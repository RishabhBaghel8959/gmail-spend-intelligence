"""Tests for Gemini retry decisions."""
from __future__ import annotations

from google.genai.errors import ClientError, ServerError

from app.extraction.llm import _is_retryable_error


def test_only_transient_gemini_errors_are_retried():
    assert _is_retryable_error(ClientError(404, {}, None)) is False
    assert _is_retryable_error(ClientError(429, {}, None)) is True
    assert _is_retryable_error(ServerError(500, {}, None)) is True
