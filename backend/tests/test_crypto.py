"""Unit test for the at-rest encryption of the OAuth token."""
from __future__ import annotations

from app.auth import crypto


def test_encrypt_decrypt_roundtrip():
    secret = '{"token": "ya29.abc", "refresh_token": "1//xyz"}'
    ciphertext = crypto.encrypt(secret)
    assert ciphertext != secret            # actually encrypted, not stored as-is
    assert crypto.decrypt(ciphertext) == secret


def test_ciphertext_is_not_readable():
    ciphertext = crypto.encrypt("ya29.super-secret-token")
    assert "super-secret" not in ciphertext
