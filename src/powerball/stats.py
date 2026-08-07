"""Frequency analysis over historical draws.

Everything here operates on plain `Counter`s so results are easy to test,
print, or feed into `picker.smart_pick` as weights.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from powerball.data import Draw
from powerball.rules import POWERBALL_MAX, POWERBALL_MIN, WHITE_MAX, WHITE_MIN


def white_ball_frequency(draws: Iterable[Draw]) -> Counter[int]:
    """Count how often each white ball (1-69) has appeared."""
    counts: Counter[int] = Counter()
    for draw in draws:
        counts.update(draw.whites)
    return counts


def powerball_frequency(draws: Iterable[Draw]) -> Counter[int]:
    """Count how often each powerball (1-26) has appeared."""
    return Counter(draw.powerball for draw in draws)


def hot_numbers(counts: Counter[int], n: int = 10) -> list[tuple[int, int]]:
    """The `n` most frequently drawn numbers, most frequent first."""
    return counts.most_common(n)


def cold_numbers(
    counts: Counter[int], n: int = 10, *, is_powerball: bool = False
) -> list[tuple[int, int]]:
    """The `n` least frequently drawn numbers, including numbers never drawn (count 0)."""
    lo, hi = (POWERBALL_MIN, POWERBALL_MAX) if is_powerball else (WHITE_MIN, WHITE_MAX)
    full = {i: counts.get(i, 0) for i in range(lo, hi + 1)}
    return sorted(full.items(), key=lambda kv: (kv[1], kv[0]))[:n]
