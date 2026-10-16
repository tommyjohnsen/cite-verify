from __future__ import annotations

import json
from pathlib import Path

import pytest

from cite_verify.cache import LocalCache
from cite_verify.courtlistener import CourtListenerClient, Lookup, make_batches
from cite_verify.extract import ExtractedCitation, extract_citations, normalize_citation
from cite_verify.models import Label, SourceTag
from cite_verify.pipeline import verify_text
from cite_verify.report import csv_report, markdown_report

FIXTURE = Path(__file__).parent / "fixtures" / "courtlistener_results.json"


def citation(text: str, number: int = 0) -> ExtractedCitation:
    return ExtractedCitation(text, normalize_citation(text), number, "case")


def test_extracts_case_and_no_token_mode(tmp_path: Path) -> None:
    results = verify_text("Alpha v. Beta, 123 F.3d 456 (9th Cir. 2001).", token="", cache_dir=tmp_path)
    assert len(results) == 1
    assert results[0].cite == "123 F.3d 456"
    assert results[0].label is Label.UNVERIFIED
    assert results[0].reason == "no token"


def test_verified_corrected_and_unverified_labels(tmp_path: Path) -> None:
    body = FIXTURE.read_bytes()

    def transport(url, headers, payload):
        assert url.startswith("https://www.courtlistener.com/")
        assert json.loads(payload)["text"].count("\n") == 2
        return 200, {}, body

    text = "123 F.3d 456; 77 U.S. 88; 99 F.2d 101."
    results = verify_text(text, token="sample-token", cache_dir=tmp_path, transport=transport)
    assert [result.label for result in results] == [Label.VERIFIED, Label.CORRECTED, Label.UNVERIFIED]
    assert results[1].normalized_form == "78 U.S. 88"
    assert results[0].matched_field == "reporter+volume+page"
    assert results[0].source_url.startswith("https://www.courtlistener.com/")


def test_batching_splits_on_count_and_characters() -> None:
    many = [citation(f"{index} F.3d 1") for index in range(251)]
    assert [len(batch) for batch in make_batches(many)] == [250, 1]
    large = [citation("A" * 32_000), citation("B" * 32_000)]
    assert [len(batch) for batch in make_batches(large)] == [1, 1]
    with pytest.raises(ValueError):
        make_batches([citation("X" * 64_001)])


def test_429_retry_after_and_twelve_second_spacing(tmp_path: Path) -> None:
    now = [0.0]
    sleeps: list[float] = []
    replies = [(429, {"Retry-After": "7"}, b"{}"), (200, {}, b'{"results":[{"citation":"1 F.3d 2"}]}')]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def transport(url, headers, payload):
        return replies.pop(0)

    client = CourtListenerClient("sample-token", LocalCache(tmp_path), transport=transport,
                                 clock=lambda: now[0], sleep=sleep)
    result = client.lookup([citation("1 F.3d 2")])
    assert result[normalize_citation("1 F.3d 2")].status == 200
    assert sleeps == [7.0, 5.0]


def test_daily_budget_stops_without_extra_request(tmp_path: Path) -> None:
    calls = 0

    def transport(url, headers, payload):
        nonlocal calls
        calls += 1
        return 429, {"Retry-After": "0"}, b"{}"

    client = CourtListenerClient("sample-token", LocalCache(tmp_path), transport=transport,
                                 sleep=lambda _: None, daily_budget=1)
    value = client.lookup([citation("2 F.3d 3")])[normalize_citation("2 F.3d 3")]
    assert calls == 1
    assert value.reason == "daily budget exhausted"


def test_cache_reuse_avoids_http(tmp_path: Path) -> None:
    cache = LocalCache(tmp_path)
    key = normalize_citation("3 F.3d 4")
    cache.put("courtlistener", key, Lookup(200, "3 F.3d 4", "", "reporter+volume+page", "cached").cache_value())

    def forbidden(*args):
        raise AssertionError("HTTP should not be called")

    result = CourtListenerClient("sample-token", cache, transport=forbidden).lookup([citation("3 F.3d 4")])
    assert result[key].reason == "cached"


def test_token_never_appears_in_output_or_cache(tmp_path: Path) -> None:
    secret = "private-sample-token"

    def transport(url, headers, payload):
        assert headers["Authorization"] == f"Token {secret}"
        return 404, {}, b"{}"

    results = verify_text("4 F.3d 5", token=secret, cache_dir=tmp_path, transport=transport)
    rendered = csv_report(results) + markdown_report(results)
    cached = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert secret not in rendered
    assert secret not in cached


def test_sidecar_json_tag(tmp_path: Path) -> None:
    sidecar = tmp_path / "tags.json"
    sidecar.write_text('{"5 F.3d 6":"ALT"}', encoding="utf-8")
    result = verify_text("5 F.3d 6", token="", cache_dir=tmp_path / "cache", sidecar=sidecar)[0]
    assert result.tag is SourceTag.ALT
