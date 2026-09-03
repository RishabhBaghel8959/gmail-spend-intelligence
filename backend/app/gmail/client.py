"""Read-only Gmail client: search for spend emails and fetch their contents.

These calls use Google's official client library, which is synchronous (blocking).
The service layer runs them in a threadpool so they don't block the async server.

We only ever READ mail (the OAuth scope is gmail.readonly) and we keep just what we
need (headers, snippet, and the text body for extraction).
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .query import build_query
from ..config import settings
from ..extraction.schema import RawEmail

logger = logging.getLogger(__name__)


def build_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_message_ids(service, query: str, max_results: int) -> list[str]:
    """Return up to ``max_results`` matching message ids, paging as needed."""
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_results:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(100, max_results - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_results]


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "replace")


def _collect_parts(payload: dict, plain: list[str], html: list[str]) -> None:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data:
        if mime == "text/plain":
            plain.append(_decode(data))
        elif mime == "text/html":
            html.append(_decode(data))
    for part in payload.get("parts", []) or []:
        _collect_parts(part, plain, html)


def extract_body(payload: dict) -> str:
    """Prefer the plain-text body; otherwise strip tags from the HTML body."""
    plain: list[str] = []
    html: list[str] = []
    _collect_parts(payload, plain, html)
    if plain:
        return "\n".join(plain).strip()
    if html:
        text = " ".join(
            BeautifulSoup(h, "lxml").get_text(" ", strip=True) for h in html
        )
        return text.strip()
    return ""


def _header(headers: dict, name: str) -> str:
    return headers.get(name.lower(), "")


def fetch_message(service, message_id: str) -> RawEmail:
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = message.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    email_date: datetime | None = None
    internal = message.get("internalDate")
    if internal:
        email_date = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)

    return RawEmail(
        gmail_message_id=message["id"],
        thread_id=message.get("threadId"),
        rfc822_msgid=_header(headers, "message-id") or None,
        subject=_header(headers, "subject"),
        sender=_header(headers, "from"),
        date=email_date,
        snippet=message.get("snippet", ""),
        body=extract_body(payload),
        source="gmail",
    )


def fetch_emails(creds: Credentials, months: int, max_emails: int) -> list[RawEmail]:
    """Search + fetch the recent spend-related emails for the connected account."""
    service = build_service(creds)
    query = build_query(months)
    message_ids = search_message_ids(service, query, max_emails)

    emails: list[RawEmail] = []
    for mid in message_ids:
        try:
            emails.append(fetch_message(service, mid))
        except HttpError as exc:  # one bad message shouldn't abort the whole sync
            logger.warning("Skipping message %s: %s", mid, exc)
    return emails
