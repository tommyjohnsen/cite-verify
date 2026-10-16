"""Deterministic legal citation extraction and verification."""

from .models import Label, Result, SourceTag
from .pipeline import verify_text

__all__ = ["Label", "Result", "SourceTag", "verify_text"]
__version__ = "0.1.0"

