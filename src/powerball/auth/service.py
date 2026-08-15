"""Password hashing, JWT access tokens, and refresh-token generation.

No SQL and no FastAPI imports — pure functions over strings, kept separate from
`powerball.auth.db` so both halves are independently testable (mirrors `powerball.insights.llm`
being decoupled from `powerball.insights.insights`).

- Passwords are hashed with bcrypt (`hash_password`/`verify_password`) — never stored or compared
  as plaintext.
- Access tokens are short-lived HS256 JWTs (`create_access_token`/`decode_access_token`), signed
  with `POWERBALL_JWT_SECRET`.
- Refresh tokens are opaque random strings (`generate_refresh_token`), not JWTs — they're looked
  up server-side (see `powerball.auth.db`) so an individual one can be revoked, which a
  self-contained JWT can't be without a separate blacklist anyway. Only a sha256 hash of the raw
  token is ever persisted (`hash_refresh_token`) — sha256 rather than bcrypt because the input is
  already high-entropy random, not a low-entropy human password.

Env vars: `POWERBALL_JWT_SECRET` (required — no default, fails closed via `AuthConfigError`),
`POWERBALL_ACCESS_TOKEN_TTL_MINUTES` (default 15), `POWERBALL_REFRESH_TOKEN_TTL_DAYS` (default 30).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

JWT_SECRET_ENV_VAR = "POWERBALL_JWT_SECRET"
ACCESS_TOKEN_TTL_ENV_VAR = "POWERBALL_ACCESS_TOKEN_TTL_MINUTES"
REFRESH_TOKEN_TTL_ENV_VAR = "POWERBALL_REFRESH_TOKEN_TTL_DAYS"
DEFAULT_ACCESS_TOKEN_TTL_MINUTES = 15
DEFAULT_REFRESH_TOKEN_TTL_DAYS = 30

JWT_ALGORITHM = "HS256"


class AuthConfigError(RuntimeError):
    """Raised when required auth configuration (POWERBALL_JWT_SECRET) is missing."""


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: str
    email: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _jwt_secret() -> str:
    secret = os.environ.get(JWT_SECRET_ENV_VAR)
    if not secret:
        raise AuthConfigError(f"{JWT_SECRET_ENV_VAR} is not configured on the server")
    return secret


def access_token_ttl() -> timedelta:
    minutes = int(os.environ.get(ACCESS_TOKEN_TTL_ENV_VAR, DEFAULT_ACCESS_TOKEN_TTL_MINUTES))
    return timedelta(minutes=minutes)


def refresh_token_ttl() -> timedelta:
    days = int(os.environ.get(REFRESH_TOKEN_TTL_ENV_VAR, DEFAULT_REFRESH_TOKEN_TTL_DAYS))
    return timedelta(days=days)


def create_access_token(*, user_id: Any, email: str) -> tuple[str, datetime]:
    """Return `(jwt, expires_at)` for a new short-lived access token."""
    now = datetime.now(timezone.utc)
    expires_at = now + access_token_ttl()
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> AccessTokenClaims:
    """Validate and decode an access token JWT.

    Raises `AuthConfigError` if `POWERBALL_JWT_SECRET` isn't configured, or a
    `jwt.InvalidTokenError` (expired, bad signature, malformed, ...) from `pyjwt` itself for a bad
    token. Not wired to an endpoint yet — none of `/auth/refresh` or `/auth/logout` need to
    authenticate *via* the access token (they operate on the refresh token instead) — but this is
    the intended hook for protecting future endpoints.
    """
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    return AccessTokenClaims(
        user_id=payload["sub"],
        email=payload["email"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )


def generate_refresh_token() -> str:
    """A new opaque, high-entropy refresh token (not a JWT — looked up server-side)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """sha256 hex digest — the only form of a refresh token ever persisted to the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
