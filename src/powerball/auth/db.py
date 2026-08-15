"""Postgres access for user accounts and refresh tokens (e.g. a Supabase Postgres instance).

The only module that touches `app_user` / `refresh_tokens` directly — everything else in
`powerball.auth` works with `UserRow` and plain values, never SQL. Talks to Postgres over a
connection pool via `psycopg` (not the `supabase-py` SDK), consistent with this repo's "talk to
the wire protocol directly, no vendor SDK" approach already used for LLM backends in
`powerball.insights.llm`.

Configured entirely via `POWERBALL_DATABASE_URL` (a standard Postgres connection string — Supabase
publishes one per project). Reading it, and connecting, happens lazily on first use rather than at
import time, so importing this module never fails; every public function raises
`DatabaseUnavailableError` (mapped to an HTTP 503 by `api.py`, same treatment as
`LLMUnavailableError`) if the var is unset or the database is unreachable — fails closed rather
than silently no-op'ing.

Schema (see `db/schema.sql` for the DDL — `app_user` is assumed to already exist):

    app_user(user_id, email, password, created_on, deleted)
    refresh_tokens(token_id, user_id, token_hash, created_at, expires_at, revoked_at, replaced_by)

Only a *hash* of each refresh token is ever stored (see
`powerball.auth.service.hash_refresh_token`) — never the raw token — so a database leak doesn't
yield directly-usable sessions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

import logging

logger = logging.getLogger(__name__)

DATABASE_URL_ENV_VAR = "POWERBALL_DATABASE_URL"


class DatabaseUnavailableError(RuntimeError):
    """Raised when POWERBALL_DATABASE_URL isn't configured, or the database isn't reachable."""


class UserAlreadyExistsError(RuntimeError):
    """Raised by `create_user` when the email is already registered."""


@dataclass(frozen=True)
class UserRow:
    """A row from `app_user`. `user_id` is whatever type the column is (uuid or int)."""

    user_id: Any
    name: str
    email: str
    password_hash: str
    deleted: bool


_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Lazily create (once) and return the module-level connection pool.

    Doesn't block waiting for a connection to succeed — `open(wait=False)` returns immediately
    and lets connection failures surface from `_connection()` on first real use, same "fail
    closed at the point of use, not at import time" shape as the rest of this app's config.
    """
    global _pool
    if _pool is None:
        dsn = os.environ.get(DATABASE_URL_ENV_VAR)
        if not dsn:
            raise DatabaseUnavailableError(
                f"{DATABASE_URL_ENV_VAR} is not configured on the server"
            )
        pool = ConnectionPool(dsn, min_size=1, max_size=5, kwargs={"autocommit": True}, open=False)
        pool.open(wait=False)
        _pool = pool
        logger.info("created Postgres connection pool to %s", dsn)
    return _pool


@contextmanager
def _connection() -> Iterator[psycopg.Connection]:
    try:
        with get_pool().connection() as conn:
            yield conn
    except psycopg.OperationalError as e:
        raise DatabaseUnavailableError(f"couldn't reach the database: {e}") from e


def _to_user_row(row: tuple) -> UserRow:
    user_id, name, email, password_hash, deleted = row
    return UserRow(user_id=user_id, name=name, email=email, password_hash=password_hash, deleted=deleted)


def get_user_by_email(email: str) -> UserRow | None:
    with _connection() as conn:
        row = conn.execute(
            "select user_id, name, email, password, deleted from app_user where email = %s",
            (email,),
        ).fetchone()
    return _to_user_row(row) if row is not None else None


def create_user(name: str, email: str, password_hash: str) -> UserRow:
    with _connection() as conn:
        try:
            row = conn.execute(
                "insert into app_user (name, email, password) values (%s, %s, %s) "
                "returning user_id, name, email, password, deleted",
                (name, email, password_hash),
            ).fetchone()
        except psycopg.errors.UniqueViolation as e:
            raise UserAlreadyExistsError(f"an account with email {email!r} already exists") from e
    return _to_user_row(row)


def store_refresh_token(user_id: Any, token_hash: str, expires_at: datetime) -> None:
    with _connection() as conn:
        conn.execute(
            "insert into refresh_tokens (user_id, token_hash, expires_at) values (%s, %s, %s)",
            (user_id, token_hash, expires_at),
        )


def revoke_refresh_token(token_hash: str) -> None:
    """Mark a refresh token revoked. Idempotent — a no-op if already revoked or unknown."""
    with _connection() as conn:
        conn.execute(
            "update refresh_tokens set revoked_at = now() "
            "where token_hash = %s and revoked_at is null",
            (token_hash,),
        )


def rotate_refresh_token(
    old_token_hash: str, new_token_hash: str, new_expires_at: datetime
) -> UserRow | None:
    """Atomically validate + revoke `old_token_hash` and insert `new_token_hash` in its place.

    Validates that the old token exists, isn't revoked or expired, and its owning user isn't
    deleted, all inside one transaction with a row lock on the old token — so two concurrent
    `/auth/refresh` calls with the same (stolen or replayed) token can't both succeed. Returns the
    owning `UserRow` if the old token was valid, else `None` (nothing is written in that case).
    """
    with _connection() as conn, conn.transaction():
        row = conn.execute(
            """
            select u.user_id, u.email, u.password, u.deleted
            from refresh_tokens rt
            join app_user u on u.user_id = rt.user_id
            where rt.token_hash = %s
              and rt.revoked_at is null
              and rt.expires_at > now()
              and u.deleted = false
            for update of rt
            """,
            (old_token_hash,),
        ).fetchone()
        if row is None:
            return None
        user = _to_user_row(row)
        new_row = conn.execute(
            "insert into refresh_tokens (user_id, token_hash, expires_at) "
            "values (%s, %s, %s) returning token_id",
            (user.user_id, new_token_hash, new_expires_at),
        ).fetchone()
        conn.execute(
            "update refresh_tokens set revoked_at = now(), replaced_by = %s where token_hash = %s",
            (new_row[0], old_token_hash),
        )
    return user
