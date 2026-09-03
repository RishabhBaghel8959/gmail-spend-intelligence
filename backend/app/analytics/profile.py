"""Compute a spending profile from stored transactions.

Everything here is plain Python over an in-memory list (a sync stores at most a few
hundred transactions, so this is simpler and just as fast as a MongoDB aggregation
pipeline — and trivially testable). It produces the numbers the dashboard shows:
totals, spend by category and by merchant, a monthly trend, and recurring payments.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median
from typing import Callable

from ..enums import SPEND_TYPES, TxnType
from ..models import Transaction
from ..schemas import (
    CategorySlice,
    MerchantSlice,
    MonthPoint,
    RecurringItem,
    SpendingProfile,
)

_SPEND_VALUES = {t.value for t in SPEND_TYPES}


def is_spend(txn: Transaction) -> bool:
    """Money going out (purchase / subscription / bill). Refunds/transfers excluded."""
    return txn.txn_type in _SPEND_VALUES


def _primary_currency(txns: list[Transaction]) -> str:
    if not txns:
        return "INR"
    return Counter(t.currency for t in txns).most_common(1)[0][0]


def _grouped(
    txns: list[Transaction],
    key: Callable[[Transaction], str],
    total: float,
    limit: int | None = None,
) -> list[tuple[str, float, int, float]]:
    agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for t in txns:
        bucket = agg[key(t)]
        bucket[0] += t.amount
        bucket[1] += 1
    items = sorted(agg.items(), key=lambda kv: kv[1][0], reverse=True)
    if limit:
        items = items[:limit]
    return [
        (name, round(vals[0], 2), int(vals[1]),
         round(vals[0] / total * 100, 1) if total else 0.0)
        for name, vals in items
    ]


def _monthly(txns: list[Transaction]) -> list[MonthPoint]:
    agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for t in txns:
        bucket = agg[t.txn_date.strftime("%Y-%m")]
        bucket[0] += t.amount
        bucket[1] += 1
    return [
        MonthPoint(month=m, amount=round(v[0], 2), count=int(v[1]))
        for m, v in sorted(agg.items())
    ]


def detect_recurring(spend: list[Transaction], currency: str) -> list[RecurringItem]:
    """Find merchants that are charged repeatedly (subscriptions, monthly bills…).

    A merchant is 'recurring' if it appears twice or more and either the emails look
    like subscriptions, or the gaps between charges are roughly weekly/monthly, or
    it simply recurs 3+ times.
    """
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in spend:
        if t.currency == currency:
            by_merchant[t.merchant].append(t)

    out: list[RecurringItem] = []
    for merchant, txns in by_merchant.items():
        if len(txns) < 2:
            continue
        txns.sort(key=lambda t: t.txn_date)
        dates = [t.txn_date.date() for t in txns]
        intervals = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        med = median(intervals) if intervals else 0

        is_sub = any(t.txn_type == TxnType.SUBSCRIPTION.value for t in txns)
        if is_sub or 25 <= med <= 35:
            cadence = "monthly"
        elif 5 <= med <= 9:
            cadence = "weekly"
        else:
            cadence = "irregular"

        if not (is_sub or cadence in ("monthly", "weekly") or len(txns) >= 3):
            continue

        amounts = [t.amount for t in txns]
        last = dates[-1]
        next_expected = last + timedelta(days=round(med)) if med else None
        out.append(
            RecurringItem(
                merchant=merchant,
                category=txns[-1].category,
                currency=currency,
                cadence=cadence,
                average_amount=round(sum(amounts) / len(amounts), 2),
                total_amount=round(sum(amounts), 2),
                occurrences=len(txns),
                last_date=last.isoformat(),
                next_expected=next_expected.isoformat() if next_expected else None,
                transaction_ids=[t.id for t in txns if t.id],
            )
        )
    out.sort(key=lambda r: r.total_amount, reverse=True)
    return out


def build_profile(
    transactions: list[Transaction], account_email: str | None = None
) -> SpendingProfile:
    if not transactions:
        return SpendingProfile(account_email=account_email)

    spend_all = [t for t in transactions if is_spend(t)]
    currency = _primary_currency(spend_all or transactions)
    # Totals use a single currency so we never add ₹ to $.
    spend = [t for t in spend_all if t.currency == currency]
    total = round(sum(t.amount for t in spend), 2)

    dates = [t.txn_date.date() for t in transactions]
    by_category = [CategorySlice(category=c, amount=a, count=n, percent=p)
                   for c, a, n, p in _grouped(spend, lambda t: t.category, total)]
    by_merchant = [MerchantSlice(merchant=m, amount=a, count=n, percent=p)
                   for m, a, n, p in _grouped(spend, lambda t: t.merchant, total, limit=10)]
    recurring = detect_recurring(spend, currency)
    rec_estimate = round(
        sum(r.average_amount for r in recurring if r.cadence == "monthly"), 2
    )

    return SpendingProfile(
        account_email=account_email,
        currency=currency,
        total_spent=total,
        transaction_count=len(transactions),
        spend_transaction_count=len(spend),
        first_date=min(dates).isoformat(),
        last_date=max(dates).isoformat(),
        by_category=by_category,
        by_merchant=by_merchant,
        monthly=_monthly(spend),
        recurring=recurring,
        recurring_monthly_estimate=rec_estimate,
    )
