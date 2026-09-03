"""Unit tests for the analytics layer: profile, recurring detection, insights.

These use in-memory Transaction objects (no DB) and assert the numbers and the
anomaly types that the task brief calls for (top category, spend spike, new large
merchant), plus that refunds are excluded from spend.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.analytics import build_insights, build_profile
from app.models import Transaction

_counter = 0


def _txn(merchant, amount, month, day, category="Shopping",
         txn_type="purchase", currency="INR") -> Transaction:
    global _counter
    _counter += 1
    return Transaction(
        id=f"{_counter:024d}",  # 24 hex chars so it looks like an ObjectId
        account_email="user@example.com",
        gmail_message_id=f"m{_counter}",
        merchant=merchant,
        amount=amount,
        currency=currency,
        txn_date=datetime(2026, month, day, tzinfo=timezone.utc),
        category=category,
        txn_type=txn_type,
    )


def _dataset() -> list[Transaction]:
    return [
        # Netflix: 3 monthly subscription charges.
        _txn("Netflix", 199, 1, 5, "Subscriptions & SaaS", "subscription"),
        _txn("Netflix", 199, 2, 4, "Subscriptions & SaaS", "subscription"),
        _txn("Netflix", 199, 3, 6, "Subscriptions & SaaS", "subscription"),
        # Adobe: 2 normal charges then a spike.
        _txn("Adobe", 1699, 1, 10, "Subscriptions & SaaS", "subscription"),
        _txn("Adobe", 1699, 2, 10, "Subscriptions & SaaS", "subscription"),
        _txn("Adobe", 6899, 3, 10, "Subscriptions & SaaS", "subscription"),
        # A one-off shopping purchase.
        _txn("Amazon", 1200, 1, 15, "Shopping", "purchase"),
        # A large single travel booking -> "new merchant" anomaly + top category.
        _txn("MakeMyTrip", 42000, 2, 20, "Travel", "purchase"),
        # A refund: tracked but must NOT count as spend.
        _txn("Amazon", 500, 3, 1, "Shopping", "refund"),
    ]


def test_profile_totals_exclude_refund():
    profile = build_profile(_dataset(), "user@example.com")
    # 597 (Netflix) + 10297 (Adobe) + 1200 (Amazon) + 42000 (MMT) = 54094
    assert profile.total_spent == 54094.0
    assert profile.spend_transaction_count == 8  # refund excluded
    assert profile.transaction_count == 9


def test_top_category_is_travel():
    profile = build_profile(_dataset(), "user@example.com")
    assert profile.by_category[0].category == "Travel"
    assert profile.by_category[0].amount == 42000.0


def test_recurring_detects_monthly_subscriptions():
    profile = build_profile(_dataset(), "user@example.com")
    merchants = {r.merchant: r for r in profile.recurring}
    assert "Netflix" in merchants
    assert merchants["Netflix"].cadence == "monthly"
    assert merchants["Netflix"].occurrences == 3
    assert merchants["Netflix"].next_expected is not None
    assert "Adobe" in merchants


def test_insights_flag_spike_and_new_merchant():
    txns = _dataset()
    profile = build_profile(txns, "user@example.com")
    result = build_insights(txns, profile)

    types = {i.type for i in result.insights}
    assert "top_category" in types
    assert "spike" in types          # Adobe 6899 vs avg 1699
    assert "new_merchant" in types   # MakeMyTrip 42000, first seen

    # The top-category insight should read like the brief's example.
    top = next(i for i in result.insights if i.type == "top_category")
    assert "Travel" in top.text and "42,000" in top.text

    # Anomalies are the warning-level insights and carry source transaction ids.
    assert len(result.anomalies) >= 2
    spike = next(i for i in result.insights if i.type == "spike")
    assert spike.merchant == "Adobe"
    assert spike.transaction_ids  # links back to the source email


def test_empty_dataset_is_safe():
    profile = build_profile([], "user@example.com")
    assert profile.total_spent == 0.0
    assert profile.by_category == []
    result = build_insights([], profile)
    assert result.insights == [] and result.anomalies == []
