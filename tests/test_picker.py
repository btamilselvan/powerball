import random

from powerball.draws.data import load_draws
from powerball.draws.picker import quick_pick, smart_pick
from powerball.draws.rules import POWERBALL_MAX, POWERBALL_MIN, WHITE_MAX, WHITE_MIN


def test_quick_pick_is_valid_and_reproducible_with_seeded_rng():
    a = quick_pick(rng=random.Random(1))
    b = quick_pick(rng=random.Random(1))
    assert a.whites == b.whites
    assert a.powerball == b.powerball
    assert len(set(a.whites)) == 5
    assert all(WHITE_MIN <= n <= WHITE_MAX for n in a.whites)
    assert POWERBALL_MIN <= a.powerball <= POWERBALL_MAX


def test_smart_pick_falls_back_gracefully_on_empty_history():
    draw = smart_pick([], rng=random.Random(1))
    assert len(set(draw.whites)) == 5


def test_smart_pick_uses_real_history():
    draws = load_draws()
    draw = smart_pick(draws, rng=random.Random(1))
    assert len(set(draw.whites)) == 5
    assert POWERBALL_MIN <= draw.powerball <= POWERBALL_MAX
