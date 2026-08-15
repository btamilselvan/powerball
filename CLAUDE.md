# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small Python tool for analyzing historical Powerball draws and generating ticket picks. Two pick
strategies: `quick` (uniform random) and `smart` (weighted toward numbers that have appeared more
often in the supplied historical data). Powerball drawings are independent random events — `smart`
is a novelty/exploration feature, not a real edge, and any UI/docs text should keep saying so.

There's also an `insights` feature that uses an LLM (local Ollama by default, or an
OpenAI-compatible endpoint — see `insights/llm.py`) to turn the same historical stats into
natural-language commentary, and optionally a caveated "AI commentary pick". Same rule applies:
this is descriptive/novelty output layered on real historical data, never framed as a predictive
edge. See `insights/insights.py`'s module docstring for the specifics.

The HTTP API additionally has user accounts (`/auth/signup`, `/auth/login`, `/auth/refresh`,
`/auth/logout`) backed by a Postgres database (e.g. Supabase), with JWT access tokens and
opaque, rotating refresh tokens. See `auth/db.py` and `auth/service.py`'s module docstrings, and
`db/schema.sql` for the DDL.

## Commands

Dependency management and running commands both go through `uv`.

```bash
uv sync --extra dev          # install runtime + dev deps (pytest, ruff, fastapi, uvicorn, httpx,
                              # psycopg, pyjwt, bcrypt)

uv run pytest                # run all tests
uv run pytest tests/test_stats.py::test_hot_numbers_orders_by_count_desc  # run a single test

uv run ruff check .          # lint
uv run ruff format .         # format (format --check . to verify without writing)

uv run powerball pick --strategy quick --count 5
uv run powerball pick --strategy smart --count 5
uv run powerball stats --top 10

uv run powerball insights                    # LLM commentary over the full history
uv run powerball insights --years 1          # ...over just the last year
uv run powerball insights --pick             # ...plus a caveated AI commentary pick
# default provider is Ollama: requires a local server (`ollama serve`) with the
# target model pulled (`ollama pull gemma4:e4b` or whatever POWERBALL_INSIGHTS_MODEL points at)
uv run powerball insights --provider openai  # ...or hit an OpenAI-compatible endpoint instead

POWERBALL_API_KEY=some-secret uv run powerball-api      # run the HTTP API (see api.py)
POWERBALL_API_KEY=some-secret uv run uvicorn powerball.api:app --reload  # with autoreload
```

`insights` backend selection (`insights/llm.py`) is `POWERBALL_INSIGHTS_PROVIDER` (`ollama`, the
default, or `openai`), all optional and provider-scoped:
- `ollama`: `POWERBALL_INSIGHTS_MODEL` (default `gemma4:e4b`), `OLLAMA_HOST` (default
  `http://localhost:11434`). No API key — inference is local.
- `openai`: `POWERBALL_INSIGHTS_MODEL` (default `gpt-4o-mini`), `POWERBALL_INSIGHTS_HOST` (default
  `https://api.openai.com/v1` — point this at any OpenAI-compatible server), and an API key via
  `POWERBALL_INSIGHTS_API_KEY` or `OPENAI_API_KEY` (checked in that order).

The `/auth/*` endpoints (`auth/db.py`, `auth/service.py`) need, all required and fail-closed
(missing → 503, same as `POWERBALL_API_KEY`):
- `POWERBALL_DATABASE_URL` — a Postgres connection string (Supabase's, or any Postgres). Run
  `db/schema.sql` against it first (it assumes `app_user` already exists).
- `POWERBALL_JWT_SECRET` — HMAC secret for signing access-token JWTs.
- Optional: `POWERBALL_ACCESS_TOKEN_TTL_MINUTES` (default 15), `POWERBALL_REFRESH_TOKEN_TTL_DAYS`
  (default 30).

## Architecture

Source lives under `src/powerball/` (src layout), split into three feature subpackages plus a
thin top-level API/CLI layer that wires them together. Within `draws/`, data flows one direction
through `rules.py → data.py → stats.py → picker.py`.

### `draws/` — core lottery domain

- `rules.py` — the only place game constants live (white ball range/count, powerball range). Every
  other module imports from here rather than hardcoding 1-69 / 1-26 / 5, so a rules change only
  needs one edit.
- `data.py` — `Draw` (frozen dataclass, validates itself against `rules.py` in `__post_init__`),
  `load_draws()`, which parses the CSV format (header row + rows shaped like
  `"Wed, Jan 3, 2024",4,15,29,32,36,5` — date, 5 whites, powerball, read positionally) into `Draw`
  objects, and `recent_draws(draws, *, years=, months=)`, a pure filter to the last N years/months
  relative to the newest draw in the list (not `date.today()`, so results stay reproducible). Note
  `Draw.__post_init__` validates every row against today's `rules.py` ranges — loading data from
  before the Oct 2015 rule change (different white-ball/powerball ranges) will raise immediately
  rather than silently mixing incompatible eras. `DEFAULT_DATA_PATH` is `data/draws.csv`, resolved
  relative to the process's current working directory (not to this file) — `data/` isn't packaged
  into distributions, so a `Path(__file__)`-relative default would break once the package is
  installed from a wheel.
- `stats.py` — pure functions over `Iterable[Draw]` → `Counter` (or a dict/list of them):
  frequency (`white_ball_frequency`, `powerball_frequency`, `hot_numbers`/`cold_numbers`), plus
  pattern analysis (`pair_frequency`, `odd_even_split`, `consecutive_pair_counts`,
  `positional_frequency`, `overdue_numbers`, `decade_distribution`, `sum_distribution`). Feeds both
  `picker.smart_pick` (as weights) and `insights.build_stats_digest` (as LLM input). `cold_numbers`
  and `overdue_numbers` fill in numbers with zero occurrences / max gap so they aren't silently
  omitted.
- `picker.py` — `quick_pick()` and `smart_pick(draws)`, both returning a `Draw`. `smart_pick` uses
  `stats.py`'s frequency counts as weights (+1 Laplace smoothing so untouched numbers stay
  possible) and falls back to effectively-uniform behavior when `draws` is empty. Both accept an
  optional `random.Random` for deterministic tests.

### `insights/` — LLM-generated commentary

- `llm.py` — pluggable LLM backend, talked to directly over HTTP via `httpx` (no vendor SDKs, so no
  `ollama` package dependency). `LLMProvider` is a one-method interface (`chat_json(system, user,
  schema) -> str`); `OllamaProvider` (default, local, no API key) and `OpenAIProvider` (OpenAI or
  any OpenAI-compatible `/chat/completions` server — LM Studio, vLLM, Groq, etc.) implement it.
  `get_provider(provider=, model=, host=)` picks one based on `$POWERBALL_INSIGHTS_PROVIDER`
  (`ollama`/`openai`, default `ollama`), falling back through each provider's own env vars — see
  the module docstring. `LLMUnavailableError` wraps connection failures, missing-model/auth errors,
  and unknown-provider names with an actionable message.
- `insights.py` — LLM-generated commentary, backend-agnostic (delegates the actual model call to
  `llm.py`). `build_stats_digest(draws)` turns `draws/stats.py` output into a compact
  JSON-serializable dict — the *only* thing sent to the model, never raw draw rows.
  `generate_insights(stats)` returns a structured `Insights` (summary + notable patterns), enforced
  via the backend's own schema-constrained decoding. `generate_commentary_pick(draws, stats)`
  additionally proposes a ticket, validated against `draws/rules.py` before being accepted (retries
  once on an invalid response, then raises). Every `generate_commentary_pick` result carries a
  hardcoded `DISCLAIMER` regardless of what the model itself says — never trust the model to
  include it unprompted.

### `auth/` — user accounts and sessions

- `db.py` — the only module that touches the `app_user` / `refresh_tokens` Postgres tables
  directly (schema in `db/schema.sql`; `app_user` is assumed to pre-exist). Talks to Postgres over
  a `psycopg` connection pool (not the `supabase-py` SDK), consistent with `insights/llm.py`'s
  "wire protocol directly, no vendor SDK" approach. `get_pool()` reads `POWERBALL_DATABASE_URL`
  lazily on first use and fails closed (`DatabaseUnavailableError` → 503, mapped in `api.py` the
  same way as `LLMUnavailableError`) rather than at import time. `create_user` raises
  `UserAlreadyExistsError` on a duplicate email. `rotate_refresh_token` does the whole
  validate-old/revoke-old/insert-new dance in one transaction with a row lock, so two concurrent
  `/auth/refresh` calls on the same token can't both succeed.
- `service.py` — password hashing (bcrypt), JWT access tokens (`pyjwt`, HS256, signed with
  `POWERBALL_JWT_SECRET`), and refresh-token generation. No SQL, no FastAPI — pure functions, kept
  separate from `db.py` so both halves are independently testable. Refresh tokens are opaque random
  strings (`generate_refresh_token`), not JWTs, so an individual one can be revoked server-side;
  only a sha256 hash of the raw token is ever persisted (`hash_refresh_token`), never the raw
  value. `AuthConfigError` (missing `POWERBALL_JWT_SECRET`) also maps to 503 in `api.py`.

### Top level

- `cli.py` — argparse wiring (`pick`, `stats`, `insights` subcommands) on top of `draws/` and
  `insights/`; no logic of its own. `insights` takes `--provider`/`--model`/`--host`, each
  defaulting to the matching env var when omitted.
- `api.py` — FastAPI app exposing `GET /health` (unauthenticated), `GET /pick/quick` / `GET
  /pick/smart` / `GET /insights` / `GET /insights/pick`, and `POST /auth/signup` / `POST
  /auth/login` / `POST /auth/refresh` / `POST /auth/logout` (all behind
  `security.require_api_key`; `/pick/*` also take `?count=` 1-25). Draws are loaded once at
  startup (`lifespan`) into `app.state.draws` rather than re-read per request. `/pick/smart` and
  `/insights*` always read the server's own `data/draws.csv` — they deliberately don't accept a
  client-supplied path, to avoid turning the endpoints into an arbitrary file reader. `/insights*`
  don't accept a client-supplied provider/model either (env vars only) and return 503 (not 500) on
  `LLMUnavailableError` — a down/unpulled local model or an upstream API outage is an availability
  problem, not a server bug. `/auth/login` and `/auth/refresh` put issued tokens only in response
  headers (`X-Access-Token`, `X-Refresh-Token`), never in the JSON body; `/auth/refresh` rotates
  the refresh token on every call (old one revoked, new one issued).
- `security.py` — `require_api_key`, a FastAPI dependency checking the `X-API-Key` header against
  the `POWERBALL_API_KEY` env var with `secrets.compare_digest`. Fails closed: if the env var isn't
  set, protected endpoints return 503 rather than allowing unauthenticated access. Guards
  `/pick/*`, `/insights*`, and all `/auth/*` — `insights/insights.py`'s own LLM calls (via
  `insights/llm.py`) need no separate key when using the default local Ollama backend.

`data/draws.csv` holds the historical draw data used by the CLI, tests, and API by default (see
`data/README.md` for the row format). Pass `--data path/to/file.csv` to point the CLI at a different
file; the API always uses `data/draws.csv`.

`db/schema.sql` holds the DDL for the `refresh_tokens` table (plus a commented-out reference copy
of the assumed `app_user` schema) used by `auth/db.py`.
