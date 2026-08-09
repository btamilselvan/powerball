import json

import pytest

from powerball.data import load_draws
from powerball.insights import (
    DISCLAIMER,
    OllamaUnavailableError,
    build_stats_digest,
    generate_commentary_pick,
    generate_insights,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeClient:
    """Stands in for `ollama.Client` — `chat()` returns canned responses, never hits a server.

    Pass one content string for a single-shot response, or several to feed a
    retry loop one response per call (the last one repeats if called beyond
    what was given).
    """

    def __init__(self, *contents):
        self._contents = list(contents)

    def chat(self, **kwargs):
        content = self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]
        return _FakeResponse(content)


class _BrokenClient:
    def chat(self, **kwargs):
        raise ConnectionError("connection refused")


@pytest.fixture
def draws():
    return load_draws()


def test_build_stats_digest_is_json_serializable(draws):
    digest = build_stats_digest(draws)
    json.dumps(digest)  # raises TypeError if anything (e.g. a tuple key) isn't serializable
    assert digest["draw_count"] == len(draws)
    assert digest["date_range"]["from"] is not None


def _insights_payload(n_patterns=3):
    return json.dumps(
        {
            "summary": "test summary",
            "notable_patterns": [
                {"headline": f"h{i}", "detail": f"d{i}"} for i in range(n_patterns)
            ],
            "disclaimer": "whatever the model made up",
        }
    )


def test_generate_insights_parses_response_and_stamps_disclaimer(monkeypatch, draws):
    monkeypatch.setattr(
        "powerball.insights.ollama.Client", lambda host=None: _FakeClient(_insights_payload())
    )
    result = generate_insights(build_stats_digest(draws))
    assert result.summary == "test summary"
    assert len(result.notable_patterns) == 3
    assert result.notable_patterns[0].headline == "h0"
    assert result.disclaimer == DISCLAIMER  # code-owned, overwrites the model's own wording


def test_generate_insights_wraps_connection_failure(monkeypatch, draws):
    monkeypatch.setattr("powerball.insights.ollama.Client", lambda host=None: _BrokenClient())
    with pytest.raises(OllamaUnavailableError, match="ollama serve"):
        generate_insights(build_stats_digest(draws))


def test_generate_insights_retries_when_patterns_are_folded_into_summary(monkeypatch, draws):
    # Simulates a small model cramming everything into `summary` and leaving
    # `notable_patterns` empty — syntactically valid JSON, but violates the
    # min_length=3 constraint on notable_patterns, so it should be rejected
    # and retried rather than silently accepted.
    degenerate = json.dumps(
        {"summary": "everything crammed in here " * 20, "notable_patterns": [], "disclaimer": "d"}
    )
    well_formed = _insights_payload()
    monkeypatch.setattr(
        "powerball.insights.ollama.Client",
        lambda host=None: _FakeClient(degenerate, well_formed),
    )
    result = generate_insights(build_stats_digest(draws))
    assert len(result.notable_patterns) == 3


def test_generate_insights_raises_after_repeated_format_violations(monkeypatch, draws):
    degenerate = json.dumps(
        {"summary": "everything crammed in here " * 20, "notable_patterns": [], "disclaimer": "d"}
    )
    monkeypatch.setattr(
        "powerball.insights.ollama.Client", lambda host=None: _FakeClient(degenerate)
    )
    with pytest.raises(OllamaUnavailableError, match="didn't return well-formed insights"):
        generate_insights(build_stats_digest(draws), max_attempts=2)


def test_generate_commentary_pick_validates_and_returns(monkeypatch, draws):
    payload = {"whites": [5, 4, 3, 2, 1], "powerball": 10, "rationale": "r"}
    monkeypatch.setattr(
        "powerball.insights.ollama.Client", lambda host=None: _FakeClient(json.dumps(payload))
    )
    result = generate_commentary_pick(draws, build_stats_digest(draws))
    assert result.whites == (1, 2, 3, 4, 5)  # sorted
    assert result.powerball == 10
    assert result.disclaimer == DISCLAIMER


def test_generate_commentary_pick_rejects_invalid_output_after_retries(monkeypatch, draws):
    payload = {"whites": [1, 1, 1, 1, 1], "powerball": 999, "rationale": "bad"}
    monkeypatch.setattr(
        "powerball.insights.ollama.Client", lambda host=None: _FakeClient(json.dumps(payload))
    )
    with pytest.raises(OllamaUnavailableError, match="didn't return a valid pick"):
        generate_commentary_pick(draws, build_stats_digest(draws), max_attempts=2)
