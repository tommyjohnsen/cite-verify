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
        fields: dict[str, str] = {}
        metadata = citation.metadata
        if isinstance(citation, (FullCaseCitation, ShortCaseCitation)):
            kind = "case"
            fields["form"] = "full" if isinstance(citation, FullCaseCitation) else "short"
            for name in ("plaintiff", "defendant", "antecedent_guess", "pin_cite"):
                value = getattr(metadata, name, None)
                if value:
                    fields[name] = str(value)
            reporter = getattr(citation, "groups", {}).get("reporter")
            if reporter:
                fields["reporter"] = reporter
            if isinstance(citation, ShortCaseCitation):
                line_start = text.rfind("\n", 0, start) + 1
                prefix = text[line_start:start]
                local_name = re.search(r"([A-Z][\w'’-]*)\s*,\s*$", prefix)
                if local_name:
                    fields["antecedent_guess"] = local_name.group(1)
        elif isinstance(citation, IdCitation):
            kind = "id"
            pin = getattr(metadata, "pin_cite", None)
            if pin:
                fields["pin_cite"] = str(pin)
        elif isinstance(citation, SupraCitation):
            kind = "supra"
            antecedent = getattr(metadata, "antecedent_guess", None)
            pin = getattr(metadata, "pin_cite", None)
            if antecedent:
                fields["antecedent"] = str(antecedent)
            if pin:
                fields["pin_cite"] = str(pin)
        else:
            kind = "other"
        try:
            canonical = citation.corrected_citation()
        except (AttributeError, TypeError, ValueError):
            canonical = raw
        footnote = _footnote_at(text, max(0, start))
        if footnote:
            fields["footnote"] = footnote
        found.append(ExtractedCitation(raw, normalize_citation(canonical), max(0, start), kind,
                                       tuple(fields.items())))
    return found


_FOOTNOTE = re.compile(r"(?m)^\[\^(?P<number>[^\]]+)\]:")


def _footnote_at(text: str, location: int) -> str:
    """Return the Markdown footnote label containing ``location``, if any."""
    matches = list(_FOOTNOTE.finditer(text, 0, location + 1))
    if not matches:
        return ""
    match = matches[-1]
    line_start = text.rfind("\n", 0, location) + 1
    if line_start == match.start() or text[line_start:location].startswith(("    ", "\t")):
        return match.group("number")
    # A later unindented line ends a footnote definition.
    between = text[match.end():location]
    if "\n" not in between:
        return match.group("number")
    lines = between.splitlines()[1:]
    return match.group("number") if all(not line or line.startswith(("    ", "\t")) for line in lines) else ""


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
    enriched: list[ExtractedCitation] = []
    for item in combined:
        if not item.field("footnote"):
            note = _footnote_at(text, item.location)
            if note:
                item = ExtractedCitation(item.text, item.normalized, item.location, item.kind,
                                         item.fields + (("footnote", note),))
        enriched.append(item)
    return sorted(enriched, key=lambda item: item.location)
