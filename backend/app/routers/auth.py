"""Auth routes: connect / disconnect a Gmail account via Google OAuth.

Flow:
  GET  /auth/status          -> is OAuth configured? is an account connected?
  GET  /auth/google/login    -> redirect the browser to Google's consent screen
  GET  /auth/google/callback -> Google returns here; we store credentials, then
                                bounce back to the Streamlit frontend
  POST /auth/logout          -> forget the stored token
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from starlette.concurrency import run_in_threadpool

from ..auth import oauth
from ..config import settings
from ..deps import get_database
from ..schemas import AuthStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# The OAuth ``state`` value is stashed in a short-lived, http-only cookie so the
# callback can confirm the response came from the request we started (CSRF guard).
_STATE_COOKIE = "oauth_state"
_PKCE_COOKIE = "oauth_code_verifier"


@router.get("/status", response_model=AuthStatus)
async def status(db: AsyncIOMotorDatabase = Depends(get_database)) -> AuthStatus:
    email = await oauth.connected_account(db)
    return AuthStatus(
        configured=oauth.is_configured(),
        connected=email is not None,
        email=email,
    )


@router.get("/google/login")
async def login() -> RedirectResponse:
    if not oauth.is_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET in backend/.env (see the README)."
            ),
        )
    url, state, code_verifier = oauth.authorization_url()
    resp = RedirectResponse(url)
    resp.set_cookie(
        _STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax"
    )
    # Google requires this verifier to redeem the code when the authorization
    # URL included a PKCE challenge. Keep it only long enough for the callback.
    if code_verifier:
        resp.set_cookie(
            _PKCE_COOKIE, code_verifier, max_age=600, httponly=True, samesite="lax"
        )
    return resp


@router.get("/google/callback")
async def callback(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_database),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    frontend = settings.frontend_origin.rstrip("/")

    if error:
        return RedirectResponse(f"{frontend}/?auth_error={error}")

    cookie_state = request.cookies.get(_STATE_COOKIE)
    if not code or not state or state != cookie_state:
        return RedirectResponse(f"{frontend}/?auth_error=invalid_state")

    code_verifier = request.cookies.get(_PKCE_COOKIE)
    if not code_verifier:
        return RedirectResponse(f"{frontend}/?auth_error=missing_pkce_verifier")

    try:
        creds = await run_in_threadpool(
            oauth.exchange_code, code, state, code_verifier
        )
        email = await run_in_threadpool(oauth.fetch_email, creds)
        await oauth.save_credentials(db, email, creds)
    except Exception:
        logger.exception("OAuth callback failed")
        return RedirectResponse(f"{frontend}/?auth_error=exchange_failed")

    resp = RedirectResponse(f"{frontend}/?connected={email}")
    resp.delete_cookie(_STATE_COOKIE)
    resp.delete_cookie(_PKCE_COOKIE)
    return resp


@router.post("/logout", status_code=204)
async def logout(db: AsyncIOMotorDatabase = Depends(get_database)) -> Response:
    await oauth.disconnect(db)
    return Response(status_code=204)
