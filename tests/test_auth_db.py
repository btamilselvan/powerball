"""Tests for the parts of auth/db.py that don't need a live Postgres.

Actual SQL execution (get_user_by_email, create_user, rotate_refresh_token, ...) needs a real
database and isn't covered here — same as insights/llm.py's real HTTP calls aren't unit-tested,
only its config/selection logic is. Exercise those against a real Postgres per the README.
"""

import pytest

from powerball.auth import db
from powerball.auth.db import DATABASE_URL_ENV_VAR, DatabaseUnavailableError


@pytest.fixture(autouse=True)
def _reset_pool_singleton(monkeypatch):
    # get_pool() caches a module-level singleton; make sure no test's (possibly bogus) pool
    # leaks into another test.
    monkeypatch.setattr(db, "_pool", None)


def test_get_pool_raises_when_database_url_unset(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)
    with pytest.raises(DatabaseUnavailableError, match=DATABASE_URL_ENV_VAR):
        db.get_pool()


def test_get_user_by_email_raises_when_database_url_unset(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)
    with pytest.raises(DatabaseUnavailableError, match=DATABASE_URL_ENV_VAR):
        db.get_user_by_email("a@example.com")


def test_create_user_raises_when_database_url_unset(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)
    with pytest.raises(DatabaseUnavailableError, match=DATABASE_URL_ENV_VAR):
        db.create_user("a@example.com", "hashed")
