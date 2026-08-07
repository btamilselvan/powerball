# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small Python tool for analyzing historical Powerball draws and generating ticket picks. Two pick
strategies: `quick` (uniform random) and `smart` (weighted toward numbers that have appeared more
often in the supplied historical data). Powerball drawings are independent random events — `smart`
is a novelty/exploration feature, not a real edge, and any UI/docs text should keep saying so.

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

POWERBALL_API_KEY=some-secret uv run powerball-api      # run the HTTP API (see api.py)
POWERBALL_API_KEY=some-secret uv run uvicorn powerball.api:app --reload  # with autoreload
```

## Architecture

Source lives under `src/powerball/` (src layout). Data flows one direction through four modules:

- `rules.py` — the only place game constants live (white ball range/count, powerball range). Every
  other module imports from here rather than hardcoding 1-69 / 1-26 / 5, so a rules change only
  needs one edit.
- `data.py` — `Draw` (frozen dataclass, validates itself against `rules.py` in `__post_init__`) and
  `load_draws()`, which parses the CSV format (header row + rows shaped like
  `"Wed, Jan 3, 2024",4,15,29,32,36,5` — date, 5 whites, powerball, read positionally) into `Draw`
  objects. `DEFAULT_DATA_PATH` is `data/draws.csv`, resolved relative to the process's current
  working directory (not to this file) — `data/` isn't packaged into distributions, so a
  `Path(__file__)`-relative default would break once the package is installed from a wheel.
- `stats.py` — pure functions over `Iterable[Draw]` → `Counter`, plus `hot_numbers`/`cold_numbers`
  helpers. `cold_numbers` fills in numbers with zero occurrences so they aren't silently omitted.
- `picker.py` — `quick_pick()` and `smart_pick(draws)`, both returning a `Draw`. `smart_pick` uses
  `stats.py`'s frequency counts as weights (+1 Laplace smoothing so untouched numbers stay
  possible) and falls back to effectively-uniform behavior when `draws` is empty. Both accept an
  optional `random.Random` for deterministic tests.
- `cli.py` — argparse wiring (`pick`, `stats` subcommands) on top of the above; no logic of its own.
- `api.py` — FastAPI app exposing `GET /health` (unauthenticated) and `GET /pick/quick` /
  `GET /pick/smart` (both behind `security.require_api_key`, `?count=` 1-25). Draws are loaded once
  at startup (`lifespan`) into `app.state.draws` rather than re-read per request. `/pick/smart`
  always reads the server's own `data/draws.csv` — it deliberately does not accept a client-supplied
  path, to avoid turning the endpoint into an arbitrary file reader.
- `security.py` — `require_api_key`, a FastAPI dependency checking the `X-API-Key` header against
  the `POWERBALL_API_KEY` env var with `secrets.compare_digest`. Fails closed: if the env var isn't
  set, protected endpoints return 503 rather than allowing unauthenticated access.

`data/draws.csv` holds the historical draw data used by the CLI, tests, and API by default (see
`data/README.md` for the row format). Pass `--data path/to/file.csv` to point the CLI at a different
file; the API always uses `data/draws.csv`.
