from __future__ import annotations

import os
from pathlib import Path

from .cache import LocalCache
from .courtlistener import CourtListenerClient, Lookup, Transport, _transport
from .extract import ExtractedCitation, extract_all_citations, normalize_citation
from .models import Label, Result, SourceTag
from .local_resolver import resolve_local
from .sidecar import load_sidecar
from .source_adapters import (
    BarEthicsAdapter, CrossrefAdapter, ECFRAdapter, GetTransport, GovInfoAdapter,
    OpenAlexAdapter, WashingtonAdapter, extract_ethics_citations, get_transport,
    load_ethics_sources,
)


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
    source_transport: GetTransport = get_transport,
    govinfo_api_key: str | None = None,
    contact_email: str | None = None,
    openalex_api_key: str | None = None,
    ethics_sources: str | Path | None = None,
) -> list[Result]:
    citations = extract_all_citations(text)
    configured_ethics = load_ethics_sources(ethics_sources)
    citations.extend(extract_ethics_citations(text, configured_ethics))
    citations.sort(key=lambda item: item.location)
    tags = load_sidecar(sidecar)
    results: list[Result] = []
    cache = LocalCache(cache_dir)
    cases = [citation for citation in citations if citation.kind == "case"]
    actual_token = token if token is not None else os.environ.get("COURTLISTENER_API_TOKEN", "")
    lookups: dict[str, Lookup] = {}
    if actual_token and cases:
        kwargs = {"transport": transport, "daily_budget": daily_budget}
        if clock is not None:
            kwargs["clock"] = clock
        if sleep is not None:
            kwargs["sleep"] = sleep
        lookups = CourtListenerClient(actual_token, cache, **kwargs).lookup(cases)

    key = govinfo_api_key if govinfo_api_key is not None else os.environ.get("GOVINFO_API_KEY", "")
    email = contact_email if contact_email is not None else os.environ.get("CONTACT_EMAIL", "")
    oa_key = openalex_api_key if openalex_api_key is not None else os.environ.get("OPENALEX_API_KEY", "")
    govinfo = GovInfoAdapter(key, cache, source_transport)
    ecfr = ECFRAdapter(cache, source_transport)
    washington = WashingtonAdapter(cache, source_transport)
    crossref = CrossrefAdapter(cache, contact_email=email, transport=source_transport)
    openalex = OpenAlexAdapter(cache, contact_email=email, api_key=oa_key, transport=source_transport)
    ethics = BarEthicsAdapter(cache, source_transport)
    earlier: list[ExtractedCitation] = []
    for citation in citations:
        tag = tags.get(citation.normalized, SourceTag.PUBLIC)
        if citation.kind == "case":
            lookup = lookups.get(citation.normalized, Lookup(0, reason="no token"))
        elif citation.kind in {"id", "supra"}:
            results.append(resolve_local(citation, earlier, tag))
            earlier.append(citation)
            continue
        elif citation.kind == "usc":
            lookup = govinfo.verify(citation)
        elif citation.kind == "cfr":
            lookup = govinfo.verify(citation)
            if lookup.status != 200:
                lookup = ecfr.verify(citation)
        elif citation.kind in {"rcw", "wac"}:
            lookup = washington.verify(citation)
        elif citation.kind == "journal":
            lookup = crossref.verify(citation)
            if lookup.status != 200:
                lookup = openalex.verify(citation)
        elif citation.kind == "ethics":
            lookup = ethics.verify(citation)
        else:
            lookup = Lookup(0, reason="source adapter not yet available")
        results.append(_result(citation, lookup, tag))
        earlier.append(citation)
    return results
