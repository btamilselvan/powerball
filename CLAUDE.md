# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small Python tool for analyzing historical Powerball draws and generating ticket picks. Two pick
strategies: `quick` (uniform random) and `smart` (weighted toward numbers that have appeared more
often in the supplied historical data). Powerball drawings are independent random events — `smart`
is a novelty/exploration feature, not a real edge, and any UI/docs text should keep saying so.

There's also an `insights` feature that uses a local LLM (via Ollama) to turn the same historical
stats into natural-language commentary, and optionally a caveated "AI commentary pick". Same rule
applies: this is descriptive/novelty output layered on real historical data, never framed as a
predictive edge. See `insights.py`'s module docstring for the specifics.

## Commands

Dependency management and running commands both go through `uv`.

```bash
uv sync --extra dev          # install runtime + dev deps (pytest, ruff, fastapi, uvicorn, httpx)

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
# requires a local Ollama server (`ollama serve`) with the target model pulled
# (`ollama pull gemma4:e4b` or whatever POWERBALL_INSIGHTS_MODEL points at)

POWERBALL_API_KEY=some-secret uv run powerball-api      # run the HTTP API (see api.py)
POWERBALL_API_KEY=some-secret uv run uvicorn powerball.api:app --reload  # with autoreload
```

Env vars for `insights` (both optional): `POWERBALL_INSIGHTS_MODEL` (default `gemma4:e4b`),
`OLLAMA_HOST` (default `http://localhost:11434`). No API key needed — inference is local.

## Architecture

Source lives under `src/powerball/` (src layout). Data flows one direction through these modules:

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
- `insights.py` — LLM-generated commentary via a **local Ollama** server (no API key; see
  `MODEL_ENV_VAR`/`HOST_ENV_VAR`). `build_stats_digest(draws)` turns `stats.py` output into a
  compact JSON-serializable dict — the *only* thing sent to the model, never raw draw rows.
  `generate_insights(stats)` returns a structured `Insights` (summary + notable patterns), enforced
  via Ollama's `format=<json schema>` constrained decoding. `generate_commentary_pick(draws, stats)`
  additionally proposes a ticket, validated against `rules.py` before being accepted (retries once
  on an invalid response, then raises). Every `generate_commentary_pick` result carries a
  hardcoded `DISCLAIMER` regardless of what the model itself says — never trust the model to include
  it unprompted. `OllamaUnavailableError` wraps both connection failures and missing-model errors
  with an actionable message (`ollama pull <model>` / `ollama serve`).
- `cli.py` — argparse wiring (`pick`, `stats`, `insights` subcommands) on top of the above; no logic
  of its own.
- `api.py` — FastAPI app exposing `GET /health` (unauthenticated), `GET /pick/quick` / `GET
  /pick/smart` / `GET /insights` / `GET /insights/pick` (all behind `security.require_api_key`;
  `/pick/*` also take `?count=` 1-25). Draws are loaded once at startup (`lifespan`) into
  `app.state.draws` rather than re-read per request. `/pick/smart` and `/insights*` always read the
  server's own `data/draws.csv` — they deliberately don't accept a client-supplied path, to avoid
  turning the endpoints into an arbitrary file reader. `/insights*` return 503 (not 500) on
  `OllamaUnavailableError` — a down/unpulled local model is an availability problem, not a server bug.
- `security.py` — `require_api_key`, a FastAPI dependency checking the `X-API-Key` header against
  the `POWERBALL_API_KEY` env var with `secrets.compare_digest`. Fails closed: if the env var isn't
  set, protected endpoints return 503 rather than allowing unauthenticated access. Only guards
  `/pick/*` and `/insights*` — `insights.py`'s own Ollama calls need no key, since inference is local.

`data/draws.csv` holds the historical draw data used by the CLI, tests, and API by default (see
`data/README.md` for the row format). Pass `--data path/to/file.csv` to point the CLI at a different
file; the API always uses `data/draws.csv`.
