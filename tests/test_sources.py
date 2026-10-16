from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cite_verify.cache import LocalCache
from cite_verify.extract import ExtractedCitation, extract_rule_citations, normalize_citation
from cite_verify.models import Label
from cite_verify.pipeline import verify_text
from cite_verify.source_adapters import (
    BarEthicsAdapter, CrossrefAdapter, ECFRAdapter, GovInfoAdapter,
    OpenAlexAdapter, WashingtonAdapter, extract_ethics_citations,
    load_ethics_sources,
)

FIXTURES = Path(__file__).parent / "fixtures"


def parsed(kind: str, text: str, **fields: str) -> ExtractedCitation:
    return ExtractedCitation(text, normalize_citation(text), 0, kind, tuple(fields.items()))


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_rule_parsers_cover_statutes_regulations_and_journals() -> None:
    text = ("42 U.S.C. § 123; 7 C.F.R. § 1.2; RCW 1.02.030; WAC 10-20-030; "
            "10.5555/example.17; Smith, A Synthetic Article, 12 Example Journal 34 (2024).")
    found = extract_rule_citations(text)
    assert [item.kind for item in found] == ["usc", "cfr", "rcw", "wac", "journal", "journal"]
    assert found[0].field("section") == "123"


def test_govinfo_match_missing_key_not_found_and_no_secret_cache(tmp_path: Path) -> None:
    cite = parsed("usc", "42 USC § 123", title="42", section="123")
    assert "no GOVINFO_API_KEY" in GovInfoAdapter("", LocalCache(tmp_path)).verify(cite).reason
    calls = []

    def transport(url, headers):
        calls.append(url)
        assert parse_qs(urlsplit(url).query)["api_key"] == ["runtime-key"]
        return 200, {}, fixture("govinfo_results.json")

    adapter = GovInfoAdapter("runtime-key", LocalCache(tmp_path), transport)
    assert adapter.verify(cite).status == 200
    assert adapter.verify(cite).status == 200
    assert len(calls) == 1
    assert "runtime-key" not in "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    missing = GovInfoAdapter("runtime-key", LocalCache(tmp_path / "missing"),
                             lambda *_: (404, {}, b"{}"))
    assert missing.verify(cite).reason == "not found"


def test_ecfr_verified_and_corrected_pipeline_results(tmp_path: Path) -> None:
    def transport(url, headers):
        assert url.startswith("https://www.ecfr.gov/api/versioner/v1/")
        return 200, {}, fixture("ecfr_result.json")

    exact = parsed("cfr", "7 C.F.R. § 1.2", title="7", section="1.2")
    assert ECFRAdapter(LocalCache(tmp_path), transport).verify(exact).status == 200
    result = verify_text("7 CFR § 1.2", token="", cache_dir=tmp_path / "pipeline",
                         govinfo_api_key="", source_transport=transport)[0]
    assert result.label is Label.CORRECTED
    assert result.matched_field == "section number"
    assert result.source_url.startswith("https://www.ecfr.gov/")


def test_ecfr_not_found(tmp_path: Path) -> None:
    cite = parsed("cfr", "7 C.F.R. § 9.9", title="7", section="9.9")
    result = ECFRAdapter(LocalCache(tmp_path), lambda *_: (404, {}, b"{}")).verify(cite)
    assert result.status == 404


def test_washington_html_match_not_found_and_cache_reuse(tmp_path: Path) -> None:
    calls = 0

    def transport(url, headers):
        nonlocal calls
        calls += 1
        assert url.startswith("https://app.leg.wa.gov/RCW/")
        return 200, {}, fixture("washington_result.html")

    cite = parsed("rcw", "RCW 1.02.030", section="1.02.030")
    adapter = WashingtonAdapter(LocalCache(tmp_path), transport)
    assert adapter.verify(cite).reason.startswith("section exists")
    assert adapter.verify(cite).matched_field == "section number"
    assert calls == 1
    absent = parsed("wac", "WAC 10-20-999", section="10-20-999")
    missing = WashingtonAdapter(LocalCache(tmp_path / "missing"),
                                lambda *_: (200, {}, fixture("washington_result.html"))).verify(absent)
    assert missing.status == 404


def test_crossref_doi_match_not_found_and_cache(tmp_path: Path) -> None:
    calls = 0

    def transport(url, headers):
        nonlocal calls
        calls += 1
        assert url.startswith("https://api.crossref.org/")
        assert parse_qs(urlsplit(url).query)["mailto"] == ["you@example.com"]
        return 200, {}, fixture("crossref_result.json")

    cite = parsed("journal", "10.5555/example.17", doi="10.5555/example.17")
    adapter = CrossrefAdapter(LocalCache(tmp_path), contact_email="you@example.com", transport=transport)
    assert adapter.verify(cite).reason == "exact DOI match"
    assert adapter.verify(cite).status == 200
    assert calls == 1
    missing = CrossrefAdapter(LocalCache(tmp_path / "missing"), transport=lambda *_: (404, {}, b"{}"))
    assert missing.verify(cite).status == 404


def test_openalex_fuzzy_metadata_is_corrected_and_below_threshold_is_missing(tmp_path: Path) -> None:
    body = fixture("openalex_result.json")
    close = parsed("journal", "Smith, A Synthetic Article Revise, 12 Example Journal 34 (2024)",
                   author="Smith", title="A Synthetic Article Revise", volume="12",
                   journal="Example Journal", page="34", year="2024")
    adapter = OpenAlexAdapter(LocalCache(tmp_path), transport=lambda *_: (200, {}, body))
    lookup = adapter.verify(close)
    assert lookup.status == 200
    assert lookup.reason.startswith("fuzzy title match")
    result = verify_text(close.text, token="", cache_dir=tmp_path / "pipeline",
                         source_transport=lambda url, headers: (404, {}, b"{}") if "crossref" in url else (200, {}, body))[0]
    assert result.label is Label.CORRECTED
    far = parsed("journal", "Smith, Unrelated Subject Matter, 12 Example Journal 34 (2024)",
                 author="Smith", title="Unrelated Subject Matter", volume="12",
                 journal="Example Journal", page="34", year="2024")
    assert OpenAlexAdapter(LocalCache(tmp_path / "far"), transport=lambda *_: (200, {}, body)).verify(far).status == 404


def test_ethics_sources_match_corrected_not_found_and_cache(tmp_path: Path) -> None:
    sources = load_ethics_sources(FIXTURES / "ethics_sources.json")
    citations = extract_ethics_citations("EXB Opinion 17, Synthetic conflicts guidance.", sources)
    assert len(citations) == 1
    calls = 0

    def transport(url, headers):
        nonlocal calls
        calls += 1
        assert url == "https://example.com/opinions/17"
        return 200, {}, fixture("ethics_result.html")

    adapter = BarEthicsAdapter(LocalCache(tmp_path), transport)
    assert adapter.verify(citations[0]).status == 200
    assert adapter.verify(citations[0]).status == 200
    assert calls == 1
    result = verify_text("EXB Opinion 17, Synthetic conflicts guidance.", token="",
                         cache_dir=tmp_path / "pipeline", ethics_sources=FIXTURES / "ethics_sources.json",
                         source_transport=transport)[0]
    assert result.label is Label.CORRECTED
    bad = extract_ethics_citations("EXB Opinion 99.", sources)[0]
    assert BarEthicsAdapter(LocalCache(tmp_path / "bad"),
                            lambda *_: (200, {}, fixture("ethics_result.html"))).verify(bad).status == 404
