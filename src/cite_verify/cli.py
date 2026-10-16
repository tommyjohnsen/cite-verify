from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import verify_text
from .report import csv_report, markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cite-verify")
    parser.add_argument("input", type=Path)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/cite-verify"))
    parser.add_argument("--format", choices=("csv", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    text = args.input.read_text(encoding="utf-8")
    results = verify_text(text, cache_dir=args.cache_dir, sidecar=args.sidecar)
    report = csv_report(results) if args.format == "csv" else markdown_report(results)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
