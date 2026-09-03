"""Auth package: Google OAuth flow + encryption of the stored token."""
from __future__ import annotations

from . import crypto, oauth
from .oauth import (
    OAuthNotConfigured,
    authorization_url,
    connected_account,
    disconnect,
    exchange_code,
    fetch_email,
    is_configured,
    load_credentials,
    save_credentials,
)

__all__ = [
    "crypto",
    "oauth",
    "OAuthNotConfigured",
    "authorization_url",
    "connected_account",
    "disconnect",
    "exchange_code",
    "fetch_email",
    "is_configured",
    "load_credentials",
    "save_credentials",
]
