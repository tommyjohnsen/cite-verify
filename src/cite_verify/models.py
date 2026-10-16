from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class Label(StrEnum):
    VERIFIED = "Verified"
    CORRECTED = "Corrected"
    UNVERIFIED = "Unverified"


class SourceTag(StrEnum):
    LIBRARY = "LIBRARY"
    ALT = "ALT"
    PUBLIC = "PUBLIC"


@dataclass(frozen=True, slots=True)
class Result:
    cite: str
    location: int
    label: Label
    tag: SourceTag
    matched_field: str
    source_url: str
    reason: str
    normalized_form: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

