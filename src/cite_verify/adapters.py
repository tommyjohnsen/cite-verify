from __future__ import annotations

from typing import Protocol

from .extract import ExtractedCitation
from .models import Result


class SourceAdapter(Protocol):
    """Hook implemented by later authoritative-source adapters."""

    def supports(self, citation: ExtractedCitation) -> bool: ...

    def verify(self, citation: ExtractedCitation) -> Result: ...


class StatuteAdapter(SourceAdapter, Protocol): ...
class JournalAdapter(SourceAdapter, Protocol): ...
class EthicsOpinionAdapter(SourceAdapter, Protocol): ...
class LocalReferenceAdapter(SourceAdapter, Protocol):
    """Hook for deterministic id. and supra resolution within one draft."""


from .source_adapters import (  # noqa: E402,F401 - public adapter imports
    BarEthicsAdapter, CrossrefAdapter, ECFRAdapter, GovInfoAdapter,
    OpenAlexAdapter, WashingtonAdapter,
)
