"""Frequency and pattern analysis over historical draws.

Everything here operates on plain `Counter`s (or dicts of them) so results
are easy to test, print, feed into `picker.smart_pick` as weights, or hand to
`insights.build_stats_digest` as input for LLM-generated commentary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import combinations

from powerball.draws.data import Draw
from powerball.draws.rules import (
    POWERBALL_MAX,
    POWERBALL_MIN,
    WHITE_BALL_COUNT,
    WHITE_MAX,
    WHITE_MIN,
)


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


def pair_frequency(draws: Iterable[Draw]) -> Counter[tuple[int, int]]:
    """Count how often each unordered pair of white balls has appeared together."""
    counts: Counter[tuple[int, int]] = Counter()
    for draw in draws:
        counts.update(combinations(sorted(draw.whites), 2))
    return counts


def odd_even_split(draws: Iterable[Draw]) -> Counter[tuple[int, int]]:
    """Count draws by their (odd_count, even_count) white-ball split, e.g. (3, 2)."""
    counts: Counter[tuple[int, int]] = Counter()
    for draw in draws:
        odd = sum(1 for n in draw.whites if n % 2 == 1)
        counts[(odd, len(draw.whites) - odd)] += 1
    return counts


def consecutive_pair_counts(draws: Iterable[Draw]) -> Counter[int]:
    """Count draws by how many adjacent-number pairs (e.g. 14, 15) they contain."""
    counts: Counter[int] = Counter()
    for draw in draws:
        whites = sorted(draw.whites)
        adjacent = sum(1 for a, b in zip(whites, whites[1:], strict=False) if b - a == 1)
        counts[adjacent] += 1
    return counts


def positional_frequency(draws: Iterable[Draw]) -> list[Counter[int]]:
    """Frequency of each value at each sorted position (lowest to highest) across draws.

    Returns a list of length `WHITE_BALL_COUNT`; index 0 is the lowest ball
    drawn each time, index 4 the highest.
    """
    positions: list[Counter[int]] = [Counter() for _ in range(WHITE_BALL_COUNT)]
    for draw in draws:
        for i, n in enumerate(sorted(draw.whites)):
            positions[i][n] += 1
    return positions


def overdue_numbers(draws: Sequence[Draw], *, is_powerball: bool = False) -> dict[int, int]:
    """Draws elapsed since each number last appeared (0 = appeared in the most recent draw).

    `draws` must be oldest-to-newest (as returned by `load_draws`). Numbers
    that never appear in `draws` get a gap of `len(draws)` — the max a real
    gap can reach is `len(draws) - 1`, so that value is unambiguous.
    """
    lo, hi = (POWERBALL_MIN, POWERBALL_MAX) if is_powerball else (WHITE_MIN, WHITE_MAX)
    gaps = {n: len(draws) for n in range(lo, hi + 1)}
    for gap, draw in enumerate(reversed(draws)):
        numbers = (draw.powerball,) if is_powerball else draw.whites
        for n in numbers:
            if gaps[n] == len(draws):  # not yet set — this is its most recent appearance
                gaps[n] = gap
    return gaps


def decade_distribution(draws: Iterable[Draw]) -> Counter[str]:
    """Count white balls falling into each 10-wide range label, e.g. '1-10', ..., '61-69'."""
    counts: Counter[str] = Counter()
    for draw in draws:
        for n in draw.whites:
            lo = ((n - 1) // 10) * 10 + 1
            hi = min(lo + 9, WHITE_MAX)
            counts[f"{lo}-{hi}"] += 1
    return counts


def sum_distribution(draws: Iterable[Draw], *, bucket_width: int = 20) -> Counter[str]:
    """Count draws by the sum of their five white balls, bucketed into `bucket_width`-wide bins."""
    counts: Counter[str] = Counter()
    for draw in draws:
        total = sum(draw.whites)
        lo = (total // bucket_width) * bucket_width
        hi = lo + bucket_width - 1
        counts[f"{lo}-{hi}"] += 1
    return counts
