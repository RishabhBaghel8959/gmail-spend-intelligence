"""Unit tests for the rule-based extractor: candidate filter, classification, extract."""
from __future__ import annotations

from datetime import datetime

from app.enums import Category, TxnType
from app.extraction import rules
from app.extraction.schema import RawEmail


def _email(subject="", sender="", body="", snippet="", date=None) -> RawEmail:
    return RawEmail(
        gmail_message_id="m1", subject=subject, sender=sender,
        body=body, snippet=snippet, date=date or datetime(2026, 1, 10),
    )


def test_is_candidate_true_for_real_payment():
    email = _email(
        subject="Your Netflix payment",
        body="Payment of ₹649 received. Your subscription renews monthly.",
        sender="Netflix <info@netflix.com>",
    )
    assert rules.is_candidate(email) is True


def test_is_candidate_false_for_marketing_without_signal():
    # Has a price but no transaction signal word -> not a candidate.
    email = _email(
        subject="Mega Sale! Shirts at ₹499",
        body="Shop now and save big.",
        sender="Myntra <offers@myntra.com>",
    )
    assert rules.is_candidate(email) is False


def test_is_candidate_false_without_amount():
    email = _email(
        subject="Your order is confirmed",
        body="Thanks for shopping with us.",
        sender="Amazon <order@amazon.in>",
    )
    assert rules.is_candidate(email) is False


def test_detect_category():
    assert rules.detect_category("uber ride receipt") == Category.TRANSPORT
    assert rules.detect_category("netflix subscription renewed") == Category.SUBSCRIPTIONS
    assert rules.detect_category("swiggy food order delivered") == Category.FOOD_DINING


def test_detect_txn_type():
    assert rules.detect_txn_type("your refund has been processed") == TxnType.REFUND
    assert rules.detect_txn_type("your subscription renews soon") == TxnType.SUBSCRIPTION
    assert rules.detect_txn_type("electricity bill amount due") == TxnType.BILL
    assert rules.detect_txn_type("you paid for your order") == TxnType.PURCHASE


def test_extract_full_transaction():
    email = _email(
        subject="Your Netflix subscription payment",
        body="Payment of ₹649 received. Your plan renews monthly.",
        sender="Netflix <info@netflix.com>",
    )
    ex = rules.extract(email)
    assert ex.is_transaction is True
    assert ex.merchant == "Netflix"
    assert ex.amount == 649.0
    assert ex.currency == "INR"
    assert ex.category == Category.SUBSCRIPTIONS
    assert ex.txn_type == TxnType.SUBSCRIPTION
    assert ex.confidence > 0.5
