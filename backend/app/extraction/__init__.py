"""Extraction package: turn raw emails into structured transactions."""
from __future__ import annotations

from . import llm, normalize, rules
from .pipeline import extract_one, extract_transactions, to_transaction
from .rules import is_candidate
from .schema import ExtractedTxn, RawEmail

__all__ = [
    "llm",
    "normalize",
    "rules",
    "extract_one",
    "extract_transactions",
    "to_transaction",
    "is_candidate",
    "ExtractedTxn",
    "RawEmail",
]
