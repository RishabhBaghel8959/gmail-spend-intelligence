"""Gmail package: read-only search + fetch of spend-related emails."""
from __future__ import annotations

from .client import build_service, fetch_emails, fetch_message, search_message_ids
from .query import build_query

__all__ = [
    "build_service",
    "fetch_emails",
    "fetch_message",
    "search_message_ids",
    "build_query",
]
