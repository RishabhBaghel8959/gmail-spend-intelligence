"""API / integration tests.

These run the real FastAPI app against a throwaway MongoDB (see conftest) and mock
only the Google/Gmail boundary. They verify the HTTP contract, input validation,
error status codes, the full sync -> store -> analyze flow, idempotent re-sync, and
that every transaction is traceable back to its source email.

Skipped automatically if MongoDB isn't reachable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.extraction.schema import RawEmail

ACCOUNT = "user@example.com"


# --------------------------------------------------------------------------- #
# Basic contract: health, empty states, validation, 404s
# --------------------------------------------------------------------------- #
def test_health_reports_mongo_connected(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mongodb"] == "connected"


def test_status_disconnected_by_default(client):
    body = client.get("/auth/status").json()
    assert body["connected"] is False
    # No Google creds configured in the test env.
    assert body["configured"] is False


def test_oauth_callback_reuses_pkce_verifier(client, monkeypatch):
    """The verifier generated before Google redirects must reach token exchange."""
    from app.auth import oauth

    expected_state = "csrf-state"
    expected_verifier = "pkce-verifier"
    received: dict[str, str | None] = {}

    monkeypatch.setattr(oauth, "is_configured", lambda: True)
    monkeypatch.setattr(
        oauth,
        "authorization_url",
        lambda: ("https://accounts.google.com/consent", expected_state, expected_verifier),
    )

    def fake_exchange(code, state, code_verifier):
        received.update(code=code, state=state, code_verifier=code_verifier)
        return object()

    async def fake_save_credentials(db, email, creds):
        return None

    monkeypatch.setattr(oauth, "exchange_code", fake_exchange)
    monkeypatch.setattr(oauth, "fetch_email", lambda creds: ACCOUNT)
    monkeypatch.setattr(oauth, "save_credentials", fake_save_credentials)

    login = client.get("/auth/google/login", follow_redirects=False)
    assert login.status_code == 307

    callback = client.get(
        f"/auth/google/callback?code=one-time-code&state={expected_state}",
        follow_redirects=False,
    )
    assert callback.status_code == 307
    assert callback.headers["location"].endswith(f"connected={ACCOUNT}")
    assert received == {
        "code": "one-time-code",
        "state": expected_state,
        "code_verifier": expected_verifier,
    }


def test_transactions_empty_when_not_connected(client):
    assert client.get("/transactions").json() == []


def test_profile_empty_when_not_connected(client):
    body = client.get("/profile").json()
    assert body["total_spent"] == 0.0
    assert body["by_category"] == []


def test_sync_requires_connection(client):
    resp = client.post("/sync", json={})
    assert resp.status_code == 409  # NotConnected -> Conflict


def test_sync_validates_input(client):
    assert client.post("/sync", json={"months": 999}).status_code == 422
    assert client.post("/sync", json={"max_emails": 0}).status_code == 422


def test_get_unknown_transaction_is_404(client, raw_mongo):
    # Seed a connected account so the route gets past the connection check.
    _seed_token(raw_mongo)
    assert client.get("/transactions/not-a-real-id").status_code == 404
    # A well-formed-but-missing ObjectId is also a clean 404.
    assert client.get("/transactions/0123456789abcdef01234567").status_code == 404


# --------------------------------------------------------------------------- #
# Connected account reads
# --------------------------------------------------------------------------- #
def test_status_connected_after_token_seeded(client, raw_mongo):
    _seed_token(raw_mongo)
    body = client.get("/auth/status").json()
    assert body["connected"] is True
    assert body["email"] == ACCOUNT


def test_transactions_expose_gmail_link(client, raw_mongo):
    _seed_token(raw_mongo)
    raw_mongo["transactions"].insert_one(_txn_doc("abc123", "Netflix", 649.0))
    rows = client.get("/transactions").json()
    assert len(rows) == 1
    assert rows[0]["merchant"] == "Netflix"
    assert rows[0]["gmail_link"].endswith("abc123")  # traceable to the email


# --------------------------------------------------------------------------- #
# Full sync flow (Gmail + OAuth mocked) + idempotency
# --------------------------------------------------------------------------- #
def test_sync_extracts_stores_and_is_idempotent(client, raw_mongo, monkeypatch):
    _mock_google(monkeypatch, _sample_emails())

    first = client.post("/sync", json={"months": 6, "max_emails": 50})
    assert first.status_code == 200
    result = first.json()
    # 3 emails in, 1 is marketing (no signal) -> 2 transactions, both new.
    assert result["emails_scanned"] == 3
    assert result["transactions_found"] == 2
    assert result["new_transactions"] == 2
    assert result["status"] == "success"

    # They are queryable, with a Gmail link each.
    rows = client.get("/transactions").json()
    assert {r["merchant"] for r in rows} == {"Netflix", "Amazon"}
    assert all(r["gmail_link"] for r in rows)

    # Profile reflects the stored spend (649 + 1299).
    profile = client.get("/profile").json()
    assert profile["total_spent"] == pytest.approx(1948.0)

    # Re-syncing the same emails must NOT double-count (unique gmail_message_id).
    second = client.post("/sync", json={"months": 6, "max_emails": 50}).json()
    assert second["new_transactions"] == 0
    assert client.get("/profile").json()["total_spent"] == pytest.approx(1948.0)
    assert len(client.get("/transactions").json()) == 2


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _seed_token(db) -> None:
    now = datetime.now(timezone.utc)
    db["oauth_tokens"].insert_one(
        {"email": ACCOUNT, "token_encrypted": "x", "created_at": now, "updated_at": now}
    )


def _txn_doc(msg_id, merchant, amount) -> dict:
    return {
        "account_email": ACCOUNT,
        "gmail_message_id": msg_id,
        "merchant": merchant,
        "amount": amount,
        "currency": "INR",
        "txn_date": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "category": "Subscriptions & SaaS",
        "txn_type": "subscription",
        "source": "gmail",
        "confidence": 0.8,
        "subject": f"{merchant} payment",
        "sender": f"{merchant} <info@{merchant.lower()}.com>",
        "snippet": "",
        "created_at": datetime.now(timezone.utc),
    }


def _sample_emails() -> list[RawEmail]:
    return [
        RawEmail(
            gmail_message_id="g1",
            subject="Your Netflix subscription payment",
            sender="Netflix <info@netflix.com>",
            body="Payment of ₹649 received. Your plan renews monthly.",
            date=datetime(2026, 1, 5, tzinfo=timezone.utc),
        ),
        RawEmail(
            gmail_message_id="g2",
            subject="Your Amazon order is confirmed",
            sender="Amazon.in <order-update@amazon.in>",
            body="Order total ₹1,299 paid successfully.",
            date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        ),
        # Marketing: has a price but no transaction signal -> filtered out.
        RawEmail(
            gmail_message_id="g3",
            subject="Mega Sale! Shirts at ₹499",
            sender="Myntra <offers@myntra.com>",
            body="Shop now and save big this weekend.",
            date=datetime(2026, 1, 20, tzinfo=timezone.utc),
        ),
    ]


def _mock_google(monkeypatch, emails: list[RawEmail]) -> None:
    """Make the app think a Gmail account is connected and return canned emails."""
    async def fake_connected_account(db):
        return ACCOUNT

    async def fake_load_credentials(db, email=None):
        return object()  # a non-None stand-in for google Credentials

    def fake_fetch_emails(creds, months, max_emails):
        return emails

    monkeypatch.setattr("app.auth.oauth.connected_account", fake_connected_account)
    monkeypatch.setattr("app.auth.oauth.load_credentials", fake_load_credentials)
    monkeypatch.setattr("app.gmail.client.fetch_emails", fake_fetch_emails)
