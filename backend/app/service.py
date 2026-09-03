"""Sync orchestration: the one place that ties Gmail + extraction + storage together.

``run_sync`` is the heart of the app:
  1. make sure a Gmail account is connected (and its token still valid);
  2. fetch recent spend-related emails (blocking Google calls -> threadpool);
  3. run the extraction pipeline;
  4. store new transactions idempotently;
  5. record the whole thing as a SyncRun for the UI/audit trail.

Keeping this in a service (not in the router) means the HTTP layer stays thin and
this logic is easy to test on its own.
"""
from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from starlette.concurrency import run_in_threadpool

from . import repository
from .auth import oauth
from .config import settings
from .extraction import pipeline, rules
from .gmail import client as gmail_client
from .models import SyncRun, utcnow
from .schemas import SyncResult

logger = logging.getLogger(__name__)


class NotConnected(RuntimeError):
    """No Gmail account is connected yet."""


class NeedsReconsent(RuntimeError):
    """A token exists but can no longer be refreshed; the user must reconnect."""


async def run_sync(
    db: AsyncIOMotorDatabase,
    months: int | None = None,
    max_emails: int | None = None,
) -> SyncRun:
    account = await oauth.connected_account(db)
    if not account:
        raise NotConnected("No Gmail account is connected. Connect Gmail first.")

    creds = await oauth.load_credentials(db, account)
    if creds is None:
        raise NeedsReconsent("Gmail authorization has expired. Please reconnect Gmail.")

    months = months or settings.default_months
    max_emails = max_emails or settings.max_emails

    run = await repository.create_sync_run(
        db, SyncRun(account_email=account, status="running")
    )
    try:
        # Blocking Google/LLM work runs in a threadpool so the event loop is free.
        emails = await run_in_threadpool(
            gmail_client.fetch_emails, creds, months, max_emails
        )
        candidates = [e for e in emails if rules.is_candidate(e)]
        txns = await run_in_threadpool(
            pipeline.extract_transactions, candidates, account
        )
        new_count = await repository.upsert_transactions(db, txns)

        await repository.update_sync_run(
            db, run.id,
            status="success",
            emails_scanned=len(emails),
            candidates=len(candidates),
            transactions_found=len(txns),
            new_transactions=new_count,
            finished_at=utcnow(),
            message=(
                f"Scanned {len(emails)} emails, found {len(txns)} transactions "
                f"({new_count} new)."
            ),
        )
    except Exception as exc:
        logger.exception("Sync failed")
        await repository.update_sync_run(
            db, run.id, status="error", message=str(exc), finished_at=utcnow()
        )
        raise

    refreshed = await repository.latest_sync_run(db, account)
    return refreshed or run


def run_to_result(run: SyncRun) -> SyncResult:
    return SyncResult(
        status=run.status,
        message=run.message,
        account_email=run.account_email,
        emails_scanned=run.emails_scanned,
        candidates=run.candidates,
        transactions_found=run.transactions_found,
        new_transactions=run.new_transactions,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
