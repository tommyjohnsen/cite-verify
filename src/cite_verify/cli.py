from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import verify_text
from .lint import lint_report, lint_text
from .report import csv_report, markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cite-verify")
    parser.add_argument("command_or_input")
    parser.add_argument("lint_input", nargs="?", type=Path)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--ethics-sources", type=Path,
                        help="JSON file describing official bar ethics opinion sources")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/cite-verify"))
    parser.add_argument("--format", choices=("csv", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command_or_input == "lint":
        if args.lint_input is None:
            parser.error("lint requires an input file")
        text = args.lint_input.read_text(encoding="utf-8")
        report = lint_report(lint_text(text))
        if args.output:
            args.output.write_text(report, encoding="utf-8")
        else:
            print(report, end="")
        return 0
    if args.lint_input is not None:
        parser.error("unexpected second input")
    text = Path(args.command_or_input).read_text(encoding="utf-8")
    results = verify_text(text, cache_dir=args.cache_dir, sidecar=args.sidecar,
                          ethics_sources=args.ethics_sources)
    report = csv_report(results) if args.format == "csv" else markdown_report(results)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
