"""HTTP API exposing pick generation and LLM-generated pattern commentary.

- `GET /health` — unauthenticated liveness check.
- `GET /pick/quick` — uniform random pick(s), requires `X-API-Key`.
- `GET /pick/smart` — history-weighted pick(s), requires `X-API-Key`. Uses
  the server's `data/draws.csv` (loaded once at startup); it does not accept
  a client-supplied data path, to avoid turning the endpoint into an
  arbitrary file reader.
- `GET /insights` — LLM-generated commentary on the same server-side
  history, requires `X-API-Key`. Calls the configured LLM backend (local
  Ollama by default; see `llm.py`); returns 503 if it or the configured
  model isn't reachable.
- `GET /insights/pick` — as above, plus a caveated AI commentary pick.

See `security.py` for the auth mechanism, `insights.py` for the LLM-commentary
implementation and its "novelty, not a predictive edge" framing, and `llm.py`
for the pluggable backend (Ollama/OpenAI-compatible) that calls run through.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from powerball.data import DEFAULT_DATA_PATH, Draw, load_draws
from powerball.insights import build_stats_digest, generate_commentary_pick, generate_insights
from powerball.llm import LLMUnavailableError
from powerball.picker import quick_pick, smart_pick
from powerball.security import require_api_key

# configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(filename)s: %(lineno)d] [Thread-%(thread)d] %(message)s",
    handlers=[logging.StreamHandler()],
)

log = logging.getLogger(__name__)


class PickResponse(BaseModel):
    whites: list[int] = Field(description="Five white balls (1-69), ascending")
    powerball: int = Field(description="Powerball (1-26)")


class PatternNoteResponse(BaseModel):
    headline: str
    detail: str


class InsightsResponse(BaseModel):
    summary: str
    notable_patterns: list[PatternNoteResponse]
    disclaimer: str


class CommentaryPickResponse(BaseModel):
    whites: list[int]
    powerball: int
    rationale: str
    disclaimer: str


def _to_response(draw: Draw) -> PickResponse:
    return PickResponse(whites=list(draw.whites), powerball=draw.powerball)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.draws = load_draws(DEFAULT_DATA_PATH)
    yield


app = FastAPI(title="powerball", lifespan=lifespan)

CountQuery = Annotated[int, Query(ge=1, le=25, description="Number of picks to generate")]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/pick/quick", dependencies=[Depends(require_api_key)])
def pick_quick(count: CountQuery = 1) -> list[PickResponse]:
    return [_to_response(quick_pick()) for _ in range(count)]


@app.get("/pick/smart", dependencies=[Depends(require_api_key)])
def pick_smart(count: CountQuery = 1) -> list[PickResponse]:
    draws = app.state.draws
    return [_to_response(smart_pick(draws)) for _ in range(count)]


@app.get("/insights", dependencies=[Depends(require_api_key)])
def insights() -> InsightsResponse:
    digest = build_stats_digest(app.state.draws)
    try:
        result = generate_insights(digest)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return InsightsResponse(**result.model_dump())


@app.get("/insights/pick", dependencies=[Depends(require_api_key)])
def insights_pick() -> CommentaryPickResponse:
    draws = app.state.draws
    digest = build_stats_digest(draws)
    log.debug("Generating commentary pick with digest: %s", digest)
    try:
        result = generate_commentary_pick(draws, digest)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return CommentaryPickResponse(
        whites=list(result.whites),
        powerball=result.powerball,
        rationale=result.rationale,
        disclaimer=result.disclaimer,
    )


def main() -> None:
    """Entry point for the `powerball-api` console script."""
    uvicorn.run("powerball.api:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
