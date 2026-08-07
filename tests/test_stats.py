from collections import Counter

from powerball.data import load_draws
from powerball.stats import cold_numbers, hot_numbers, powerball_frequency, white_ball_frequency


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
