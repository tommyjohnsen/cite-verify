from __future__ import annotations

import csv
import io

from .models import Result

FIELDS = ["cite", "location", "label", "tag", "matched_field", "source_url", "reason", "normalized_form"]


def csv_report(results: list[Result]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(result.as_dict() for result in results)
    return output.getvalue()


def markdown_report(results: list[Result]) -> str:
    def clean(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(FIELDS) + " |", "| " + " | ".join("---" for _ in FIELDS) + " |"]
    for result in results:
        values = result.as_dict()
        lines.append("| " + " | ".join(clean(values[field]) for field in FIELDS) + " |")
    return "\n".join(lines) + "\n"

