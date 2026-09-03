"""Transaction routes: list stored transactions and fetch one by id.

Every transaction includes a ``gmail_link`` back to the source email, so any number
on the dashboard can be traced to the message it came from.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import repository
from ..auth import oauth
from ..deps import get_database
from ..schemas import TransactionOut, transaction_to_out

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    db: AsyncIOMotorDatabase = Depends(get_database),
    category: str | None = None,
    source: str | None = None,
    start: date | None = Query(None, description="Only transactions on/after this date"),
    end: date | None = Query(None, description="Only transactions on/before this date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[TransactionOut]:
    account = await oauth.connected_account(db)
    if not account:
        return []  # no account connected yet -> empty list, not an error

    # Dates arrive as YYYY-MM-DD; widen to full-day UTC datetimes for the query.
    start_dt = (
        datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None
    )
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc) if end else None

    txns = await repository.list_transactions(
        db, account,
        category=category, source=source,
        start=start_dt, end=end_dt, skip=skip, limit=limit,
    )
    return [transaction_to_out(t) for t in txns]


@router.get("/{txn_id}", response_model=TransactionOut)
async def get_transaction(
    txn_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> TransactionOut:
    account = await oauth.connected_account(db)
    if not account:
        raise HTTPException(404, "Transaction not found.")
    txn = await repository.get_transaction(db, account, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found.")
    return transaction_to_out(txn)
