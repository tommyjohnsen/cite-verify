"""Deterministic legal citation extraction and verification."""

from .models import Label, Result, SourceTag
from .pipeline import verify_text
from .source_adapters import FUZZY_THRESHOLD

__all__ = ["FUZZY_THRESHOLD", "Label", "Result", "SourceTag", "verify_text"]
__version__ = "0.1.0"
