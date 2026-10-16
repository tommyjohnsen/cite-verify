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

