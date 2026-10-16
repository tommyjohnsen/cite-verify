from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from reporters_db import REPORTERS, VARIATIONS_ONLY

from .extract import ExtractedCitation, extract_all_citations, normalize_citation
from .local_resolver import resolve_target


@dataclass(frozen=True, slots=True)
class LintFinding:
    rule_id: str
    description: str
    cite: str
    location: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


RULES = {
    "CV001": "Use the standard abbreviation for a case reporter.",
    "CV002": "Include a specific page in a case short form.",
    "CV003": "Use id. only when the referenced authority is immediately preceding.",
    "CV004": "Do not use supra as a short form for a case.",
    "CV005": "Introduce an authority with a full citation before using its short form.",
}


def _finding(rule_id: str, citation: ExtractedCitation) -> LintFinding:
    return LintFinding(rule_id, RULES[rule_id], citation.text, citation.location)


def lint_text(text: str) -> list[LintFinding]:
    """Return deterministic citation-style flags without changing the input."""
    citations = extract_all_citations(text)
    findings: list[LintFinding] = []
    earlier: list[ExtractedCitation] = []
    for citation in citations:
        if citation.kind == "case":
            reporter = citation.field("reporter")
            if reporter in VARIATIONS_ONLY:
                findings.append(_finding("CV001", citation))
            if citation.field("form") == "short":
                if not citation.field("pin_cite"):
                    findings.append(_finding("CV002", citation))
                name = normalize_citation(citation.field("antecedent_guess"))
                prior_names = {
                    normalize_citation(value)
                    for old in earlier if old.kind == "case" and old.field("form") == "full"
                    for value in (old.field("plaintiff"), old.field("defendant")) if value
                }
                if not name or name not in prior_names:
                    findings.append(_finding("CV005", citation))
        elif citation.kind == "id":
            previous = earlier[-1] if earlier else None
            if (previous is None
                    or previous.kind == "other" and previous.text.strip() == "§"
                    or _ambiguous_footnote_predecessor(citation, earlier)
                    or _intervening_authority(text, previous, citation)):
                findings.append(_finding("CV003", citation))
        elif citation.kind == "supra":
            target = resolve_target(citation, earlier)
            if target is None:
                findings.append(_finding("CV005", citation))
            elif target.kind == "case":
                findings.append(_finding("CV004", citation))
        earlier.append(citation)
    findings.extend(_missing_pin_short_forms(text, citations))
    return sorted(findings, key=lambda item: (item.location, item.rule_id))


def _ambiguous_footnote_predecessor(
    current: ExtractedCitation, earlier: list[ExtractedCitation]
) -> bool:
    """Flag id. after a footnote segment containing multiple authorities."""
    if not earlier:
        return False
    current_note = current.field("footnote")
    note = (current_note if any(item.field("footnote") == current_note for item in earlier)
            else earlier[-1].field("footnote"))
    if not note:
        return False
    authorities = [
        item for item in earlier
        if item.field("footnote") == note and item.kind not in {"id", "supra", "other"}
    ]
    return len({item.normalized for item in authorities}) > 1


def _intervening_authority(
    text: str, previous: ExtractedCitation, current: ExtractedCitation
) -> bool:
    """Detect an authority-like cite between the extracted predecessor and id."""
    between = text[previous.location + len(previous.text):current.location]
    # Extractors account for recognized citations. This catches a semicolon-separated
    # unrecognized section reference without treating ordinary prose as an authority.
    return bool(re.search(r"(?:§+|\b(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\b)\s*[\w.-]+", between, re.I))


def _missing_pin_short_forms(
    text: str, citations: list[ExtractedCitation]
) -> list[LintFinding]:
    """Find reporter short forms that eyecite omits because they lack a page."""
    reporter_names = sorted(set(REPORTERS).union(VARIATIONS_ONLY).union(
        target for targets in VARIATIONS_ONLY.values() for target in targets), key=len, reverse=True)
    reporter_pattern = "|".join(re.escape(name) for name in reporter_names)
    pattern = re.compile(
        rf"\b(?P<name>[A-Z][\w'’-]+),\s+(?P<volume>\d+)\s+(?P<reporter>{reporter_pattern})"
        rf"(?![\w.]|\s+(?:at\s+)?\d)")
    occupied = [(item.location, item.location + len(item.text)) for item in citations]
    findings: list[LintFinding] = []
    for match in pattern.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in occupied):
            continue
        synthetic = ExtractedCitation(match.group(), normalize_citation(match.group()),
                                      match.start(), "case", (("form", "short"),))
        findings.append(_finding("CV002", synthetic))
        prior_names = {
            normalize_citation(value)
            for item in citations if item.location < match.start() and item.kind == "case"
            and item.field("form") == "full"
            for value in (item.field("plaintiff"), item.field("defendant")) if value
        }
        if normalize_citation(match.group("name")) not in prior_names:
            findings.append(_finding("CV005", synthetic))
    return findings


def lint_report(findings: list[LintFinding]) -> str:
    lines = ["rule\tlocation\tcitation\tdescription"]
    lines.extend(
        f"{item.rule_id}\t{item.location}\t{item.cite}\t{item.description}"
        for item in findings
    )
    return "\n".join(lines) + "\n"
