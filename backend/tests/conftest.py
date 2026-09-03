"""Shared pytest fixtures.

Pure-logic tests (normalize, rules, analytics, crypto) need nothing special.
The API tests spin up the real FastAPI app against a THROWAWAY MongoDB database
(``gmail_spend_apitest``), which is dropped before and after each test. If MongoDB
isn't reachable, those tests are skipped rather than failed, so the pure-logic
suite still runs anywhere.

The Gmail/OAuth layer is mocked in the API tests — we never make real Google calls.
"""
from __future__ import annotations

import pytest

TEST_DB = "gmail_spend_apitest"


@pytest.fixture(scope="session")
def mongo_available() -> bool:
    from pymongo import MongoClient

    from app.config import settings

    try:
        c = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=1500)
        c.admin.command("ping")
        c.close()
        return True
    except Exception:
        return False


@pytest.fixture
def raw_mongo(mongo_available):
    """A plain pymongo client pointed at the test DB (for direct seeding/asserts)."""
    if not mongo_available:
        pytest.skip("MongoDB not reachable at configured URI")
    from pymongo import MongoClient

    from app.config import settings

    client = MongoClient(settings.mongodb_uri)
    client.drop_database(TEST_DB)
    yield client[TEST_DB]
    client.drop_database(TEST_DB)
    client.close()


@pytest.fixture
def client(monkeypatch, raw_mongo):
    """FastAPI TestClient bound to the throwaway DB (runs real startup/shutdown)."""
    from fastapi.testclient import TestClient

    import app.mongodb as mongodb
    from app import main
    from app.config import settings

    # Point the app at the test DB and make sure we start from a clean singleton.
    monkeypatch.setattr(settings, "mongodb_db", TEST_DB)
    # API tests must not inherit the developer's real OAuth credentials from
    # backend/.env or make Gemini requests. They cover the disconnected flow
    # and mock Gmail explicitly where a connected account is required.
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "mock_llm", True)
    mongodb._client = None
    mongodb._db = None

    with TestClient(main.app) as c:
        yield c
