"""API request/response models (kept separate from the DB document models).

Separating these means the shape we send to the frontend can evolve independently
of how we store data, and lets us add computed fields like ``gmail_link`` (a direct
link back to the source email — the traceability the task asks for).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .models import Transaction

GMAIL_MESSAGE_URL = "https://mail.google.com/mail/u/0/#all/"


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
class TransactionOut(BaseModel):
    id: str | None
    merchant: str
    merchant_raw: str | None = None
    amount: float
    currency: str
    date: str            # YYYY-MM-DD
    category: str
    txn_type: str
    source: str
    confidence: float
    # traceability back to the source email
    subject: str | None = None
    sender: str | None = None
    snippet: str | None = None
    gmail_message_id: str
    gmail_link: str


def transaction_to_out(txn: Transaction) -> TransactionOut:
    return TransactionOut(
        id=txn.id,
        merchant=txn.merchant,
        merchant_raw=txn.merchant_raw,
        amount=txn.amount,
        currency=txn.currency,
        date=txn.txn_date.date().isoformat(),
        category=txn.category,
        txn_type=txn.txn_type,
        source=txn.source,
        confidence=txn.confidence,
        subject=txn.subject,
        sender=txn.sender,
        snippet=txn.snippet,
        gmail_message_id=txn.gmail_message_id,
        gmail_link=f"{GMAIL_MESSAGE_URL}{txn.gmail_message_id}",
    )


# --------------------------------------------------------------------------- #
# Spending profile
# --------------------------------------------------------------------------- #
class CategorySlice(BaseModel):
    category: str
    amount: float
    count: int
    percent: float


class MerchantSlice(BaseModel):
    merchant: str
    amount: float
    count: int
    percent: float


class MonthPoint(BaseModel):
    month: str  # YYYY-MM
    amount: float
    count: int


class RecurringItem(BaseModel):
    merchant: str
    category: str
    currency: str
    cadence: str            # "monthly" | "weekly" | "irregular"
    average_amount: float
    total_amount: float
    occurrences: int
    last_date: str
    next_expected: str | None = None
    transaction_ids: list[str] = []


class SpendingProfile(BaseModel):
    account_email: str | None = None
    currency: str = "INR"
    total_spent: float = 0.0
    transaction_count: int = 0
    spend_transaction_count: int = 0
    first_date: str | None = None
    last_date: str | None = None
    by_category: list[CategorySlice] = []
    by_merchant: list[MerchantSlice] = []
    monthly: list[MonthPoint] = []
    recurring: list[RecurringItem] = []
    recurring_monthly_estimate: float = 0.0


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #
class Insight(BaseModel):
    type: str            # top_category | spike | new_merchant | recurring | upcoming
    severity: str        # info | warning
    title: str
    text: str
    amount: float | None = None
    merchant: str | None = None
    transaction_ids: list[str] = []


class InsightsResponse(BaseModel):
    insights: list[Insight] = []
    anomalies: list[Insight] = []
    generated_from: int = 0


# --------------------------------------------------------------------------- #
# Auth + sync
# --------------------------------------------------------------------------- #
class AuthStatus(BaseModel):
    configured: bool
    connected: bool
    email: str | None = None


class SyncRequest(BaseModel):
    months: int | None = None
    max_emails: int | None = None


class SyncResult(BaseModel):
    status: str
    message: str | None = None
    account_email: str | None = None
    emails_scanned: int = 0
    candidates: int = 0
    transactions_found: int = 0
    new_transactions: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
