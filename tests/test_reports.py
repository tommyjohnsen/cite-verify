from __future__ import annotations

from pathlib import Path

from cite_verify.models import Label, Result, SourceTag
from cite_verify.report import csv_report, markdown_report


FIXTURES = Path(__file__).parent / "fixtures"


def sample_results() -> list[Result]:
    return [
        Result(
            "123 F.3d 456",
            7,
            Label.VERIFIED,
            SourceTag.PUBLIC,
            "reporter+volume+page",
            "https://www.courtlistener.com/opinion/123/",
            "exact citation match",
            "123 F.3d 456",
        ),
        Result(
            "Smith, Synthetic Study",
            42,
            Label.CORRECTED,
            SourceTag.ALT,
            "title",
            "https://api.crossref.org/works/10.5555/example.17",
            "authoritative form differs, punctuation normalized",
            "Smith, Synthetic Study (2024)",
        ),
        Result(
            "Unknown Authority",
            88,
            Label.UNVERIFIED,
            SourceTag.LIBRARY,
            "",
            "",
            "not found",
            "Unknown Authority",
        ),
    ]


def test_csv_report_matches_golden_file() -> None:
    expected = (FIXTURES / "report.csv").read_text(encoding="utf-8")
    assert csv_report(sample_results()) == expected


def test_markdown_report_matches_golden_file() -> None:
    expected = (FIXTURES / "report.md").read_text(encoding="utf-8")
    assert markdown_report(sample_results()) == expected
