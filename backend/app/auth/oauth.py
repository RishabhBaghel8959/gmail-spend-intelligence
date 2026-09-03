"""Google OAuth 2.0 flow for read-only Gmail access.

What this does, in plain terms:
  1. We send the user to Google's consent screen (``authorization_url``).
  2. Google redirects back to our callback with a one-time ``code``.
  3. We exchange that code for credentials (``exchange_code``) and store them
     encrypted in MongoDB (``save_credentials``).
  4. Later, we load and (if needed) refresh those credentials to call Gmail.

The requested scope is ``gmail.readonly`` — the app can read mail but can never
send, modify, or delete it.
"""
from __future__ import annotations

import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import repository
from ..config import settings
from . import crypto

# Allow http://localhost for the redirect during local development.
# (Google normally requires https; localhost is the documented exception, but the
# oauthlib library still needs this opt-in to not raise on an http redirect URI.)
import os  # noqa: E402

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class OAuthNotConfigured(RuntimeError):
    """Raised when the Google client id/secret are not set in the environment."""


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_flow(state: str | None = None) -> Flow:
    if not is_configured():
        raise OAuthNotConfigured(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in backend/.env (see .env.example and the README)."
        )
    flow = Flow.from_client_config(
        _client_config(), scopes=settings.gmail_scopes, state=state
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def authorization_url() -> tuple[str, str, str | None]:
    """Return the consent URL, CSRF state, and PKCE verifier for this login.

    ``Flow.authorization_url`` creates a PKCE verifier on the flow instance.
    The callback uses a new instance, so the caller must retain that verifier
    and provide it to :func:`exchange_code` when redeeming the authorization
    code.
    """
    flow = build_flow()
    url, state = flow.authorization_url(
        access_type="offline",       # so we also get a refresh token
        include_granted_scopes="true",
        prompt="consent",            # ensures a refresh token on repeat consents
    )
    return url, state, flow.code_verifier


def exchange_code(
    code: str, state: str | None = None, code_verifier: str | None = None
) -> Credentials:
    flow = build_flow(state=state)
    # PKCE binds the authorization code to the browser session that started the
    # login. ``Flow`` is reconstructed for the callback, so restore the value
    # that was generated before redirecting to Google.
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return flow.credentials


def fetch_email(creds: Credentials) -> str:
    """Look up which Google account these credentials belong to."""
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info = service.userinfo().get().execute()
    return info["email"]


# --------------------------------------------------------------------------- #
# Persistence (encrypted) + refresh
# --------------------------------------------------------------------------- #
async def save_credentials(
    db: AsyncIOMotorDatabase, email: str, creds: Credentials
) -> None:
    await repository.save_token(db, email, crypto.encrypt(creds.to_json()))


async def load_credentials(
    db: AsyncIOMotorDatabase, email: str | None = None
) -> Credentials | None:
    """Load stored credentials, refreshing the access token if it has expired.

    Returns None if there is no stored token, or if the token cannot be refreshed
    (in which case the user must reconnect their Gmail account).
    """
    token = await repository.get_token(db, email)
    if token is None:
        return None

    info = json.loads(crypto.decrypt(token.token_encrypted))
    creds = Credentials.from_authorized_user_info(info, scopes=settings.gmail_scopes)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            await save_credentials(db, token.email, creds)
        else:
            return None
    return creds


async def connected_account(db: AsyncIOMotorDatabase) -> str | None:
    """Email of the currently connected account, or None. Single-user local tool."""
    token = await repository.get_token(db)
    return token.email if token else None


async def disconnect(db: AsyncIOMotorDatabase, email: str | None = None) -> int:
    return await repository.delete_token(db, email)
