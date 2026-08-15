"""HTTP API exposing pick generation, LLM-generated pattern commentary, and user auth.

- `GET /health` — unauthenticated liveness check.
- `GET /pick/quick` — uniform random pick(s), requires `X-API-Key`.
- `GET /pick/smart` — history-weighted pick(s), requires `X-API-Key`. Uses
  the server's `data/draws.csv` (loaded once at startup); it does not accept
  a client-supplied data path, to avoid turning the endpoint into an
  arbitrary file reader.
- `GET /insights` — LLM-generated commentary on the same server-side
  history, requires `X-API-Key`. Calls the configured LLM backend (local
  Ollama by default; see `insights/llm.py`); returns 503 if it or the
  configured model isn't reachable.
- `GET /insights/pick` — as above, plus a caveated AI commentary pick.
- `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`,
  `POST /auth/logout` — user accounts backed by Postgres (`auth/db.py`) and
  JWT/refresh-token sessions (`auth/service.py`); all four also require
  `X-API-Key`. See those modules' docstrings for the token model.

See `security.py` for the `X-API-Key` mechanism, `insights/insights.py` for the LLM-commentary
implementation and its "novelty, not a predictive edge" framing, `insights/llm.py` for the
pluggable backend (Ollama/OpenAI-compatible) that calls run through, and `auth/db.py` /
`auth/service.py` for the auth implementation.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr, Field

from powerball.auth.db import (
    DatabaseUnavailableError,
    UserAlreadyExistsError,
    create_user,
    get_user_by_email,
    revoke_refresh_token,
    rotate_refresh_token,
    store_refresh_token,
)
from powerball.auth.service import (
    AuthConfigError,
    access_token_ttl,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_ttl,
    verify_password,
)
from powerball.draws.data import DEFAULT_DATA_PATH, Draw, load_draws
from powerball.draws.picker import quick_pick, smart_pick
from powerball.insights.insights import (
    build_stats_digest,
    generate_commentary_pick,
    generate_insights,
)
from powerball.insights.llm import LLMUnavailableError
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


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=16, description="8-16 characters")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str


class TokenIssuedResponse(BaseModel):
    """Confirms tokens were issued; the tokens themselves are only ever in response headers

    (`X-Access-Token`, `X-Refresh-Token`) — never in the JSON body, so they don't end up
    duplicated in logs/caches that capture bodies but not headers any more than necessary.
    """

    token_type: str = "Bearer"
    access_token_expires_in: int = Field(description="Access token lifetime, in seconds")
    refresh_token_expires_in: int = Field(description="Refresh token lifetime, in seconds")


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


RefreshTokenHeader = Annotated[str, Header(alias="X-Refresh-Token")]


def _write_tokens(response: Response, access_token: str, refresh_token: str) -> TokenIssuedResponse:
    response.headers["X-Access-Token"] = access_token
    response.headers["X-Refresh-Token"] = refresh_token
    return TokenIssuedResponse(
        access_token_expires_in=int(access_token_ttl().total_seconds()),
        refresh_token_expires_in=int(refresh_token_ttl().total_seconds()),
    )


@app.post("/auth/signup", status_code=201, dependencies=[Depends(require_api_key)])
def signup(body: SignupRequest) -> UserResponse:
    try:
        user = create_user(body.name, body.email, hash_password(body.password))
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return UserResponse(user_id=str(user.user_id), email=user.email, name=user.name)


@app.post("/auth/login", dependencies=[Depends(require_api_key)])
def login(body: LoginRequest, response: Response) -> TokenIssuedResponse:
    try:
        user = get_user_by_email(body.email)
        if user is None or user.deleted or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid email or password")
        access_token, _ = create_access_token(user_id=user.user_id, email=user.email)
        refresh_token = generate_refresh_token()
        store_refresh_token(
            user.user_id,
            hash_refresh_token(refresh_token),
            datetime.now(timezone.utc) + refresh_token_ttl(),
        )
    except (DatabaseUnavailableError, AuthConfigError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return _write_tokens(response, access_token, refresh_token)


@app.post("/auth/refresh", dependencies=[Depends(require_api_key)])
def refresh(response: Response, x_refresh_token: RefreshTokenHeader) -> TokenIssuedResponse:
    new_refresh_token = generate_refresh_token()
    try:
        user = rotate_refresh_token(
            hash_refresh_token(x_refresh_token),
            hash_refresh_token(new_refresh_token),
            datetime.now(timezone.utc) + refresh_token_ttl(),
        )
        if user is None:
            raise HTTPException(
                status_code=401, detail="invalid, expired, or revoked refresh token"
            )
        access_token, _ = create_access_token(user_id=user.user_id, email=user.email)
    except (DatabaseUnavailableError, AuthConfigError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return _write_tokens(response, access_token, new_refresh_token)


@app.post("/auth/logout", status_code=204, dependencies=[Depends(require_api_key)])
def logout(x_refresh_token: RefreshTokenHeader) -> None:
    try:
        revoke_refresh_token(hash_refresh_token(x_refresh_token))
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def main() -> None:
    """Entry point for the `powerball-api` console script."""
    uvicorn.run("powerball.api:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
