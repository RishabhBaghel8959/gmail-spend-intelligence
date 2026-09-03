"""Optional LLM extractor using Google Gemini.

Used only when a ``GEMINI_API_KEY`` is set and ``MOCK_LLM`` is off. It asks Gemini
to read one email and return a small, strict JSON object describing the transaction.
An LLM handles the endless variety of real-world receipt wording far better than
regexes; the rule-based extractor stays as the always-available fallback.

We keep the model on a tight leash: JSON-only output, temperature 0, a fixed
vocabulary for category/type, and defensive parsing so a malformed reply never
crashes a sync (the pipeline falls back to rules in that case).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .schema import ExtractedTxn, RawEmail
from . import normalize
from ..config import settings
from ..enums import Category, TxnType

logger = logging.getLogger(__name__)

_CATEGORIES = ", ".join(c.value for c in Category)
_TXN_TYPES = ", ".join(t.value for t in TxnType)

_PROMPT = """You are a precise financial-email parser. Read ONE email and decide whether it \
records a real money transaction by THIS user (a purchase, subscription charge, \
bill payment, refund, or transfer) — NOT a promotion, price drop, or newsletter.

Return ONLY a JSON object with exactly these keys:
{{
  "is_transaction": boolean,
  "merchant": string,            // the company charged, e.g. "Amazon", "Netflix"
  "amount": number,              // the total amount, digits only (e.g. 1299.00)
  "currency": string,            // ISO code: INR, USD, EUR, GBP
  "date": string,                // transaction date as YYYY-MM-DD
  "category": string,            // one of: {categories}
  "txn_type": string,            // one of: {txn_types}
  "confidence": number           // 0.0 - 1.0
}}
If it is not a transaction, set "is_transaction" to false and "amount" to 0.

EMAIL
-----
From: {sender}
Date: {date}
Subject: {subject}

{body}
"""


def _is_retryable_error(exc: BaseException) -> bool:
    """Retry temporary failures, but not invalid keys, models, or requests."""
    try:
        from google.genai.errors import APIError
    except ImportError:
        return True

    if isinstance(exc, APIError):
        # Rate limits and server errors can recover; other 4xx responses cannot
        # and retrying them once per email makes a sync unnecessarily slow.
        return exc.code == 429 or exc.code >= 500
    return True


@lru_cache(maxsize=1)
def _client():
    # Imported lazily so the app doesn't require the SDK/key unless the LLM is used.
    from google import genai

    return genai.Client(api_key=settings.gemini_api_key)


def available() -> bool:
    return settings.use_llm


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _generate(prompt: str) -> str:
    from google.genai import types

    resp = _client().models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    return resp.text or ""


def extract(email: RawEmail) -> ExtractedTxn:
    prompt = _PROMPT.format(
        categories=_CATEGORIES,
        txn_types=_TXN_TYPES,
        sender=email.sender,
        date=email.date.isoformat() if email.date else "",
        subject=email.subject,
        body=email.body[: settings.body_char_limit],
    )
    raw = _generate(prompt)
    data = json.loads(raw)

    amount = data.get("amount")
    try:
        amount = float(amount) if amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None

    merchant = (data.get("merchant") or "").strip() or None
    return ExtractedTxn(
        is_transaction=bool(data.get("is_transaction", False)),
        merchant=merchant,
        merchant_raw=merchant,
        amount=amount,
        currency=(str(data.get("currency") or "INR").upper()[:3]),
        txn_date=normalize.coerce_date(data.get("date")),
        category=normalize.to_category(data.get("category")),
        txn_type=normalize.to_txn_type(data.get("txn_type")),
        confidence=float(data.get("confidence", 0.6) or 0.6),
    )
