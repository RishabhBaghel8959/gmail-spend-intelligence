"""Deterministic, rule-based extractor.

This is the default extractor (used whenever no Gemini key is configured) and also
the fast pre-filter that decides whether an email is even worth looking at. Being
pure and rule-based means it is free, offline, and fully testable.

It answers two questions:
  - ``is_candidate(email)``  -> is this plausibly a spend email at all?
  - ``extract(email)``       -> pull out merchant / amount / date / category / type
"""
from __future__ import annotations

from .schema import ExtractedTxn, RawEmail
from . import normalize
from ..enums import Category, TxnType

# Words that signal a real transaction (as opposed to a marketing blast).
_TXN_SIGNALS = [
    "paid", "payment", "invoice", "receipt", "order", "subscription", "bill",
    "billed", "debited", "charged", "transaction", "renewal", "renewed",
    "purchase", "booking", "booked", "confirmed", "successfully paid",
    "payment successful", "amount due", "e-invoice", "tax invoice",
]

_CATEGORY_KEYWORDS: dict[Category, list[str]] = {
    Category.TRAVEL: [
        "flight", "airline", "indigo", "vistara", "air india", "makemytrip",
        "goibibo", "cleartrip", "irctc", "train ticket", "hotel", "airfare",
        "boarding pass", "pnr", "itinerary", "check-in",
    ],
    Category.FOOD_DINING: [
        "swiggy", "zomato", "restaurant", "dining", "domino", "pizza", "cafe",
        "eatery", "food order", "order from",
    ],
    Category.GROCERIES: [
        "bigbasket", "blinkit", "zepto", "grofers", "grocery", "supermarket",
        "dmart", "dunzo",
    ],
    Category.SHOPPING: [
        "amazon", "flipkart", "myntra", "ajio", "shipped", "delivered",
        "your order", "cart", "out for delivery",
    ],
    Category.SUBSCRIPTIONS: [
        "subscription", "netflix", "spotify", "prime", "hotstar", "youtube premium",
        "adobe", "openai", "github", "notion", "figma", "canva", "membership",
        "your plan", "auto-renew",
    ],
    Category.UTILITIES: [
        "electricity", "bescom", "water bill", "gas bill", "broadband", "wifi",
        "postpaid", "recharge", "dth", "tata play", "utility", "internet bill",
    ],
    Category.TRANSPORT: [
        "uber", "ola", "rapido", "cab", "ride", "fuel", "petrol", "fastag",
        "metro", "parking",
    ],
    Category.ENTERTAINMENT: [
        "bookmyshow", "movie", "concert", "event ticket", "gaming", "steam",
        "playstation",
    ],
    Category.HEALTH: [
        "pharmacy", "apollo", "1mg", "netmeds", "hospital", "clinic", "doctor",
        "medical", "medicine", "diagnostic",
    ],
    Category.FINANCIAL: [
        "emi", "loan", "interest", "credit card", "statement", "insurance",
        "premium", "mutual fund", "brokerage", "zerodha", "groww", "processing fee",
    ],
    Category.EDUCATION: [
        "course", "coursera", "udemy", "tuition", "udacity", "upgrad", "class fee",
    ],
}

_SUBSCRIPTION_HINTS = [
    "subscription", "renew", "renewal", "membership", "auto-pay", "auto-renew",
    "recurring", "monthly plan", "billing cycle", "your plan",
]
_BILL_HINTS = [
    "bill", "postpaid", "electricity", "utility", "amount due", "statement",
    "recharge", "due date",
]
_REFUND_HINTS = ["refund", "refunded", "reversal", "credited back", "money back"]
_TRANSFER_HINTS = ["transferred", "sent to", "received from", "upi to", "imps", "neft"]


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def detect_category(text: str) -> Category:
    """Highest-scoring category by keyword hits (ties resolved by enum order)."""
    best_cat = Category.OTHER
    best_score = 0
    for cat, words in _CATEGORY_KEYWORDS.items():
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best_cat, best_score = cat, score
    return best_cat


def detect_txn_type(text: str) -> TxnType:
    if _has_any(text, _REFUND_HINTS):
        return TxnType.REFUND
    if _has_any(text, _TRANSFER_HINTS):
        return TxnType.TRANSFER
    if _has_any(text, _SUBSCRIPTION_HINTS):
        return TxnType.SUBSCRIPTION
    if _has_any(text, _BILL_HINTS):
        return TxnType.BILL
    return TxnType.PURCHASE


def is_candidate(email: RawEmail) -> bool:
    """Cheap pre-filter: a real spend email has BOTH a money amount and a
    transaction signal word. This throws out newsletters that merely quote prices."""
    text = email.searchable_text
    amount, _ = normalize.parse_amount(text)
    return amount is not None and _has_any(text, _TXN_SIGNALS)


def extract(email: RawEmail) -> ExtractedTxn:
    text = email.searchable_text
    amount, currency = normalize.parse_amount(text)

    if amount is None:
        return ExtractedTxn(is_transaction=False, confidence=0.1)

    merchant, merchant_raw = normalize.canonical_merchant(
        email.sender, email.subject, email.body
    )
    category = detect_category(text)
    txn_type = detect_txn_type(text)
    txn_date = normalize.coerce_date(email.date)

    has_signal = _has_any(text, _TXN_SIGNALS)
    confidence = 0.5
    if merchant in normalize._KNOWN_MERCHANTS.values():
        confidence += 0.2
    if _has_any(text, ["invoice", "receipt", "paid", "payment successful", "debited"]):
        confidence += 0.15
    if any(sym in text for sym in ("₹", "rs.", "inr", "$", "€", "£")):
        confidence += 0.1
    confidence = round(min(confidence, 0.95), 2)

    return ExtractedTxn(
        is_transaction=has_signal,
        merchant=merchant,
        merchant_raw=merchant_raw,
        amount=amount,
        currency=currency,
        txn_date=txn_date,
        category=category,
        txn_type=txn_type,
        confidence=confidence,
    )
