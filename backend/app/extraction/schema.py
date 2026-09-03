"""Data shapes shared by the email source (gmail) and the extraction pipeline.

- ``RawEmail`` is the normalized form of one email, whatever its origin.
- ``ExtractedTxn`` is what an extractor (rules or LLM) produces from a RawEmail.

Keeping these here means ``gmail`` and ``extraction`` agree on a contract without
importing each other.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from ..enums import Category, TxnType


class RawEmail(BaseModel):
    gmail_message_id: str
    thread_id: str | None = None
    rfc822_msgid: str | None = None
    subject: str = ""
    sender: str = ""            # raw "From" header, e.g. 'Amazon <no-reply@amazon.in>'
    date: datetime | None = None
    snippet: str = ""
    body: str = ""              # plain-text body (HTML already stripped)
    source: str = "gmail"

    @property
    def searchable_text(self) -> str:
        """Subject + snippet + body, lower-cased — what the rules scan over."""
        return f"{self.subject}\n{self.snippet}\n{self.body}".lower()


class ExtractedTxn(BaseModel):
    is_transaction: bool = False
    merchant: str | None = None
    merchant_raw: str | None = None
    amount: float | None = None
    currency: str = "INR"
    txn_date: date | None = None
    category: Category = Category.OTHER
    txn_type: TxnType = TxnType.OTHER
    confidence: float = 0.0
