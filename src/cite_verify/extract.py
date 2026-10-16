from __future__ import annotations

from dataclasses import dataclass
import re

from eyecite import get_citations
from eyecite.models import FullCaseCitation, IdCitation, ShortCaseCitation, SupraCitation


@dataclass(frozen=True, slots=True)
class ExtractedCitation:
    text: str
    normalized: str
    location: int
    kind: str
    fields: tuple[tuple[str, str], ...] = ()

    def field(self, name: str, default: str = "") -> str:
        return dict(self.fields).get(name, default)


def normalize_citation(value: str) -> str:
    """Normalize spacing and punctuation for deterministic comparisons/cache keys."""
    value = value.replace("\u00a0", " ").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(r"\s*\.\s*", ".", value)
    return value.casefold()


def extract_citations(text: str) -> list[ExtractedCitation]:
    found: list[ExtractedCitation] = []
    cursor = 0
    for citation in get_citations(text):
        raw = citation.matched_text()
        start = text.find(raw, cursor)
        if start < 0:
            start = text.find(raw)
        cursor = max(cursor, start + len(raw))
        if isinstance(citation, (FullCaseCitation, ShortCaseCitation)):
            kind = "case"
        elif isinstance(citation, IdCitation):
            kind = "id"
        elif isinstance(citation, SupraCitation):
            kind = "supra"
        else:
            kind = "other"
        try:
            canonical = citation.corrected_citation()
        except (AttributeError, TypeError, ValueError):
            canonical = raw
        found.append(ExtractedCitation(raw, normalize_citation(canonical), max(0, start), kind))
    return found


_RULES = (
    ("usc", re.compile(r"\b(?P<title>\d+)\s+U\.?\s*S\.?\s*C\.?\s*§+\s*(?P<section>[\w.-]+)", re.I)),
    ("cfr", re.compile(r"\b(?P<title>\d+)\s+C\.?\s*F\.?\s*R\.?\s*§+\s*(?P<section>\d+(?:\.\d+)+)", re.I)),
    ("rcw", re.compile(r"\bRCW\s+(?P<section>\d+[A-Z]?(?:\.\d+){1,3})\b", re.I)),
    ("wac", re.compile(r"\bWAC\s+(?P<section>\d+(?:-\d+){2,3})\b", re.I)),
)
_DOI = re.compile(r"(?<![\w/])(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
_ARTICLE = re.compile(
    r"(?P<author>[A-Z][\w'’-]+(?:\s+(?:&|and)\s+[A-Z][\w'’-]+)?),\s*"
    r"(?P<title>[^,\n]{5,160}),\s*(?P<volume>\d+)\s+"
    r"(?P<journal>[A-Z][A-Za-z.&' -]{2,80})\s+(?P<page>\d+)\s*\((?P<year>\d{4})\)",
)


def extract_rule_citations(text: str) -> list[ExtractedCitation]:
    """Extract open-source citation families with deterministic regular expressions."""
    found: list[ExtractedCitation] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in _RULES:
        for match in pattern.finditer(text):
            found.append(ExtractedCitation(match.group(), normalize_citation(match.group()), match.start(), kind,
                                           tuple(match.groupdict().items())))
            occupied.append(match.span())
    for match in _DOI.finditer(text):
        raw = match.group(1).rstrip(".,;)")
        found.append(ExtractedCitation(raw, normalize_citation(raw), match.start(1), "journal",
                                       (("doi", raw.casefold()),)))
        occupied.append(match.span())
    for match in _ARTICLE.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in occupied):
            continue
        found.append(ExtractedCitation(match.group(), normalize_citation(match.group()), match.start(), "journal",
                                       tuple((key, value.strip()) for key, value in match.groupdict().items())))
    return sorted(found, key=lambda item: item.location)


def extract_all_citations(text: str) -> list[ExtractedCitation]:
    """Combine eyecite output and rule-based families without overlapping matches."""
    primary = extract_citations(text)
    rules = extract_rule_citations(text)
    def overlaps(left: ExtractedCitation, right: ExtractedCitation) -> bool:
        return left.location < right.location + len(right.text) and right.location < left.location + len(left.text)

    # eyecite intentionally recognizes some non-case citations as ``other``;
    # prefer the structured rule parser for those same spans.
    combined = [item for item in primary if item.kind != "other" or not any(overlaps(item, rule) for rule in rules)]
    for item in rules:
        item_end = item.location + len(item.text)
        if not any(old.location < item_end and item.location < old.location + len(old.text)
                   for old in combined):
            combined.append(item)
    return sorted(combined, key=lambda item: item.location)
