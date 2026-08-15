import pytest

from powerball.draws.data import DEFAULT_DATA_PATH, Draw, load_draws, recent_draws


def test_load_draws_reads_default_data():
    draws = load_draws(DEFAULT_DATA_PATH)
    assert len(draws) > 0
    assert len(draws[0].whites) == 5
    assert len(set(draws[0].whites)) == 5


def test_draw_rejects_duplicate_whites():
    with pytest.raises(ValueError, match="unique"):
        Draw(date=draws_date(), whites=(1, 1, 2, 3, 4), powerball=5)


def test_draw_rejects_out_of_range_powerball():
    with pytest.raises(ValueError, match="powerball"):
        Draw(date=draws_date(), whites=(1, 2, 3, 4, 5), powerball=99)


def test_recent_draws_requires_exactly_one_of_years_or_months():
    draws = [Draw(date=draws_date(), whites=(1, 2, 3, 4, 5), powerball=1)]
    with pytest.raises(ValueError, match="exactly one"):
        recent_draws(draws)
    with pytest.raises(ValueError, match="exactly one"):
        recent_draws(draws, years=1, months=1)


def test_recent_draws_filters_relative_to_newest_draw():
    from datetime import date

    old = Draw(date=date(2020, 1, 1), whites=(1, 2, 3, 4, 5), powerball=1)
    recent = Draw(date=date(2024, 6, 1), whites=(6, 7, 8, 9, 10), powerball=2)
    result = recent_draws([old, recent], years=1)
    assert result == [recent]


def test_recent_draws_on_empty_list_returns_empty():
    assert recent_draws([], months=6) == []


def draws_date():
    from datetime import date

    return date(2024, 1, 1)
