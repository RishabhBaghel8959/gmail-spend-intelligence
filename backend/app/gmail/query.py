"""Builds the Gmail search query used to find spend-related emails.

We restrict to a time window (``after:YYYY/MM/DD``) and to a set of finance-y terms
so we pull far fewer, far more relevant messages instead of the whole mailbox.
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

# Broad but finance-focused. Gmail treats these as OR'd search terms.
_TERMS = [
    "invoice", "receipt", "order confirmation", "payment", "subscription",
    "bill", "transaction", "paid", "renewal", "purchase", "order placed",
    "payment successful", "debited", "your order",
]


def build_query(months: int) -> str:
    after = (date.today() - relativedelta(months=months)).strftime("%Y/%m/%d")
    terms = " OR ".join(f'"{t}"' if " " in t else t for t in _TERMS)
    # -in:chats keeps Google Chat messages out of the results.
    return f"({terms}) after:{after} -in:chats"
