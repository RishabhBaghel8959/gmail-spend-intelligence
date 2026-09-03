"""Shared enums: the spending-category taxonomy and transaction types.

Kept in one place so the extraction schema (what we ask Gemini to emit), the
normalizer, and the analytics layer all agree on the exact same vocabulary.
"""
from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    TRAVEL = "Travel"
    FOOD_DINING = "Food & Dining"
    GROCERIES = "Groceries"
    SHOPPING = "Shopping"
    SUBSCRIPTIONS = "Subscriptions & SaaS"
    UTILITIES = "Utilities & Bills"
    TRANSPORT = "Transport"
    ENTERTAINMENT = "Entertainment"
    HEALTH = "Health"
    FINANCIAL = "Financial & Fees"
    EDUCATION = "Education"
    OTHER = "Other"


class TxnType(str, Enum):
    PURCHASE = "purchase"
    SUBSCRIPTION = "subscription"
    BILL = "bill"
    REFUND = "refund"
    TRANSFER = "transfer"
    OTHER = "other"


# Money that flows OUT of the account, i.e. counts toward "spending".
# Refunds and transfers are tracked but excluded from spend totals.
SPEND_TYPES = {TxnType.PURCHASE, TxnType.SUBSCRIPTION, TxnType.BILL}
