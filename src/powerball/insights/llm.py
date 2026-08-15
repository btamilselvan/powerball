"""Pluggable LLM backends for `insights.py`.

`insights.py` only needs one thing from a backend: turn a system prompt, a
user prompt, and a JSON schema into a raw JSON string. `LLMProvider` is that
one-method interface; everything else in here is picking and configuring an
implementation of it.

Two backends ship, both talking HTTP directly via `httpx` — no vendor SDKs:

- `ollama` (default): a local Ollama server (`ollama serve`), no API key,
  no network egress beyond localhost. Uses Ollama's own `/api/chat` with its
  `format` parameter for schema-constrained decoding.
- `openai`: OpenAI's API, or anything that speaks the same
  `/chat/completions` wire format — LM Studio, vLLM, Groq, Together, etc.
  Uses `response_format={"type": "json_schema", ...}`. Requires an API key
  for real OpenAI; self-hosted OpenAI-compatible servers often don't check
  it, but the header is always sent if a key is configured.

Select a backend with `POWERBALL_INSIGHTS_PROVIDER` (`ollama` or `openai`).
Model/host/key are provider-scoped env vars — see each class below — so
switching providers doesn't require unsetting the other provider's config.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx

PROVIDER_ENV_VAR = "POWERBALL_INSIGHTS_PROVIDER"
DEFAULT_PROVIDER = "ollama"

REQUEST_TIMEOUT_SECONDS = 120


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM backend or model isn't reachable/available."""


class LLMProvider(ABC):
    """One LLM backend, configured and ready to make chat calls."""

    @abstractmethod
    def chat_json(self, *, system: str, user: str, schema: dict) -> str:
        """Return the model's raw JSON-string reply, steered toward `schema`.

        Callers (insights.py) are responsible for validating the result
        against the schema themselves — a provider can only ask the backend
        to conform, not guarantee it, especially for smaller models.
        """


class OllamaProvider(LLMProvider):
    """Local Ollama server, talked to directly over HTTP (no `ollama` package)."""

    MODEL_ENV_VAR = "POWERBALL_INSIGHTS_MODEL"
    DEFAULT_MODEL = "gemma4:e4b"
    HOST_ENV_VAR = "OLLAMA_HOST"
    DEFAULT_HOST = "http://localhost:11434"

    def __init__(self, *, model: str | None = None, host: str | None = None):
        self.model = model or os.environ.get(self.MODEL_ENV_VAR, self.DEFAULT_MODEL)
        self.host = (host or os.environ.get(self.HOST_ENV_VAR, self.DEFAULT_HOST)).rstrip("/")

    def chat_json(self, *, system: str, user: str, schema: dict) -> str:
        try:
            response = httpx.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "format": schema,
                    "stream": False,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise LLMUnavailableError(
                    f"model '{self.model}' isn't pulled — run `ollama pull {self.model}`"
                ) from e
            raise LLMUnavailableError(
                f"Ollama returned an error: {e.response.status_code} {e.response.text}"
            ) from e
        except httpx.HTTPError as e:
            # Deliberately broad: connection-refused/DNS/timeout errors surface
            # as different httpx exception subclasses. The goal is a friendly,
            # actionable CLI/API message, not fine-grained transport handling.
            raise LLMUnavailableError(
                f"couldn't reach Ollama at {self.host} — is `ollama serve` running? ({e})"
            ) from e
        return response.json()["message"]["content"]


class OpenAIProvider(LLMProvider):
    """OpenAI's API, or any server implementing the same chat-completions wire format."""

    MODEL_ENV_VAR = "POWERBALL_INSIGHTS_MODEL"
    DEFAULT_MODEL = "gpt-4o-mini"
    HOST_ENV_VAR = "POWERBALL_INSIGHTS_HOST"
    DEFAULT_HOST = "https://api.openai.com/v1"
    # Checked in order; POWERBALL_INSIGHTS_API_KEY wins so a non-OpenAI
    # OpenAI-compatible server doesn't have to masquerade under OPENAI_API_KEY.
    API_KEY_ENV_VARS = ("POWERBALL_INSIGHTS_API_KEY", "OPENAI_API_KEY")

    def __init__(self, *, model: str | None = None, host: str | None = None):
        self.model = model or os.environ.get(self.MODEL_ENV_VAR, self.DEFAULT_MODEL)
        self.host = (host or os.environ.get(self.HOST_ENV_VAR, self.DEFAULT_HOST)).rstrip("/")
        self.api_key = next(
            (os.environ[var] for var in self.API_KEY_ENV_VARS if os.environ.get(var)), None
        )
        if not self.api_key:
            keys = " or ".join(f"${v}" for v in self.API_KEY_ENV_VARS)
            raise LLMUnavailableError(f"{keys} isn't set — required for the openai provider")

    def chat_json(self, *, system: str, user: str, schema: dict) -> str:
        try:
            response = httpx.post(
                f"{self.host}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "response", "schema": schema},
                    },
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMUnavailableError(
                f"'{self.model}' at {self.host} returned an error: "
                f"{e.response.status_code} {e.response.text}"
            ) from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(
                f"couldn't reach the openai-compatible endpoint at {self.host} ({e})"
            ) from e
        return response.json()["choices"][0]["message"]["content"]


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
}
SUPPORTED_PROVIDERS = tuple(sorted(_PROVIDERS))


def get_provider(
    *, provider: str | None = None, model: str | None = None, host: str | None = None
) -> LLMProvider:
    """Instantiate the configured `LLMProvider`.

    `provider` falls back to `$POWERBALL_INSIGHTS_PROVIDER`, then `"ollama"`.
    `model`/`host` are passed straight through to the chosen provider class,
    which applies its own env-var fallback and default.
    """
    name = (provider or os.environ.get(PROVIDER_ENV_VAR, DEFAULT_PROVIDER)).lower()
    try:
        provider_cls = _PROVIDERS[name]
    except KeyError:
        raise LLMUnavailableError(
            f"unknown provider '{name}' — choose one of {sorted(_PROVIDERS)}"
        ) from None
    return provider_cls(model=model, host=host)
