# Traditional method: copy source, `uv sync`, run.
#
# Build:  docker build -t powerball:sync .
# Run:    docker run --rm -p 8000:8000 -e POWERBALL_API_KEY=change-me powerball:sync
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install deps first so this layer is cached as long as pyproject/lock don't change.
COPY pyproject.toml uv.lock ./
RUN uv sync --extra api --no-install-project --no-dev

# Now bring in the source and install the project itself.
COPY src ./src
COPY data ./data
COPY README.md ./
RUN uv sync --extra api --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "powerball-api"]
