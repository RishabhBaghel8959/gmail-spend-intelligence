"""Sync routes: pull recent emails from Gmail and extract transactions.

  POST /sync         -> run a sync now (optionally override months / max_emails)
  GET  /sync/latest  -> status of the most recent sync (for the UI)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import repository, service
from ..auth import oauth
from ..auth.oauth import OAuthNotConfigured
from ..deps import get_database
from ..schemas import SyncRequest, SyncResult

router = APIRouter(tags=["sync"])


@router.post("/sync", response_model=SyncResult)
async def run_sync(
    payload: SyncRequest | None = None,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> SyncResult:
    payload = payload or SyncRequest()
    # Validate the optional overrides at the API boundary.
    if payload.months is not None and not (1 <= payload.months <= 24):
        raise HTTPException(422, "months must be between 1 and 24.")
    if payload.max_emails is not None and not (1 <= payload.max_emails <= 500):
        raise HTTPException(422, "max_emails must be between 1 and 500.")

    try:
        run = await service.run_sync(db, payload.months, payload.max_emails)
    except service.NotConnected as exc:
        raise HTTPException(409, str(exc))
    except service.NeedsReconsent as exc:
        raise HTTPException(401, str(exc))
    except OAuthNotConfigured as exc:
        raise HTTPException(400, str(exc))
    return service.run_to_result(run)


@router.get("/sync/latest", response_model=SyncResult | None)
async def latest_sync(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> SyncResult | None:
    account = await oauth.connected_account(db)
    run = await repository.latest_sync_run(db, account)
    return service.run_to_result(run) if run else None
