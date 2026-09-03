"""Document models for MongoDB, written as Pydantic v2 classes.

Why Pydantic and not a heavy ODM? These classes give us validation and a single
definition of each document's shape, while the actual database calls stay as plain,
readable Motor queries in `repository.py`. Each model carries two helpers:

  - ``from_doc(doc)`` rebuilds the model from a raw MongoDB document, turning the
    BSON ``_id`` (an ObjectId) into a plain string ``id`` so it serializes cleanly
    to JSON for the API.
  - ``to_doc()`` turns the model back into the dict we store in MongoDB.

Three collections:
  - Transaction : one extracted financial transaction, with enough source-email
    metadata to trace it back to the exact Gmail message.
  - OAuthToken  : the user's Gmail token, encrypted at rest.
  - SyncRun     : an audit record of each sync (for the UI + debugging).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeVar

from bson import ObjectId
from pydantic import BaseModel, Field

T = TypeVar("T", bound="MongoModel")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MongoModel(BaseModel):
    """Base class that maps MongoDB's ``_id`` to a string ``id`` field."""

    id: str | None = None

    @classmethod
    def from_doc(cls: type[T], doc: dict[str, Any] | None) -> T | None:
        if doc is None:
            return None
        data = dict(doc)
        _id = data.pop("_id", None)
        if _id is not None:
            data["id"] = str(_id)
        return cls(**data)

    def to_doc(self) -> dict[str, Any]:
        """Serialize for MongoDB. Drops ``id`` when unset (so Mongo assigns an
        ObjectId), otherwise converts the string ``id`` back to an ObjectId ``_id``."""
        data = self.model_dump()
        _id = data.pop("id", None)
        if _id:
            data["_id"] = ObjectId(_id)
        return data


class Transaction(MongoModel):
    # Which connected Google account this transaction belongs to.
    account_email: str = ""

    # --- traceability: link back to the exact source email ---
    gmail_message_id: str
    thread_id: str | None = None
    rfc822_msgid: str | None = None
    subject: str | None = None
    sender: str | None = None
    snippet: str | None = None
    source: str = "gmail"

    # --- extracted, normalized fields ---
    merchant: str                       # canonical, e.g. "Amazon"
    merchant_raw: str | None = None     # what the email actually said
    amount: float = 0.0
    currency: str = "INR"               # ISO 4217
    txn_date: datetime                  # stored as a datetime (BSON has no date type)
    category: str = "Other"
    txn_type: str = "purchase"
    confidence: float = 0.0

    created_at: datetime = Field(default_factory=utcnow)


class OAuthToken(MongoModel):
    email: str
    token_encrypted: str  # Fernet-encrypted JSON of the Google credentials
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SyncRun(MongoModel):
    account_email: str | None = None
    source: str = "gmail"
    status: str = "running"  # running | success | error
    message: str | None = None
    emails_scanned: int = 0
    candidates: int = 0
    transactions_found: int = 0
    new_transactions: int = 0
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
