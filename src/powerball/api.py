"""HTTP API exposing pick generation.

- `GET /health` — unauthenticated liveness check.
- `GET /pick/quick` — uniform random pick(s), requires `X-API-Key`.
- `GET /pick/smart` — history-weighted pick(s), requires `X-API-Key`. Uses
  the server's `data/draws.csv` (loaded once at startup); it does not accept
  a client-supplied data path, to avoid turning the endpoint into an
  arbitrary file reader.

See `security.py` for the auth mechanism.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

from powerball.data import DEFAULT_DATA_PATH, Draw, load_draws
from powerball.picker import quick_pick, smart_pick
from powerball.security import require_api_key


class PickResponse(BaseModel):
    whites: list[int] = Field(description="Five white balls (1-69), ascending")
    powerball: int = Field(description="Powerball (1-26)")


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


def main() -> None:
    """Entry point for the `powerball-api` console script."""
    uvicorn.run("powerball.api:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
