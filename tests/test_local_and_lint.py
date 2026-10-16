from __future__ import annotations

from pathlib import Path

from cite_verify.cli import main
from cite_verify.lint import RULES, lint_text
from cite_verify.models import Label
from cite_verify.pipeline import verify_text


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_id_and_supra_resolve_locally_without_http(tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("local references must not use HTTP")

    results = verify_text(
        fixture("id_supra.md"), token="", cache_dir=tmp_path,
        transport=forbidden, source_transport=forbidden,
    )
    local = [result for result in results if result.cite.casefold().startswith(("id.", "supra"))]
    assert [result.label for result in local] == [Label.VERIFIED, Label.VERIFIED, Label.UNVERIFIED]
    assert local[0].matched_field == "immediately preceding authority"
    assert local[1].matched_field == "short name+footnote number"
    assert local[0].source_url == local[1].source_url == ""
    assert "no earlier full citation" in local[2].reason


def test_each_lint_rule_is_planted_and_descriptions_are_one_line() -> None:
    findings = lint_text(fixture("lint_errors.md"))
    assert {finding.rule_id for finding in findings} == set(RULES)
    assert all("\n" not in description and description for description in RULES.values())


def test_clean_draft_has_no_lint_findings() -> None:
    assert lint_text(fixture("lint_clean.md")) == []


def test_lint_cli_is_flag_only(tmp_path: Path, capsys) -> None:
    source = tmp_path / "draft.md"
    original = fixture("lint_errors.md")
    source.write_text(original, encoding="utf-8")
    assert main(["lint", str(source)]) == 0
    assert "CV001" in capsys.readouterr().out
    assert source.read_text(encoding="utf-8") == original
