"""Turn the spending profile into short, human-readable insights and anomalies.

These mirror the examples in the task brief, e.g.:
  - "You spent ₹42,000 on Travel, your highest spending category."
  - "Your latest Adobe payment of ₹6,899 is higher than your previous payments."
  - "A ₹35,000 payment to a merchant we haven't seen before was detected."

Every insight carries the ``transaction_ids`` it came from, so the UI can link back
to the exact source email(s).
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

from .profile import is_spend
from ..models import Transaction
from ..schemas import Insight, InsightsResponse, SpendingProfile

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _sym(currency: str) -> str:
    return _SYMBOLS.get(currency, currency + " ")


def money(amount: float, currency: str) -> str:
    sym = _sym(currency)
    if float(amount).is_integer():
        return f"{sym}{amount:,.0f}"
    return f"{sym}{amount:,.2f}"


def build_insights(
    transactions: list[Transaction], profile: SpendingProfile
) -> InsightsResponse:
    currency = profile.currency
    spend = [t for t in transactions if is_spend(t) and t.currency == currency]
    if not spend:
        return InsightsResponse(generated_from=len(transactions))

    amounts = [t.amount for t in spend]
    med = median(amounts)
    insights: list[Insight] = []

    # 1) Highest-spend category
    if profile.by_category:
        top = profile.by_category[0]
        cat_ids = [t.id for t in spend if t.category == top.category and t.id][:20]
        insights.append(Insight(
            type="top_category", severity="info",
            title="Highest spending category",
            text=f"You spent {money(top.amount, currency)} on {top.category} — "
                 f"your highest spending category ({top.percent:.0f}% of total).",
            amount=top.amount, transaction_ids=cat_ids,
        ))

    # 2) Top merchant
    if profile.by_merchant:
        tm = profile.by_merchant[0]
        mer_ids = [t.id for t in spend if t.merchant == tm.merchant and t.id][:20]
        insights.append(Insight(
            type="top_merchant", severity="info",
            title="Top merchant",
            text=f"{tm.merchant} is your top merchant at {money(tm.amount, currency)} "
                 f"across {tm.count} payment(s).",
            amount=tm.amount, merchant=tm.merchant, transaction_ids=mer_ids,
        ))

    # 3) Recurring summary + upcoming charges
    if profile.recurring:
        insights.append(Insight(
            type="recurring", severity="info",
            title="Recurring payments",
            text=f"You have {len(profile.recurring)} recurring payment(s), roughly "
                 f"{money(profile.recurring_monthly_estimate, currency)} per month.",
            amount=profile.recurring_monthly_estimate,
        ))
        for r in profile.recurring[:3]:
            if r.next_expected and r.cadence in ("monthly", "weekly"):
                insights.append(Insight(
                    type="upcoming", severity="info",
                    title=f"Upcoming: {r.merchant}",
                    text=f"{r.merchant} usually charges about "
                         f"{money(r.average_amount, currency)} ({r.cadence}); "
                         f"next one expected around {r.next_expected}.",
                    amount=r.average_amount, merchant=r.merchant,
                    transaction_ids=r.transaction_ids[-1:],
                ))

    # 4) Spend spikes: latest charge from a merchant is well above its usual amount
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in spend:
        by_merchant[t.merchant].append(t)
    spikes: list[Insight] = []
    for merchant, txns in by_merchant.items():
        if len(txns) < 2:
            continue
        txns.sort(key=lambda t: t.txn_date)
        latest = txns[-1]
        prev_avg = mean(t.amount for t in txns[:-1])
        if prev_avg > 0 and latest.amount >= 1.6 * prev_avg and latest.amount >= med:
            spikes.append(Insight(
                type="spike", severity="warning",
                title=f"Unusually high {merchant} payment",
                text=f"Your latest {merchant} payment of "
                     f"{money(latest.amount, currency)} is significantly higher than "
                     f"your previous payments (avg {money(round(prev_avg, 2), currency)}).",
                amount=latest.amount, merchant=merchant,
                transaction_ids=[latest.id] if latest.id else [],
            ))
    spikes.sort(key=lambda i: i.amount or 0, reverse=True)
    insights.extend(spikes[:3])

    # 5) New, large payments (single occurrence, well above the typical amount)
    threshold = max(2.5 * med, med + 1)
    new_large: list[Insight] = []
    for merchant, txns in by_merchant.items():
        if len(txns) != 1:
            continue
        t = txns[0]
        if t.amount >= threshold:
            new_large.append(Insight(
                type="new_merchant", severity="warning",
                title=f"New merchant: {merchant}",
                text=f"A {money(t.amount, currency)} payment to {merchant}, a merchant "
                     f"we haven't seen before, was detected.",
                amount=t.amount, merchant=merchant,
                transaction_ids=[t.id] if t.id else [],
            ))
    new_large.sort(key=lambda i: i.amount or 0, reverse=True)
    insights.extend(new_large[:3])

    anomalies = [i for i in insights if i.severity == "warning"]
    return InsightsResponse(
        insights=insights, anomalies=anomalies, generated_from=len(transactions)
    )
