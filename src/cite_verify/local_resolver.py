from __future__ import annotations

import re

from .extract import ExtractedCitation, normalize_citation
from .models import Label, Result, SourceTag


def _names(citation: ExtractedCitation) -> set[str]:
    names: set[str] = set()
    for field in ("plaintiff", "defendant", "antecedent_guess", "author"):
        value = citation.field(field)
        if value:
            names.add(normalize_citation(value))
            names.add(normalize_citation(value.split()[-1]))
    return names


def _note_number(citation: ExtractedCitation) -> str:
    match = re.search(r"\bnote\s+(\d+)\b", citation.field("pin_cite"), re.I)
    return match.group(1) if match else ""


def resolve_local(
    citation: ExtractedCitation,
    earlier: list[ExtractedCitation],
    tag: SourceTag,
) -> Result:
    """Resolve an id. or supra reference solely from earlier draft citations."""
    target: ExtractedCitation | None = None
    matched_field = ""
    if citation.kind == "id":
        if earlier:
            target = earlier[-1]
            # Follow a local-reference chain to its underlying authority.
            seen = set()
            while target.kind in {"id", "supra"} and target.location not in seen:
                seen.add(target.location)
                preceding = [item for item in earlier if item.location < target.location]
                nested = resolve_target(target, preceding)
                if nested is None:
                    target = None
                    break
                target = nested
            matched_field = "immediately preceding authority"
    else:
        target = resolve_target(citation, earlier)
        matched_field = "short name+footnote number"

    if target is None:
        reason = ("no preceding authority for id." if citation.kind == "id"
                  else "no earlier full citation matches the supra reference")
        return Result(citation.text, citation.location, Label.UNVERIFIED, tag, matched_field,
                      "", reason, citation.text)
    return Result(citation.text, citation.location, Label.VERIFIED, tag, matched_field, "",
                  f"resolved locally to {target.text}", target.normalized)


def resolve_target(
    citation: ExtractedCitation, earlier: list[ExtractedCitation]
) -> ExtractedCitation | None:
    if citation.kind == "id":
        return earlier[-1] if earlier else None
    if citation.kind != "supra":
        return None
    name = normalize_citation(citation.field("antecedent"))
    note = _note_number(citation)
    if not name or not note:
        return None
    candidates = [
        item for item in earlier
        if item.kind not in {"id", "supra"}
        and item.field("footnote") == note
        and name in _names(item)
        and (item.kind != "case" or item.field("form") == "full")
    ]
    return candidates[-1] if candidates else None
