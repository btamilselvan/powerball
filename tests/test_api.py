import pytest
from fastapi.testclient import TestClient

from powerball.api import app
from powerball.rules import POWERBALL_MAX, POWERBALL_MIN, WHITE_MAX, WHITE_MIN
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
