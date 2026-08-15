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

There's also an `insights` command that uses an LLM to turn the same
historical stats into natural-language commentary, and optionally a
caveated "AI commentary pick". The backend is pluggable — local
[Ollama](https://ollama.com) by default, or any OpenAI-compatible endpoint —
see [Insights](#insights-pluggable-llm) below. Same caveat applies: it's
descriptive/novelty output layered on real historical data, not a
predictive edge.

The HTTP API also has real user accounts (signup/login/refresh/logout) backed by Postgres — see
[Auth](#auth) below.

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

### Insights (pluggable LLM)

By default, requires a local Ollama server with a model pulled:

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

The backend is pluggable (`--provider`, or `$POWERBALL_INSIGHTS_PROVIDER`):

- **`ollama`** (default) — a local server, no API key. Configure via
  `POWERBALL_INSIGHTS_MODEL` (default `gemma4:e4b`) and `OLLAMA_HOST`
  (default `http://localhost:11434`).
- **`openai`** — OpenAI's API, or any server speaking the same
  `/chat/completions` format (LM Studio, vLLM, Groq, Together, etc).
  Configure via `POWERBALL_INSIGHTS_MODEL` (default `gpt-4o-mini`),
  `POWERBALL_INSIGHTS_HOST` (default `https://api.openai.com/v1`), and an
  API key via `POWERBALL_INSIGHTS_API_KEY` or `OPENAI_API_KEY`.

```bash
export OPENAI_API_KEY=sk-...
uv run powerball insights --provider openai --model gpt-4o-mini
```

`--model`/`--host` (or their env-var equivalents) override the selected
provider's defaults; both backends talk HTTP directly (via `httpx`), no
vendor SDK required.

## API

An HTTP API exposes the same two pick strategies plus insights and a health
check, protected by a shared API key. `/insights*` additionally require a
reachable configured LLM backend (see above) — they return `503` if it
isn't. The API always uses the server's own env-configured provider; it
doesn't accept a client-supplied provider/model.

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
| `POST /auth/signup` | `X-API-Key` header | create an account; `409` if the email's taken |
| `POST /auth/login`  | `X-API-Key` header | issues an access + refresh token (see [Auth](#auth) below) |
| `POST /auth/refresh`| `X-API-Key` header + `X-Refresh-Token` header | rotates the refresh token, issues a new access token |
| `POST /auth/logout` | `X-API-Key` header + `X-Refresh-Token` header | revokes the refresh token; always `204` |

If `POWERBALL_API_KEY` isn't set, the protected endpoints respond `503`
rather than allowing unauthenticated access.

```bash
curl -H "X-API-Key: some-secret" "http://localhost:8000/pick/quick?count=3"
```

### Auth

Real user accounts, backed by Postgres (e.g. a [Supabase](https://supabase.com) project — any
Postgres works, connected to directly via `psycopg`, not the `supabase-py` SDK). Login issues a
short-lived JWT access token plus a long-lived, rotating refresh token; both are returned **only**
in response headers, never in the JSON body.

Setup:

1. Create `app_user` (columns: `user_id`, `email`, `password`, `created_on`, `deleted`) if you
   haven't already, then run [`db/schema.sql`](db/schema.sql) to create `refresh_tokens`.
2. Set these env vars (fail-closed like `POWERBALL_API_KEY` — missing → `503`):

   | Var | Default | Purpose |
   |---|---|---|
   | `POWERBALL_DATABASE_URL` | *(required)* | Postgres connection string |
   | `POWERBALL_JWT_SECRET` | *(required)* | HMAC secret for signing access tokens |
   | `POWERBALL_ACCESS_TOKEN_TTL_MINUTES` | `15` | Access token lifetime |
   | `POWERBALL_REFRESH_TOKEN_TTL_DAYS` | `30` | Refresh token lifetime |

```bash
# create an account
curl -X POST http://localhost:8000/auth/signup \
  -H "X-API-Key: some-secret" -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "correct horse battery staple"}'

# log in — tokens come back as response headers
curl -i -X POST http://localhost:8000/auth/login \
  -H "X-API-Key: some-secret" -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "correct horse battery staple"}'
#   X-Access-Token: eyJ...
#   X-Refresh-Token: 9f2c...

# once the access token expires, trade the refresh token for a new pair
# (the old refresh token is revoked in the same call — it can't be reused)
curl -i -X POST http://localhost:8000/auth/refresh \
  -H "X-API-Key: some-secret" -H "X-Refresh-Token: 9f2c..."

# log out — revokes the refresh token
curl -X POST http://localhost:8000/auth/logout \
  -H "X-API-Key: some-secret" -H "X-Refresh-Token: 9f2c..."
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