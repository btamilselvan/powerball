"""Shared-secret API key authentication for the HTTP API.

The expected key is read once per request from the `POWERBALL_API_KEY`
environment variable (not baked into app state), so rotating it is just a
matter of restarting the process with a new value. Requests authenticate by
sending it back in the `X-API-Key` header.

Fails closed: if the environment variable isn't set, every protected request
is rejected (503) rather than silently letting all traffic through.

A `.env` file in the working directory (if present) is loaded at import time
via `python-dotenv`, so `POWERBALL_API_KEY=...` in `.env` works the same as
exporting it in the shell. Real environment variables always win over `.env`
— `load_dotenv()` never overrides a var that's already set.
"""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

load_dotenv()

API_KEY_ENV_VAR = "POWERBALL_API_KEY"

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency: raise 401/503, or return None if `provided` is valid."""
    expected = os.environ.get(API_KEY_ENV_VAR)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{API_KEY_ENV_VAR} is not configured on the server",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
