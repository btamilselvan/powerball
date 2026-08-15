import pytest
from fastapi.testclient import TestClient

from powerball.api import app
from powerball.auth.db import DatabaseUnavailableError, UserAlreadyExistsError, UserRow
from powerball.auth.service import JWT_SECRET_ENV_VAR, hash_password
from powerball.draws.rules import POWERBALL_MAX, POWERBALL_MIN, WHITE_MAX, WHITE_MIN
from powerball.insights.insights import CommentaryPickResult, Insights, PatternNote
from powerball.insights.llm import LLMUnavailableError
from powerball.security import API_KEY_ENV_VAR


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_requires_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_pick_quick_without_key_configured_is_unavailable(client, monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    resp = client.get("/pick/quick")
    assert resp.status_code == 503


def test_pick_quick_with_wrong_key_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.get("/pick/quick", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_pick_quick_with_missing_header_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.get("/pick/quick")
    assert resp.status_code == 401


def test_pick_quick_with_correct_key_returns_picks(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.get("/pick/quick", params={"count": 3}, headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 200
    picks = resp.json()
    assert len(picks) == 3
    for pick in picks:
        assert len(set(pick["whites"])) == 5
        assert all(WHITE_MIN <= n <= WHITE_MAX for n in pick["whites"])
        assert POWERBALL_MIN <= pick["powerball"] <= POWERBALL_MAX


def test_pick_smart_with_correct_key_returns_picks(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.get("/pick/smart", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 200
    picks = resp.json()
    assert len(picks) == 1
    assert len(set(picks[0]["whites"])) == 5


def test_pick_count_out_of_range_is_rejected(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.get("/pick/quick", params={"count": 0}, headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 422


def test_insights_without_key_configured_is_unavailable(client, monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    resp = client.get("/insights")
    assert resp.status_code == 503


def test_insights_with_correct_key_returns_commentary(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    fake = Insights(
        summary="s",
        notable_patterns=[PatternNote(headline=f"h{i}", detail=f"d{i}") for i in range(3)],
        disclaimer="disc",
    )
    monkeypatch.setattr("powerball.api.generate_insights", lambda digest, **kw: fake)
    resp = client.get("/insights", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "s"
    assert len(body["notable_patterns"]) == 3


def test_insights_when_llm_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")

    def _raise(*args, **kwargs):
        raise LLMUnavailableError("no ollama running")

    monkeypatch.setattr("powerball.api.generate_insights", _raise)
    resp = client.get("/insights", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 503
    assert "no ollama running" in resp.json()["detail"]


def test_insights_pick_with_correct_key_returns_pick(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    fake = CommentaryPickResult(whites=(1, 2, 3, 4, 5), powerball=6, rationale="r")
    monkeypatch.setattr("powerball.api.generate_commentary_pick", lambda draws, digest, **kw: fake)
    resp = client.get("/insights/pick", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["whites"] == [1, 2, 3, 4, 5]
    assert body["powerball"] == 6
    assert "independent random events" in body["disclaimer"]


def test_insights_pick_when_llm_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")

    def _raise(*args, **kwargs):
        raise LLMUnavailableError("model not pulled")

    monkeypatch.setattr("powerball.api.generate_commentary_pick", _raise)
    resp = client.get("/insights/pick", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 503


# --- auth: X-API-Key gate, applied to all four new routes -----------------

AUTH_ROUTES = [
    ("/auth/signup", {"email": "a@example.com", "password": "hunter22222"}),
    ("/auth/login", {"email": "a@example.com", "password": "hunter22222"}),
    ("/auth/refresh", None),
    ("/auth/logout", None),
]


@pytest.mark.parametrize("path,body", AUTH_ROUTES)
def test_auth_route_without_key_configured_is_unavailable(client, monkeypatch, path, body):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    resp = client.post(path, json=body, headers={"X-Refresh-Token": "irrelevant"})
    assert resp.status_code == 503


@pytest.mark.parametrize("path,body", AUTH_ROUTES)
def test_auth_route_with_wrong_key_is_unauthorized(client, monkeypatch, path, body):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.post(
        path, json=body, headers={"X-API-Key": "wrong-key", "X-Refresh-Token": "irrelevant"}
    )
    assert resp.status_code == 401


# --- auth: signup -----------------------------------------------------------


def test_signup_with_correct_key_creates_user(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setattr(
        "powerball.api.create_user",
        lambda email, password_hash: UserRow(
            user_id="u-1", email=email, password_hash=password_hash, deleted=False
        ),
    )
    resp = client.post(
        "/auth/signup",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"user_id": "u-1", "email": "a@example.com"}


def test_signup_rejects_short_password(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    resp = client.post(
        "/auth/signup",
        json={"email": "a@example.com", "password": "short"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 422


def test_signup_with_duplicate_email_returns_409(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")

    def _raise(email, password_hash):
        raise UserAlreadyExistsError(f"an account with email {email!r} already exists")

    monkeypatch.setattr("powerball.api.create_user", _raise)
    resp = client.post(
        "/auth/signup",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 409


def test_signup_when_database_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")

    def _raise(email, password_hash):
        raise DatabaseUnavailableError("no database configured")

    monkeypatch.setattr("powerball.api.create_user", _raise)
    resp = client.post(
        "/auth/signup",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 503


# --- auth: login --------------------------------------------------------


def test_login_with_correct_credentials_issues_tokens(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    stored = UserRow(
        user_id="u-1",
        email="a@example.com",
        password_hash=hash_password("hunter22222"),
        deleted=False,
    )
    monkeypatch.setattr("powerball.api.get_user_by_email", lambda email: stored)
    stored_tokens = {}
    monkeypatch.setattr(
        "powerball.api.store_refresh_token",
        lambda user_id, token_hash, expires_at: stored_tokens.update(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        ),
    )
    resp = client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Access-Token"]
    assert resp.headers["X-Refresh-Token"]
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token_expires_in"] > 0
    assert body["refresh_token_expires_in"] > 0
    assert stored_tokens["user_id"] == "u-1"


def test_login_with_wrong_password_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    stored = UserRow(
        user_id="u-1",
        email="a@example.com",
        password_hash=hash_password("hunter22222"),
        deleted=False,
    )
    monkeypatch.setattr("powerball.api.get_user_by_email", lambda email: stored)
    resp = client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "wrong-password"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 401


def test_login_with_unknown_email_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    monkeypatch.setattr("powerball.api.get_user_by_email", lambda email: None)
    resp = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 401


def test_login_for_deleted_user_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    stored = UserRow(
        user_id="u-1",
        email="a@example.com",
        password_hash=hash_password("hunter22222"),
        deleted=True,
    )
    monkeypatch.setattr("powerball.api.get_user_by_email", lambda email: stored)
    resp = client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 401


def test_login_when_jwt_secret_unset_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.delenv(JWT_SECRET_ENV_VAR, raising=False)
    stored = UserRow(
        user_id="u-1",
        email="a@example.com",
        password_hash=hash_password("hunter22222"),
        deleted=False,
    )
    monkeypatch.setattr("powerball.api.get_user_by_email", lambda email: stored)
    resp = client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "hunter22222"},
        headers={"X-API-Key": "correct-key"},
    )
    assert resp.status_code == 503


# --- auth: refresh -------------------------------------------------------


def test_refresh_with_valid_token_rotates_and_issues_new_tokens(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    owner = UserRow(user_id="u-1", email="a@example.com", password_hash="irrelevant", deleted=False)
    monkeypatch.setattr(
        "powerball.api.rotate_refresh_token",
        lambda old_hash, new_hash, new_expires_at: owner,
    )
    resp = client.post(
        "/auth/refresh",
        headers={"X-API-Key": "correct-key", "X-Refresh-Token": "some-old-refresh-token"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Access-Token"]
    assert resp.headers["X-Refresh-Token"] != "some-old-refresh-token"


def test_refresh_with_invalid_token_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    monkeypatch.setattr(
        "powerball.api.rotate_refresh_token", lambda old_hash, new_hash, new_expires_at: None
    )
    resp = client.post(
        "/auth/refresh",
        headers={"X-API-Key": "correct-key", "X-Refresh-Token": "expired-or-unknown"},
    )
    assert resp.status_code == 401


def test_refresh_when_database_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")

    def _raise(old_hash, new_hash, new_expires_at):
        raise DatabaseUnavailableError("no database configured")

    monkeypatch.setattr("powerball.api.rotate_refresh_token", _raise)
    resp = client.post(
        "/auth/refresh",
        headers={"X-API-Key": "correct-key", "X-Refresh-Token": "some-token"},
    )
    assert resp.status_code == 503


# --- auth: logout --------------------------------------------------------


def test_logout_revokes_the_refresh_token(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")
    revoked = {}
    monkeypatch.setattr(
        "powerball.api.revoke_refresh_token",
        lambda token_hash: revoked.setdefault("hash", token_hash),
    )
    resp = client.post(
        "/auth/logout",
        headers={"X-API-Key": "correct-key", "X-Refresh-Token": "some-refresh-token"},
    )
    assert resp.status_code == 204
    assert revoked["hash"]


def test_logout_when_database_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "correct-key")

    def _raise(token_hash):
        raise DatabaseUnavailableError("no database configured")

    monkeypatch.setattr("powerball.api.revoke_refresh_token", _raise)
    resp = client.post(
        "/auth/logout",
        headers={"X-API-Key": "correct-key", "X-Refresh-Token": "some-refresh-token"},
    )
    assert resp.status_code == 503
