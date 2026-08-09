# powerball

A small Python tool for analyzing historical Powerball draws and generating
ticket picks.

Two pick strategies:

- **quick** — uniform random (equivalent to an in-store quick pick).
- **smart** — weighted toward numbers that have appeared more often in the
  supplied historical data.

Powerball drawings are independent random events: no strategy changes the
true odds of winning. `smart` exists as a novelty/exploration tool for
people who want their numbers informed by history anyway.

There's also an `insights` command that uses a local LLM (via
[Ollama](https://ollama.com)) to turn the same historical stats into
natural-language commentary, and optionally a caveated "AI commentary pick".
Same caveat applies: it's descriptive/novelty output layered on real
historical data, not a predictive edge.

## Install

```bash
uv sync --extra dev
```

## Usage

```bash
uv run powerball pick --strategy quick --count 5
uv run powerball pick --strategy smart --count 5
uv run powerball stats --top 10
```

By default these commands read `data/draws.csv` — see `data/README.md` for
the format. Pass `--data path/to/file.csv` to use a different file.

### Insights (local LLM)

Requires a local Ollama server with a model pulled:

```bash
ollama pull gemma4:e4b   # or whichever model you want to use
ollama serve
```

```bash
uv run powerball insights                    # commentary over the full history
uv run powerball insights --years 1          # ...over just the last year
uv run powerball insights --months 6         # (or months — --years and --months are mutually exclusive)
uv run powerball insights --pick             # ...plus a caveated AI commentary pick
```

No API key needed — inference runs entirely locally. Configure via env vars
(both optional): `POWERBALL_INSIGHTS_MODEL` (default `gemma4:e4b`) and
`OLLAMA_HOST` (default `http://localhost:11434`).

## API

An HTTP API exposes the same two pick strategies plus insights and a health
check, protected by a shared API key. `/insights*` additionally require a
reachable local Ollama server (see above) — they return `503` if it isn't.

```bash
POWERBALL_API_KEY=some-secret uv run powerball-api
# or, for auto-reload during development:
POWERBALL_API_KEY=some-secret uv run uvicorn powerball.api:app --reload
```

Alternatively, copy `.env.example` to `.env` and set `POWERBALL_API_KEY` there —
it's loaded automatically (via `python-dotenv`) and gitignored, so it never
needs to be exported manually or committed:

```bash
cp .env.example .env   # then edit .env
uv run powerball-api
```

| Endpoint            | Auth | Notes                                          |
|---------------------|------|-------------------------------------------------|
| `GET /health`       | none | liveness check                                  |
| `GET /pick/quick`   | `X-API-Key` header | `?count=` (1-25, default 1)       |
| `GET /pick/smart`   | `X-API-Key` header | `?count=` (1-25, default 1); always reads `data/draws.csv` |
| `GET /insights`     | `X-API-Key` header | LLM commentary over the full `data/draws.csv` history |
| `GET /insights/pick`| `X-API-Key` header | as above, plus a caveated AI commentary pick |

If `POWERBALL_API_KEY` isn't set, the protected endpoints respond `503`
rather than allowing unauthenticated access.

```bash
curl -H "X-API-Key: some-secret" "http://localhost:8000/pick/quick?count=3"
```

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Build

### Wheel

```bash
uv build --wheel   # writes dist/powerball-<version>-py3-none-any.whl
```

`data/draws.csv` isn't bundled into the wheel — only `src/powerball` is (see
`pyproject.toml`). `DEFAULT_DATA_PATH` resolves `data/draws.csv` relative to
the process's working directory, so an installed wheel still needs a
`data/draws.csv` alongside wherever it's run from:

```bash
pip install "dist/powerball-0.1.0-py3-none-any.whl[api]"
POWERBALL_API_KEY=some-secret powerball-api   # run from a directory containing data/
```

### Docker

Two Dockerfiles, both serving the HTTP API on port 8000:

- **`Dockerfile`** — traditional flow: copies source, `uv sync`, runs `uv run powerball-api`.
- **`Dockerfile.wheel`** — builds the `.whl` in one stage, `pip install`s it (with the `api`
  extra) into a clean stage, and runs `powerball-api` directly — no `uv` or source tree in the
  final image.

```bash
docker build -t powerball:sync -f Dockerfile .
docker build -t powerball:wheel -f Dockerfile.wheel .

docker run --rm -p 8000:8000 -e POWERBALL_API_KEY=some-secret powerball:sync
# or
docker run --rm -p 8000:8000 -e POWERBALL_API_KEY=some-secret powerball:wheel
```

Both images `COPY data ./data` at build time, so updating `data/draws.csv` normally means
rebuilding the image. Bind-mount the directory instead to pick up edits with just a container
restart — no rebuild:

```bash
docker run --rm -p 8000:8000 \
  -e POWERBALL_API_KEY=some-secret \
  -v "$(pwd)/data:/app/data" \
  powerball:sync
```

Edit `data/draws.csv` on the host, then `docker restart <container>` (the API loads draws once at
startup — see `lifespan` in `api.py` — so a running container won't pick up the change without a
restart).

## References
- https://portalseven.com/lottery/powerball_winning_numbers.jsp?viewType=2&timeRange=5