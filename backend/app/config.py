"""Application configuration, loaded from environment / .env.

Everything sensitive (API keys, OAuth client secret, encryption key) is read from
the environment so nothing secret ever lands in source control. See .env.example.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (this file is backend/app/config.py)
BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_DIR = BASE_DIR / ".secrets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Gmail Spend Intelligence"

    # --- Storage (MongoDB, local by default) ---
    # `mongodb_uri` is the connection string; the app opens ONE client at startup
    # and reuses it for every request (see mongodb.py). `mongodb_db` is the
    # database (a namespace) inside that server we read/write.
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "gmail_spend"

    # --- LLM (Google Gemini) — optional ---
    gemini_api_key: str | None = None
    # Cheap/fast Flash-Lite tier is plenty for structured extraction.
    gemini_model: str = "gemini-3.5-flash-lite"
    # When true (or when no key is present) the pipeline uses a deterministic
    # rule-based extractor instead of calling Gemini. This is about LLM cost only;
    # Gmail is always connected for real via OAuth regardless of this flag.
    mock_llm: bool = False

    # --- Google OAuth (Gmail read-only) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Read-only: the app can list and read mail, never modify or send it.
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
    ]

    # --- Encryption at rest for the stored OAuth token ---
    # If unset, a key is generated once and persisted to .secrets/fernet.key
    # (gitignored). In production this would come from a secrets manager.
    fernet_key: str | None = None

    # --- Sync limits (keep us inside Gemini free-tier RPM and Gmail quotas) ---
    max_emails: int = 150
    default_months: int = 6
    body_char_limit: int = 4000

    # --- CORS / URLs: allow the local Streamlit dashboard to call the API ---
    frontend_origin: str = "http://localhost:8501"
    backend_url: str = "http://localhost:8000"

    @property
    def use_llm(self) -> bool:
        """Use real Gemini only when we have a key and mock mode is off."""
        return bool(self.gemini_api_key) and not self.mock_llm


@lru_cache
def get_settings() -> Settings:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


settings = get_settings()
