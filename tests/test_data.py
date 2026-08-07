import pytest

from powerball.data import DEFAULT_DATA_PATH, Draw, load_draws


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


def draws_date():
    from datetime import date

    return date(2024, 1, 1)
