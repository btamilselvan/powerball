from collections import Counter
from datetime import date

from powerball.data import Draw, load_draws
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


def test_white_ball_frequency_counts_five_per_draw():
    draws = load_draws()
    counts = white_ball_frequency(draws)
    assert sum(counts.values()) == len(draws) * 5


def test_powerball_frequency_counts_one_per_draw():
    draws = load_draws()
    counts = powerball_frequency(draws)
    assert sum(counts.values()) == len(draws)


def test_hot_numbers_orders_by_count_desc():
    counts = Counter({1: 5, 2: 9, 3: 1})
    assert hot_numbers(counts, n=2) == [(2, 9), (1, 5)]


def test_cold_numbers_includes_never_drawn():
    counts = Counter({1: 5})
    result = cold_numbers(counts, n=3)
    assert result[0][1] == 0  # some never-drawn number leads


def _draw(whites, powerball=1, d=date(2024, 1, 1)):
    return Draw(date=d, whites=tuple(sorted(whites)), powerball=powerball)


def test_pair_frequency_counts_cooccurring_pairs():
    draws = [_draw([1, 2, 3, 4, 5]), _draw([1, 2, 10, 11, 12])]
    counts = pair_frequency(draws)
    assert counts[(1, 2)] == 2
    assert counts[(3, 4)] == 1
    assert (10, 11) in counts


def test_odd_even_split_counts_per_draw():
    counts = odd_even_split([_draw([1, 3, 5, 7, 9]), _draw([2, 4, 6, 8, 10])])
    assert counts[(5, 0)] == 1
    assert counts[(0, 5)] == 1


def test_consecutive_pair_counts_detects_adjacent_numbers():
    counts = consecutive_pair_counts([_draw([1, 2, 3, 10, 20]), _draw([1, 5, 10, 15, 20])])
    assert counts[2] == 1  # 1-2 and 2-3 adjacent
    assert counts[0] == 1  # no adjacent pairs


def test_positional_frequency_returns_five_counters_lowest_to_highest():
    positions = positional_frequency([_draw([1, 10, 20, 30, 69])])
    assert len(positions) == 5
    assert positions[0][1] == 1
    assert positions[4][69] == 1


def test_overdue_numbers_zero_for_most_recent_draw():
    draws = [_draw([1, 2, 3, 4, 5]), _draw([6, 7, 8, 9, 10])]
    gaps = overdue_numbers(draws)
    assert gaps[6] == 0  # in the most recent draw
    assert gaps[1] == 1  # one draw back
    assert gaps[69] == len(draws)  # never appeared


def test_overdue_numbers_powerball():
    draws = [_draw([1, 2, 3, 4, 5], powerball=10), _draw([6, 7, 8, 9, 10], powerball=20)]
    gaps = overdue_numbers(draws, is_powerball=True)
    assert gaps[20] == 0
    assert gaps[10] == 1


def test_decade_distribution_buckets_by_tens():
    counts = decade_distribution([_draw([1, 15, 25, 65, 69])])
    assert counts["1-10"] == 1
    assert counts["11-20"] == 1
    assert counts["61-69"] == 2  # truncated last bucket holds both 65 and 69


def test_sum_distribution_buckets_by_width():
    counts = sum_distribution([_draw([1, 2, 3, 4, 5])], bucket_width=20)  # sum = 15
    assert counts["0-19"] == 1
