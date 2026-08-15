import httpx
import pytest

from powerball.insights.llm import (
    DEFAULT_PROVIDER,
    PROVIDER_ENV_VAR,
    LLMUnavailableError,
    OllamaProvider,
    OpenAIProvider,
    get_provider,
)


def _response(status_code, json_body, url="http://example.test/"):
    return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", url))


# --- OllamaProvider -----------------------------------------------------


def test_ollama_provider_returns_message_content(monkeypatch):
    monkeypatch.setattr(
        "powerball.insights.llm.httpx.post",
        lambda *a, **kw: _response(200, {"message": {"content": '{"ok": true}'}}),
    )
    provider = OllamaProvider(model="m", host="http://localhost:11434")
    assert provider.chat_json(system="s", user="u", schema={}) == '{"ok": true}'


def test_ollama_provider_wraps_missing_model_as_actionable_error(monkeypatch):
    monkeypatch.setattr(
        "powerball.insights.llm.httpx.post", lambda *a, **kw: _response(404, {"error": "not found"})
    )
    provider = OllamaProvider(model="ghost-model", host="http://localhost:11434")
    with pytest.raises(LLMUnavailableError, match="ollama pull ghost-model"):
        provider.chat_json(system="s", user="u", schema={})


def test_ollama_provider_wraps_connection_failure(monkeypatch):
    def _raise(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("powerball.insights.llm.httpx.post", _raise)
    provider = OllamaProvider(model="m", host="http://localhost:11434")
    with pytest.raises(LLMUnavailableError, match="ollama serve"):
        provider.chat_json(system="s", user="u", schema={})


# --- OpenAIProvider -------------------------------------------------------


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("POWERBALL_INSIGHTS_API_KEY", raising=False)
    with pytest.raises(LLMUnavailableError, match="OPENAI_API_KEY"):
        OpenAIProvider(model="gpt-4o-mini")


def test_openai_provider_returns_message_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "powerball.insights.llm.httpx.post",
        lambda *a, **kw: _response(200, {"choices": [{"message": {"content": '{"ok": true}'}}]}),
    )
    provider = OpenAIProvider(model="gpt-4o-mini")
    assert provider.chat_json(system="s", user="u", schema={}) == '{"ok": true}'


def test_openai_provider_prefers_scoped_api_key_over_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-wrong")
    monkeypatch.setenv("POWERBALL_INSIGHTS_API_KEY", "sk-right")
    provider = OpenAIProvider(model="gpt-4o-mini")
    assert provider.api_key == "sk-right"


def test_openai_provider_wraps_error_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "powerball.insights.llm.httpx.post", lambda *a, **kw: _response(401, {"error": "bad key"})
    )
    provider = OpenAIProvider(model="gpt-4o-mini")
    with pytest.raises(LLMUnavailableError, match="401"):
        provider.chat_json(system="s", user="u", schema={})


# --- get_provider -----------------------------------------------------


def test_get_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv(PROVIDER_ENV_VAR, raising=False)
    assert DEFAULT_PROVIDER == "ollama"
    assert isinstance(get_provider(), OllamaProvider)


def test_get_provider_reads_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv(PROVIDER_ENV_VAR, "openai")
    assert isinstance(get_provider(), OpenAIProvider)


def test_get_provider_rejects_unknown_provider():
    with pytest.raises(LLMUnavailableError, match="unknown provider"):
        get_provider(provider="not-a-real-provider")
