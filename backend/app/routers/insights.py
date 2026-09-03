"""Analytics routes: the spending profile and the derived insights/anomalies.

  GET /profile   -> totals, by-category, by-merchant, monthly trend, recurring
  GET /insights  -> human-readable insights + flagged anomalies
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import repository
from ..analytics import build_insights, build_profile
from ..auth import oauth
from ..deps import get_database
from ..schemas import InsightsResponse, SpendingProfile

router = APIRouter(tags=["analytics"])


@router.get("/profile", response_model=SpendingProfile)
async def profile(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> SpendingProfile:
    account = await oauth.connected_account(db)
    if not account:
        return SpendingProfile()  # empty profile, safe for the UI to render
    txns = await repository.all_transactions(db, account)
    return build_profile(txns, account)


@router.get("/insights", response_model=InsightsResponse)
async def insights(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InsightsResponse:
    account = await oauth.connected_account(db)
    if not account:
        return InsightsResponse()
    txns = await repository.all_transactions(db, account)
    return build_insights(txns, build_profile(txns, account))
