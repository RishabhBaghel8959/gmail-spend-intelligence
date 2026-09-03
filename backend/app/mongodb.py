"""MongoDB connection management (Motor — the async MongoDB driver).

Plain-English overview
----------------------
We open ONE connection to MongoDB when the API starts up and reuse it for every
request. Opening a brand-new connection on each request would be slow and would
eventually exhaust the database. A single shared client (which keeps its own
internal pool of connections) is the standard, efficient approach.

Nothing here hardcodes secrets — the URI and database name come from `config`,
which reads them from the environment / .env.
"""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import DESCENDING

from .config import settings

logger = logging.getLogger(__name__)

# Collection names live in one place so every module agrees on them.
TRANSACTIONS = "transactions"
OAUTH_TOKENS = "oauth_tokens"
SYNC_RUNS = "sync_runs"

# Module-level singletons. `connect()` fills them; `get_db()` hands them out.
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect() -> None:
    """Open the shared client and verify the server is reachable (fail fast).

    Called once on application startup. If MongoDB is not running/reachable this
    raises immediately, so the app fails loudly at boot instead of limping along
    and erroring on the first real query.
    """
    global _client, _db
    if _db is not None:
        return  # already connected

    client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        uuidRepresentation="standard",
    )
    # `ping` raises pymongo.errors.ServerSelectionTimeoutError if unreachable.
    await client.admin.command("ping")

    _client = client
    _db = client[settings.mongodb_db]
    await ensure_indexes(_db)
    logger.info(
        "Connected to MongoDB (db=%s) at %s", settings.mongodb_db, settings.mongodb_uri
    )


async def disconnect() -> None:
    """Close the shared client on shutdown."""
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the shared database handle (used by the repository / routers)."""
    if _db is None:
        raise RuntimeError("MongoDB is not connected. Was connect() called on startup?")
    return _db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create the indexes the app relies on. Safe to call repeatedly (idempotent).

    - transactions.gmail_message_id is UNIQUE: this is what makes re-syncing safe.
      The same email can never create two transactions, so running a sync twice
      does not double-count spending.
    - The other indexes make the common filters/sorts (by date, merchant,
      category, account) fast.
    """
    await db[TRANSACTIONS].create_index("gmail_message_id", unique=True)
    await db[TRANSACTIONS].create_index([("txn_date", DESCENDING)])
    await db[TRANSACTIONS].create_index("merchant")
    await db[TRANSACTIONS].create_index("category")
    await db[TRANSACTIONS].create_index("account_email")
    await db[OAUTH_TOKENS].create_index("email", unique=True)
    await db[SYNC_RUNS].create_index([("started_at", DESCENDING)])


def _set_db_for_testing(client: AsyncIOMotorClient, db: AsyncIOMotorDatabase) -> None:
    """Test hook: point the app at a throwaway database. Not used in production."""
    global _client, _db
    _client = client
    _db = db
