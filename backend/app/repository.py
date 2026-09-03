"""Data-access layer: all MongoDB reads/writes live here.

Keeping every query in one module (instead of scattering them across routers) makes
the app easy to reason about and to test, and means the rest of the code never has
to know MongoDB details like ObjectId or ``_id``.

All functions are ``async`` because Motor (and therefore FastAPI here) is async: an
``await``-ed query lets the server handle other requests while MongoDB is working.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import OAuthToken, SyncRun, Transaction, utcnow
from .mongodb import OAUTH_TOKENS, SYNC_RUNS, TRANSACTIONS


def _to_object_id(value: str) -> ObjectId | None:
    """Parse a string id into an ObjectId, returning None if it isn't valid.

    Guards the ``GET /transactions/{id}`` route against malformed ids so a bad path
    parameter becomes a clean 404 instead of a 500.
    """
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
async def upsert_transactions(
    db: AsyncIOMotorDatabase, txns: list[Transaction]
) -> int:
    """Insert transactions, skipping any whose source email we already stored.

    Idempotency is enforced by the UNIQUE index on ``gmail_message_id``: we upsert
    with ``$setOnInsert`` so an existing transaction is never overwritten and never
    duplicated. Returns how many were newly inserted.
    """
    new_count = 0
    for txn in txns:
        doc = txn.to_doc()
        doc.pop("_id", None)  # let Mongo assign the id on insert
        result = await db[TRANSACTIONS].update_one(
            {"gmail_message_id": txn.gmail_message_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id is not None:
            new_count += 1
    return new_count


async def list_transactions(
    db: AsyncIOMotorDatabase,
    account_email: str,
    *,
    category: str | None = None,
    source: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    skip: int = 0,
    limit: int = 200,
) -> list[Transaction]:
    query: dict[str, Any] = {"account_email": account_email}
    if category:
        query["category"] = category
    if source:
        query["source"] = source
    if start or end:
        date_query: dict[str, Any] = {}
        if start:
            date_query["$gte"] = start
        if end:
            date_query["$lte"] = end
        query["txn_date"] = date_query

    cursor = (
        db[TRANSACTIONS]
        .find(query)
        .sort("txn_date", -1)
        .skip(max(skip, 0))
        .limit(max(min(limit, 1000), 1))
    )
    return [Transaction.from_doc(doc) async for doc in cursor]


async def all_transactions(
    db: AsyncIOMotorDatabase, account_email: str
) -> list[Transaction]:
    """Every transaction for an account (used by the analytics layer).

    Fine to load in full here: a sync stores at most a few hundred transactions,
    so computing the profile in Python is simpler and clearer than a big
    aggregation pipeline, with no meaningful performance cost.
    """
    cursor = db[TRANSACTIONS].find({"account_email": account_email}).sort("txn_date", 1)
    return [Transaction.from_doc(doc) async for doc in cursor]


async def get_transaction(
    db: AsyncIOMotorDatabase, account_email: str, txn_id: str
) -> Transaction | None:
    oid = _to_object_id(txn_id)
    if oid is None:
        return None
    doc = await db[TRANSACTIONS].find_one({"_id": oid, "account_email": account_email})
    return Transaction.from_doc(doc)


# --------------------------------------------------------------------------- #
# OAuth tokens
# --------------------------------------------------------------------------- #
async def save_token(
    db: AsyncIOMotorDatabase, email: str, token_encrypted: str
) -> None:
    now = utcnow()
    await db[OAUTH_TOKENS].update_one(
        {"email": email},
        {
            "$set": {"token_encrypted": token_encrypted, "updated_at": now},
            "$setOnInsert": {"email": email, "created_at": now},
        },
        upsert=True,
    )


async def get_token(
    db: AsyncIOMotorDatabase, email: str | None = None
) -> OAuthToken | None:
    query = {"email": email} if email else {}
    doc = await db[OAUTH_TOKENS].find_one(query)
    return OAuthToken.from_doc(doc)


async def list_accounts(db: AsyncIOMotorDatabase) -> list[str]:
    return await db[OAUTH_TOKENS].distinct("email")


async def delete_token(db: AsyncIOMotorDatabase, email: str | None = None) -> int:
    query = {"email": email} if email else {}
    result = await db[OAUTH_TOKENS].delete_many(query)
    return result.deleted_count


# --------------------------------------------------------------------------- #
# Sync runs
# --------------------------------------------------------------------------- #
async def create_sync_run(db: AsyncIOMotorDatabase, run: SyncRun) -> SyncRun:
    doc = run.to_doc()
    doc.pop("_id", None)
    result = await db[SYNC_RUNS].insert_one(doc)
    run.id = str(result.inserted_id)
    return run


async def update_sync_run(
    db: AsyncIOMotorDatabase, run_id: str, **fields: Any
) -> None:
    oid = _to_object_id(run_id)
    if oid is None:
        return
    await db[SYNC_RUNS].update_one({"_id": oid}, {"$set": fields})


async def latest_sync_run(
    db: AsyncIOMotorDatabase, account_email: str | None = None
) -> SyncRun | None:
    query = {"account_email": account_email} if account_email else {}
    doc = await db[SYNC_RUNS].find_one(query, sort=[("started_at", -1)])
    return SyncRun.from_doc(doc)
