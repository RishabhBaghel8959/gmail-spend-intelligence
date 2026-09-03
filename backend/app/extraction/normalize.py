"""Normalization helpers: turn messy email text into clean, typed values.

These are deliberately small and pure (no I/O), which makes them easy to unit-test:
  - parse_amount / parse_amounts : pull a money value + currency out of text
  - canonical_merchant           : "shipment-tracking@amazon.in" -> "Amazon"
  - to_category / to_txn_type     : coerce a free-form string to our enums
  - coerce_date                   : parse a date from a string/datetime
"""
from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parseaddr

from dateutil import parser as date_parser

from ..enums import Category, TxnType

# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #
_CURRENCY = {
    "₹": "INR", "rs.": "INR", "rs": "INR", "inr": "INR",
    "us$": "USD", "$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
}
_CUR_ALT = "|".join(re.escape(c) for c in sorted(_CURRENCY, key=len, reverse=True))
_NUM = r"(?:\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
# Currency symbol/code immediately before or after a number.
_BEFORE = re.compile(rf"(?P<cur>{_CUR_ALT})\s*(?P<num>{_NUM})", re.IGNORECASE)
_AFTER = re.compile(rf"(?P<num>{_NUM})\s*(?P<cur>{_CUR_ALT})", re.IGNORECASE)

# Keywords that tend to sit right before the *total* amount, most specific first.
_TOTAL_KEYWORDS = [
    "grand total", "amount paid", "total amount", "order total", "amount due",
    "net payable", "total payable", "you paid", "amount charged", "total",
    "amount", "paid", "charged",
]


def _to_float(num: str) -> float | None:
    try:
        return float(num.replace(",", ""))
    except ValueError:
        return None


def _norm_currency(token: str) -> str:
    return _CURRENCY.get(token.strip().lower(), "INR")


def parse_amounts(text: str) -> list[tuple[int, float, str]]:
    """Return every (position, amount, currency) money mention found in ``text``."""
    out: list[tuple[int, float, str]] = []
    for rx in (_BEFORE, _AFTER):
        for m in rx.finditer(text):
            amount = _to_float(m.group("num"))
            if amount is not None and amount > 0:
                out.append((m.start("num"), amount, _norm_currency(m.group("cur"))))
    return out


def parse_amount(text: str) -> tuple[float | None, str]:
    """Best-guess (amount, currency) for a receipt/invoice.

    Strategy: if a "total"-type keyword is present, take the money value closest
    after it; otherwise fall back to the largest money value in the text (on a
    receipt the total is almost always the biggest figure with a currency on it).
    """
    candidates = parse_amounts(text)
    if not candidates:
        return None, "INR"

    low = text.lower()
    for kw in _TOTAL_KEYWORDS:
        idx = low.find(kw)
        if idx == -1:
            continue
        after = [c for c in candidates if 0 <= c[0] - idx <= 60]
        if after:
            best = min(after, key=lambda c: c[0] - idx)
            return best[1], best[2]

    best = max(candidates, key=lambda c: c[1])
    return best[1], best[2]


# --------------------------------------------------------------------------- #
# Merchant
# --------------------------------------------------------------------------- #
# Substring -> canonical display name. Keeps "amazon.in", "amazon-pay", etc. all
# mapping to "Amazon". Extend freely; unknown senders fall back to the domain.
_KNOWN_MERCHANTS = {
    "amazon": "Amazon", "amzn": "Amazon", "flipkart": "Flipkart", "myntra": "Myntra",
    "ajio": "AJIO", "swiggy": "Swiggy", "zomato": "Zomato", "dominos": "Domino's",
    "uber": "Uber", "olacabs": "Ola", "ola": "Ola", "rapido": "Rapido",
    "netflix": "Netflix", "spotify": "Spotify", "hotstar": "Hotstar",
    "primevideo": "Prime Video", "youtube": "YouTube", "adobe": "Adobe",
    "apple": "Apple", "microsoft": "Microsoft", "openai": "OpenAI",
    "github": "GitHub", "notion": "Notion", "figma": "Figma", "canva": "Canva",
    "google": "Google", "jio": "Jio", "airtel": "Airtel", "vodafone": "Vodafone",
    "tataplay": "Tata Play", "bescom": "BESCOM", "phonepe": "PhonePe",
    "paytm": "Paytm", "cred": "CRED", "zerodha": "Zerodha", "groww": "Groww",
    "irctc": "IRCTC", "makemytrip": "MakeMyTrip", "goibibo": "Goibibo",
    "cleartrip": "Cleartrip", "indigo": "IndiGo", "vistara": "Vistara",
    "bookmyshow": "BookMyShow", "bigbasket": "BigBasket", "blinkit": "Blinkit",
    "zepto": "Zepto", "dunzo": "Dunzo", "hdfc": "HDFC Bank", "icici": "ICICI Bank",
    "axisbank": "Axis Bank", "sbi": "SBI", "linkedin": "LinkedIn",
    "coursera": "Coursera", "udemy": "Udemy",
}
_GENERIC_MAIL_DOMAINS = {
    "gmail", "googlemail", "yahoo", "ymail", "outlook", "hotmail", "live",
    "proton", "protonmail", "icloud", "me",
}
_NOISE_NAME_WORDS = {
    "no", "noreply", "no-reply", "donotreply", "do-not-reply", "notifications",
    "notification", "billing", "team", "support", "info", "hello", "mailer",
    "auto", "receipts", "orders", "payments", "account", "accounts", "service",
}


def _domain_label(domain: str) -> str:
    """'shipment.amazon.in' -> 'amazon' (skip subdomains and TLDs)."""
    parts = [p for p in domain.split(".") if p]
    if not parts:
        return ""
    # Drop the TLD; if there's a two-part TLD like co.in, drop that too.
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        label = parts[-3]
    elif len(parts) >= 2:
        label = parts[-2]
    else:
        label = parts[0]
    return label.lower()


def _clean_display_name(name: str) -> str:
    words = [w for w in re.split(r"[\s._-]+", name) if w]
    kept = [w for w in words if w.lower() not in _NOISE_NAME_WORDS]
    cleaned = " ".join(kept) if kept else " ".join(words)
    return cleaned.strip().title()


def canonical_merchant(sender: str, subject: str = "", body: str = "") -> tuple[str, str]:
    """Return (canonical_name, raw_hint).

    Looks at the sender's display name + domain and the subject for a known brand;
    otherwise falls back to the domain label, then the cleaned display name.
    """
    display, email_addr = parseaddr(sender)
    domain = email_addr.split("@")[-1].lower() if "@" in email_addr else ""
    label = _domain_label(domain)

    haystack = f"{display} {domain} {subject}".lower()
    for key, canonical in _KNOWN_MERCHANTS.items():
        if key in haystack:
            return canonical, display or email_addr or domain

    if label and label not in _GENERIC_MAIL_DOMAINS:
        return label.title(), display or domain
    if display:
        cleaned = _clean_display_name(display)
        if cleaned:
            return cleaned, display
    return (domain or "Unknown"), (display or email_addr or "")


# --------------------------------------------------------------------------- #
# Enum + date coercion
# --------------------------------------------------------------------------- #
def to_category(value: str | Category | None) -> Category:
    if isinstance(value, Category):
        return value
    if not value:
        return Category.OTHER
    text = str(value).strip().lower()
    for cat in Category:
        if text == cat.value.lower() or text == cat.name.lower():
            return cat
    return Category.OTHER


def to_txn_type(value: str | TxnType | None) -> TxnType:
    if isinstance(value, TxnType):
        return value
    if not value:
        return TxnType.OTHER
    text = str(value).strip().lower()
    for tt in TxnType:
        if text == tt.value.lower() or text == tt.name.lower():
            return tt
    return TxnType.OTHER


def coerce_date(value: str | datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date_parser.parse(str(value), fuzzy=True).date()
    except (ValueError, OverflowError):
        return None
