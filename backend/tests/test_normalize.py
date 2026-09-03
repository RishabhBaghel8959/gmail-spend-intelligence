"""Unit tests for the pure normalization helpers (no I/O, fully deterministic)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.extraction import normalize


@pytest.mark.parametrize(
    "text, amount, currency",
    [
        ("Total amount ₹1,299.00 paid", 1299.00, "INR"),
        ("You paid $49.99 for your subscription", 49.99, "USD"),
        ("Grand total Rs. 2,500", 2500.0, "INR"),
        ("Your bill is €19 this month", 19.0, "EUR"),
        ("Invoice for £120.50 attached", 120.50, "GBP"),
        # Indian digit grouping (lakh) must be parsed correctly.
        ("Amount charged ₹1,00,000", 100000.0, "INR"),
    ],
)
def test_parse_amount(text, amount, currency):
    assert normalize.parse_amount(text) == (amount, currency)


def test_parse_amount_none_when_absent():
    assert normalize.parse_amount("Hello there, no money here") == (None, "INR")


def test_parse_amount_prefers_total_keyword():
    # A shipping line quotes ₹50, but the *total* is ₹1,250 — we want the total.
    text = "Shipping ₹50. Grand total ₹1,250 paid."
    assert normalize.parse_amount(text) == (1250.0, "INR")


@pytest.mark.parametrize(
    "sender, subject, expected",
    [
        ("Amazon.in <order-update@amazon.in>", "Your order shipped", "Amazon"),
        ("Netflix <info@netflix.com>", "Payment received", "Netflix"),
        # Unknown brand -> fall back to the domain label.
        ("Billing <billing@acmecorp.com>", "Invoice", "Acmecorp"),
        # Generic mail domain -> fall back to a cleaned display name (noise removed).
        ("Blue Bottle <hello@gmail.com>", "receipt", "Blue Bottle"),
    ],
)
def test_canonical_merchant(sender, subject, expected):
    name, _raw = normalize.canonical_merchant(sender, subject, "")
    assert name == expected


def test_coerce_date():
    assert normalize.coerce_date(datetime(2026, 1, 15, 9, 30)) == date(2026, 1, 15)
    assert normalize.coerce_date("2026-01-15") == date(2026, 1, 15)
    assert normalize.coerce_date(None) is None
