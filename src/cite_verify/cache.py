from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class LocalCache:
    def __init__(self, root: str | Path = ".cache/cite-verify") -> None:
        self.root = Path(root)

    def _path(self, source: str, normalized: str) -> Path:
        digest = hashlib.sha256(f"{source}\0{normalized}".encode()).hexdigest()
        return self.root / source / f"{digest}.json"

    def get(self, source: str, normalized: str) -> dict[str, Any] | None:
        path = self._path(source, normalized)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def put(self, source: str, normalized: str, value: dict[str, Any]) -> None:
        path = self._path(source, normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

