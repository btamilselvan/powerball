"""LLM commentary on precomputed historical stats, via a pluggable backend.

Two things live here:
- `build_stats_digest`: turns raw draws into the same kind of small,
  deterministic summary a human doing `smart_pick` would eyeball — hot/cold
  numbers, sums, overdue numbers, etc. — via `powerball.stats`. This digest
  is the *only* thing sent to the model; raw draw rows never are.
- `generate_insights` / `generate_commentary_pick`: single calls to an LLM
  (see `powerball.llm` for the backend) that turn that digest into
  natural-language commentary, or (for the pick variant) a set of numbers
  "informed by" the digest.

Powerball drawings are independent random events. Nothing here is a
predictive edge — see `picker.smart_pick` for the same disclaimer applied to
the non-LLM strategy this builds on. `generate_commentary_pick`'s result
carries a hardcoded `DISCLAIMER` regardless of what the model itself says,
so the model can't omit it.

The actual model call is delegated to `powerball.llm.get_provider()`, which
picks a backend (local Ollama by default, or an OpenAI-compatible endpoint)
based on `$POWERBALL_INSIGHTS_PROVIDER` — see that module for backend
details and env vars. This module only cares that a provider exposes
`chat_json(system, user, schema) -> str`.

Structured output is enforced via each backend's own schema-constrained
decoding (Ollama's `format` param / OpenAI's `response_format`), generated
from the Pydantic models below. That only guarantees syntactically valid
JSON, not that a smaller model respects the schema's *intent* (e.g. it may
cram every pattern into `Insights.summary` and leave `notable_patterns`
empty). The Pydantic models carry real length/count constraints for exactly
this reason, so a degenerate-but-valid response fails validation and both
`generate_insights` and `generate_commentary_pick` reject-and-retry with a
sharper prompt rather than silently accepting it.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from powerball.data import Draw
from powerball.llm import LLMUnavailableError, get_provider
from powerball.rules import (
    POWERBALL_MAX,
    POWERBALL_MIN,
    WHITE_BALL_COUNT,
    WHITE_MAX,
    WHITE_MIN,
)
from powerball.stats import (
    cold_numbers,
    consecutive_pair_counts,
    decade_distribution,
    hot_numbers,
    odd_even_split,
    overdue_numbers,
    pair_frequency,
    positional_frequency,
    powerball_frequency,
    sum_distribution,
    white_ball_frequency,
)

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Powerball drawings are independent random events. Past frequency has no "
    "effect on future draws — this is a novelty/exploration feature, not a "
    "predictive edge."
)

SYSTEM_PROMPT = """You are summarizing precomputed statistics from historical \
Powerball draws for a hobbyist tool. You will be given aggregate counts \
(hot/cold numbers, sums, gaps since last seen, etc.) — never raw draw data.

Ground rules, non-negotiable:
- Powerball drawings are independent random events. A number's past \
frequency has zero effect on its odds in the next draw. Never say a number \
is "due", "overdue" in the sense of being more likely, "trending", or use \
any language implying predictive power.
- Describe only the patterns present in the given numbers. Do not invent \
statistics that are not in the input.
- Keep it concise and factual.

Output format, strictly enforced:
- `summary`: exactly ONE short sentence giving the overall picture (e.g. \
draw count and date range covered). Do not describe individual patterns \
here — that belongs in `notable_patterns`.
- `notable_patterns`: 3 to 8 separate entries, each covering exactly ONE \
pattern — a short headline plus 1-2 sentences of detail. Never combine \
multiple patterns into a single entry, and never fold pattern detail into \
`summary`. Each entry should be about a different kind of pattern (e.g. one \
about hot/cold numbers, one about sums, one about pairs) rather than several \
entries all repeating the same stat.
"""


class PatternNote(BaseModel):
    headline: str = Field(
        max_length=80,
        description="Short label for the pattern, e.g. '17 is the coldest white ball'",
    )
    detail: str = Field(
        max_length=280, description="One or two factual sentences, no predictive language"
    )


class Insights(BaseModel):
    summary: str = Field(
        max_length=320,
        description="ONE short overview sentence — never list individual patterns here",
    )
    notable_patterns: list[PatternNote] = Field(
        min_length=3,
        max_length=8,
        description="3-8 distinct patterns, each its own entry — never folded into summary",
    )
    disclaimer: str = Field(description="Restates that this is descriptive, not predictive")


class CommentaryPick(BaseModel):
    whites: list[int]
    powerball: int
    rationale: str = Field(
        max_length=500, description="Why these numbers, referencing only the given stats"
    )


@dataclass
class CommentaryPickResult:
    whites: tuple[int, ...]
    powerball: int
    rationale: str
    disclaimer: str = field(default=DISCLAIMER)


def build_stats_digest(draws: list[Draw]) -> dict:
    """Compact, JSON-serializable summary of `draws` — the only data sent to the model."""
    white_counts = white_ball_frequency(draws)
    pb_counts = powerball_frequency(draws)
    sums = [sum(d.whites) for d in draws]
    positions = positional_frequency(draws)

    return {
        "draw_count": len(draws),
        "date_range": {
            "from": min(d.date for d in draws).isoformat() if draws else None,
            "to": max(d.date for d in draws).isoformat() if draws else None,
        },
        "hot_whites": hot_numbers(white_counts, 10),
        "cold_whites": cold_numbers(white_counts, 10),
        "hot_powerballs": hot_numbers(pb_counts, 5),
        "cold_powerballs": cold_numbers(pb_counts, 5, is_powerball=True),
        "top_pairs": pair_frequency(draws).most_common(10),
        "odd_even_split": {
            f"{odd}_odd_{even}_even": count
            for (odd, even), count in odd_even_split(draws).most_common()
        },
        "consecutive_pair_distribution": dict(consecutive_pair_counts(draws)),
        "sum_stats": {
            "mean": round(statistics.mean(sums), 1) if sums else None,
            "median": statistics.median(sums) if sums else None,
            "min": min(sums) if sums else None,
            "max": max(sums) if sums else None,
        },
        "sum_distribution": dict(sum_distribution(draws)),
        "most_overdue_whites": sorted(
            overdue_numbers(draws).items(), key=lambda kv: kv[1], reverse=True
        )[:10],
        "most_overdue_powerballs": sorted(
            overdue_numbers(draws, is_powerball=True).items(), key=lambda kv: kv[1], reverse=True
        )[:5],
        "decade_distribution": dict(decade_distribution(draws)),
        "positional_hotspots": [c.most_common(3) for c in positions],
    }


def generate_insights(
    stats: dict,
    *,
    provider: str | None = None,
    model: str | None = None,
    host: str | None = None,
    max_attempts: int = 3,
) -> Insights:
    """Turn a `build_stats_digest` result into natural-language commentary.

    `provider`/`model`/`host` select and configure the backend (see
    `powerball.llm.get_provider`); all default to env vars when omitted.

    Schema-constrained decoding guarantees syntactically valid JSON, but
    smaller models don't reliably respect a schema's *semantic* intent —
    e.g. cramming every pattern into `summary` and leaving `notable_patterns`
    empty, technically valid JSON that violates the field-length/count
    constraints on `Insights`. Those constraints make that case a Pydantic
    `ValidationError`, which is treated the same as a malformed response:
    retry with a sharper correction, up to `max_attempts` times.

    Raises `LLMUnavailableError` if no well-formed response arrives within
    the attempt budget.
    """
    llm = get_provider(provider=provider, model=model, host=host)
    user_prompt = (
        f"Precomputed stats (JSON):\n{json.dumps(stats)}\n\nSummarize the notable patterns."
    )

    last_error: Exception | None = None
    for _ in range(max_attempts):
        content = llm.chat_json(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema=Insights.model_json_schema(),
        )
        try:
            insights = Insights.model_validate_json(content)
        except Exception as e:  # pydantic ValidationError or malformed JSON
            last_error = e
            user_prompt += (
                "\n\nYour previous answer didn't follow the required format: `summary` must "
                "be exactly one short sentence with no pattern detail in it, and each distinct "
                "pattern must be its own entry in `notable_patterns` (at least 3 entries, each "
                "under 280 characters) — not folded into `summary`. Try again."
            )
            continue
        insights.disclaimer = DISCLAIMER  # code-owned; never trust the model's own wording alone
        return insights

    raise LLMUnavailableError(
        f"model '{llm.model}' didn't return well-formed insights after {max_attempts} attempts: "
        f"{last_error}"
    )


def generate_commentary_pick(
    draws: list[Draw],
    stats: dict,
    *,
    provider: str | None = None,
    model: str | None = None,
    host: str | None = None,
    max_attempts: int = 2,
) -> CommentaryPickResult:
    """Ask the model for a ticket "informed by" `stats`, validated against game rules.

    `draws` isn't sent to the model (only `stats` is) — it's accepted here for
    signature symmetry with other pick-generating functions and to leave room
    for future validation against actual history. This is a novelty feature
    layered on `picker.smart_pick`'s framing: the model gets no special access
    to randomness or future information, only the same digest a human would
    look at. Every result carries `DISCLAIMER` regardless of what the model
    itself says.

    `provider`/`model`/`host` select and configure the backend (see
    `powerball.llm.get_provider`); all default to env vars when omitted.

    Raises `LLMUnavailableError` if the model doesn't return a valid pick
    (distinct, in-range numbers) within `max_attempts` tries.
    """
    del draws  # not sent to the model; see docstring
    llm = get_provider(provider=provider, model=model, host=host)
    user_prompt = (
        f"Precomputed stats (JSON):\n{json.dumps(stats)}\n\n"
        f"Propose {WHITE_BALL_COUNT} distinct white balls in [{WHITE_MIN}, {WHITE_MAX}] "
        f"and one powerball in [{POWERBALL_MIN}, {POWERBALL_MAX}], informed by these stats. "
        "This does not change the true odds of any ticket — say so in your rationale."
    )

    last_error: Exception | None = None
    for _ in range(max_attempts):
        content = llm.chat_json(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema=CommentaryPick.model_json_schema(),
        )
        try:
            log.debug("model returned pick content: %s", content)
            pick = CommentaryPick.model_validate_json(content)
            whites = tuple(sorted(pick.whites))
            _validate_pick(whites, pick.powerball)
        except Exception as e:  # pydantic ValidationError, our own ValueError, malformed JSON
            last_error = e
            user_prompt += (
                "\n\nYour previous answer was invalid (numbers must be distinct, in-range, "
                "and correctly counted). Try again."
            )
            continue
        return CommentaryPickResult(
            whites=whites, powerball=pick.powerball, rationale=pick.rationale
        )

    raise LLMUnavailableError(
        f"model '{llm.model}' didn't return a valid pick after {max_attempts} attempts: "
        f"{last_error}"
    )


def _validate_pick(whites: tuple[int, ...], powerball: int) -> None:
    if len(whites) != WHITE_BALL_COUNT or len(set(whites)) != WHITE_BALL_COUNT:
        raise ValueError(f"expected {WHITE_BALL_COUNT} distinct white balls, got {whites}")
    if not all(WHITE_MIN <= n <= WHITE_MAX for n in whites):
        raise ValueError(f"white balls out of range [{WHITE_MIN}, {WHITE_MAX}]: {whites}")
    if not POWERBALL_MIN <= powerball <= POWERBALL_MAX:
        raise ValueError(f"powerball out of range [{POWERBALL_MIN}, {POWERBALL_MAX}]: {powerball}")
