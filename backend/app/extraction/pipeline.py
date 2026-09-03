"""The extraction pipeline: RawEmail -> Transaction.

For each email we:
  1. skip it unless it looks like a real spend email (``rules.is_candidate``);
  2. extract structured fields, using Gemini when configured and always falling
     back to the rule-based extractor if the LLM is off or errors;
  3. turn a positive result into a ``Transaction`` ready to store, dropping
     anything that isn't actually a transaction or has no usable amount.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from . import llm, normalize, rules
from .schema import ExtractedTxn, RawEmail
from ..config import settings
from ..enums import Category, TxnType
from ..models import Transaction

logger = logging.getLogger(__name__)


def extract_one(email: RawEmail) -> ExtractedTxn:
    """Extract one email with the best available method (LLM, else rules)."""
    if settings.use_llm:
        try:
            return llm.extract(email)
        except Exception as exc:  # network error, bad JSON, quota, etc.
            logger.warning(
                "LLM extraction failed for %s (%s); using rules fallback",
                email.gmail_message_id, exc,
            )
    return rules.extract(email)


def to_transaction(
    email: RawEmail, ex: ExtractedTxn, account_email: str
) -> Transaction | None:
    if not ex.is_transaction or not ex.amount or ex.amount <= 0:
        return None

    txn_date = ex.txn_date or normalize.coerce_date(email.date)
    if txn_date is None:
        txn_date = datetime.now(timezone.utc).date()
    # MongoDB stores datetimes (not bare dates), so anchor to midnight UTC.
    txn_dt = datetime.combine(txn_date, time.min, tzinfo=timezone.utc)

    merchant = ex.merchant or normalize.canonical_merchant(email.sender, email.subject)[0]
    category = ex.category.value if isinstance(ex.category, Category) else str(ex.category)
    txn_type = ex.txn_type.value if isinstance(ex.txn_type, TxnType) else str(ex.txn_type)

    return Transaction(
        account_email=account_email,
        gmail_message_id=email.gmail_message_id,
        thread_id=email.thread_id,
        rfc822_msgid=email.rfc822_msgid,
        subject=email.subject,
        sender=email.sender,
        snippet=email.snippet,
        source=email.source,
        merchant=merchant,
        merchant_raw=ex.merchant_raw,
        amount=round(float(ex.amount), 2),
        currency=ex.currency or "INR",
        txn_date=txn_dt,
        category=category,
        txn_type=txn_type,
        confidence=round(float(ex.confidence), 2),
    )


def extract_transactions(
    emails: list[RawEmail], account_email: str
) -> list[Transaction]:
    """Full pipeline over a batch of raw emails (self-contained: filters + extracts)."""
    out: list[Transaction] = []
    for email in emails:
        if not rules.is_candidate(email):
            continue
        txn = to_transaction(email, extract_one(email), account_email)
        if txn is not None:
            out.append(txn)
    return out
