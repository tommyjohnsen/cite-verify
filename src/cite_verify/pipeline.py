from __future__ import annotations

import os
from pathlib import Path

from .cache import LocalCache
from .courtlistener import CourtListenerClient, Lookup, Transport, _transport
from .extract import ExtractedCitation, extract_citations, normalize_citation
from .models import Label, Result, SourceTag
from .sidecar import load_sidecar


def _result(citation: ExtractedCitation, lookup: Lookup, tag: SourceTag) -> Result:
    authoritative = normalize_citation(lookup.authoritative) if lookup.authoritative else ""
    if lookup.status == 200 and authoritative == citation.normalized:
        label, reason, normalized = Label.VERIFIED, lookup.reason, lookup.authoritative or citation.text
    elif lookup.status == 200 and authoritative:
        label, reason, normalized = Label.CORRECTED, "authoritative form differs", lookup.authoritative
    else:
        label, reason, normalized = Label.UNVERIFIED, lookup.reason or "not looked up", citation.text
    return Result(citation.text, citation.location, label, tag, lookup.matched_field,
                  lookup.source_url, reason, normalized)


def verify_text(
    text: str,
    *,
    token: str | None = None,
    cache_dir: str | Path = ".cache/cite-verify",
    sidecar: str | Path | None = None,
    transport: Transport = _transport,
    clock=None,
    sleep=None,
    daily_budget: int = 125,
) -> list[Result]:
    citations = extract_citations(text)
    tags = load_sidecar(sidecar)
    results: list[Result] = []
    cases = [citation for citation in citations if citation.kind == "case"]
    actual_token = token if token is not None else os.environ.get("COURTLISTENER_API_TOKEN", "")
    lookups: dict[str, Lookup] = {}
    if actual_token and cases:
        kwargs = {"transport": transport, "daily_budget": daily_budget}
        if clock is not None:
            kwargs["clock"] = clock
        if sleep is not None:
            kwargs["sleep"] = sleep
        lookups = CourtListenerClient(actual_token, LocalCache(cache_dir), **kwargs).lookup(cases)
    for citation in citations:
        tag = tags.get(citation.normalized, SourceTag.PUBLIC)
        if citation.kind == "case":
            lookup = lookups.get(citation.normalized, Lookup(0, reason="no token"))
        elif citation.kind in {"id", "supra"}:
            lookup = Lookup(0, reason=f"{citation.kind} resolver not yet available")
        else:
            lookup = Lookup(0, reason="source adapter not yet available")
        results.append(_result(citation, lookup, tag))
    return results

