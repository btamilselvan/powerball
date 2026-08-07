"""Generating ticket picks.

Two strategies:
- `quick_pick`: uniform random, same odds as an in-store quick pick.
- `smart_pick`: weighted by historical draw frequency (via `powerball.stats`),
  as a novelty/exploration tool. Powerball drawings are independent random
  events, so no strategy changes the true odds of any single ticket — this
  exists for people who want their numbers informed by history anyway.
"""

from __future__ import annotations

import random
from collections import Counter

from powerball.data import Draw
from powerball.rules import (
    POWERBALL_MAX,
    POWERBALL_MIN,
    WHITE_BALL_COUNT,
    WHITE_MAX,
    WHITE_MIN,
)
from powerball.stats import powerball_frequency, white_ball_frequency


def quick_pick(rng: random.Random | None = None) -> Draw:
    """A uniformly random ticket, ignoring any historical data."""
    rng = rng or random.Random()
    whites = tuple(sorted(rng.sample(range(WHITE_MIN, WHITE_MAX + 1), WHITE_BALL_COUNT)))
    powerball = rng.randint(POWERBALL_MIN, POWERBALL_MAX)
    return Draw(date=_today(), whites=whites, powerball=powerball)


def smart_pick(draws: list[Draw], rng: random.Random | None = None) -> Draw:
    """A ticket weighted toward numbers that have appeared more often historically.

    Falls back to `quick_pick` behavior for any pool with zero total weight
    (e.g. an empty `draws` list).
    """
    rng = rng or random.Random()
    white_weights = _weights_for_range(white_ball_frequency(draws), WHITE_MIN, WHITE_MAX)
    whites = tuple(sorted(_weighted_sample(white_weights, WHITE_BALL_COUNT, rng)))

    pb_weights = _weights_for_range(powerball_frequency(draws), POWERBALL_MIN, POWERBALL_MAX)
    powerball = _weighted_sample(pb_weights, 1, rng)[0]

    return Draw(date=_today(), whites=whites, powerball=powerball)


def _today():
    from datetime import date

    return date.today()


def _weights_for_range(counts: Counter[int], lo: int, hi: int) -> dict[int, float]:
    # +1 smoothing so every number stays possible even with sparse history.
    return {n: counts.get(n, 0) + 1 for n in range(lo, hi + 1)}


def _weighted_sample(weights: dict[int, float], k: int, rng: random.Random) -> list[int]:
    pool = dict(weights)
    chosen: list[int] = []
    for _ in range(k):
        numbers = list(pool.keys())
        picked = rng.choices(numbers, weights=[pool[n] for n in numbers], k=1)[0]
        chosen.append(picked)
        del pool[picked]
    return chosen
