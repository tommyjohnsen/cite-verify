from __future__ import annotations

import csv
import json
from pathlib import Path

from .extract import normalize_citation
from .models import SourceTag


def load_sidecar(path: str | Path | None) -> dict[str, SourceTag]:
    if path is None:
        return {}
    source = Path(path)
    if source.suffix.casefold() == ".json":
        raw = json.loads(source.read_text(encoding="utf-8"))
        rows = raw.items() if isinstance(raw, dict) else ((r["citation"], r["tag"]) for r in raw)
    else:
        with source.open(newline="", encoding="utf-8") as handle:
            rows = [(r["citation"], r["tag"]) for r in csv.DictReader(handle)]
    return {normalize_citation(str(cite)): SourceTag(str(tag).upper()) for cite, tag in rows}

