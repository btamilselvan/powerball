from datetime import timedelta

import jwt
import pytest

from powerball.auth.service import (
    ACCESS_TOKEN_TTL_ENV_VAR,
    DEFAULT_ACCESS_TOKEN_TTL_MINUTES,
    DEFAULT_REFRESH_TOKEN_TTL_DAYS,
    JWT_SECRET_ENV_VAR,
    REFRESH_TOKEN_TTL_ENV_VAR,
    AuthConfigError,
    access_token_ttl,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_ttl,
    verify_password,
)

# --- passwords ------------------------------------------------------------


def test_hash_password_roundtrips_with_verify_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_password_never_stores_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in hashed


# --- access tokens ----------------------------------------------------------


def test_create_and_decode_access_token_roundtrips(monkeypatch):
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    token, expires_at = create_access_token(user_id="u-1", email="a@example.com")
    claims = decode_access_token(token)
    assert claims.user_id == "u-1"
    assert claims.email == "a@example.com"
    # JWT `exp` is an integer NumericDate (RFC 7519 section 2), so sub-second precision
    # doesn't round-trip through encode/decode.
    assert claims.expires_at == expires_at.replace(microsecond=0)


def test_create_access_token_raises_when_secret_unset(monkeypatch):
    monkeypatch.delenv(JWT_SECRET_ENV_VAR, raising=False)
    with pytest.raises(AuthConfigError, match=JWT_SECRET_ENV_VAR):
        create_access_token(user_id="u-1", email="a@example.com")


def test_decode_access_token_raises_when_secret_unset(monkeypatch):
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    token, _ = create_access_token(user_id="u-1", email="a@example.com")
    monkeypatch.delenv(JWT_SECRET_ENV_VAR, raising=False)
    with pytest.raises(AuthConfigError, match=JWT_SECRET_ENV_VAR):
        decode_access_token(token)


def test_decode_access_token_rejects_expired_token(monkeypatch):
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    monkeypatch.setenv(ACCESS_TOKEN_TTL_ENV_VAR, "-1")
    token, _ = create_access_token(user_id="u-1", email="a@example.com")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_decode_access_token_rejects_tampered_token(monkeypatch):
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    token, _ = create_access_token(user_id="u-1", email="a@example.com")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token + "tampered")


def test_decode_access_token_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "test-secret-that-is-long-enough-1234567890")
    token, _ = create_access_token(user_id="u-1", email="a@example.com")
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, "a-different-secret-that-is-long-enough-098765")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_access_token_ttl_defaults(monkeypatch):
    monkeypatch.delenv(ACCESS_TOKEN_TTL_ENV_VAR, raising=False)
    assert access_token_ttl() == timedelta(minutes=DEFAULT_ACCESS_TOKEN_TTL_MINUTES)


def test_access_token_ttl_reads_env_var(monkeypatch):
    monkeypatch.setenv(ACCESS_TOKEN_TTL_ENV_VAR, "5")
    assert access_token_ttl() == timedelta(minutes=5)


# --- refresh tokens ---------------------------------------------------------


def test_generate_refresh_token_is_high_entropy_and_unique():
    a, b = generate_refresh_token(), generate_refresh_token()
    assert a != b
    assert len(a) >= 32


def test_hash_refresh_token_is_deterministic_and_not_reversible():
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert hash_refresh_token(token) != token
    assert len(hash_refresh_token(token)) == 64  # sha256 hex digest


def test_refresh_token_ttl_defaults(monkeypatch):
    monkeypatch.delenv(REFRESH_TOKEN_TTL_ENV_VAR, raising=False)
    assert refresh_token_ttl() == timedelta(days=DEFAULT_REFRESH_TOKEN_TTL_DAYS)


def test_refresh_token_ttl_reads_env_var(monkeypatch):
    monkeypatch.setenv(REFRESH_TOKEN_TTL_ENV_VAR, "7")
    assert refresh_token_ttl() == timedelta(days=7)
