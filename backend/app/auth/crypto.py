"""Encryption at rest for sensitive values (currently: the Gmail OAuth token).

We never store the Google token in plaintext. It is encrypted with Fernet
(symmetric AES-based encryption from the ``cryptography`` library). The key comes
from the ``FERNET_KEY`` environment variable, or — for local development — from a
gitignored file at ``backend/.secrets/fernet.key`` that we generate once.

If someone reads the database, the stored token is useless to them without the key.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

from ..config import SECRETS_DIR, settings

_KEY_FILE = SECRETS_DIR / "fernet.key"


def _load_or_create_key() -> bytes:
    # 1) Prefer an explicit key from the environment (how you'd do it in production).
    if settings.fernet_key:
        return settings.fernet_key.encode()
    # 2) Otherwise reuse the local dev key if we've already generated one.
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    # 3) First run: generate one and persist it (the folder is gitignored).
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        os.chmod(_KEY_FILE, 0o600)  # best effort; no-op on some Windows setups
    except OSError:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
