"""Loading and validating historical Powerball draw records.

Draw data is plain CSV with a header row followed by rows shaped like:
    "Mon, Aug 3, 2026",8,30,41,48,54,4
i.e. a quoted `Day, Mon D, YYYY` date, then the five white balls (any order),
then the powerball. Columns are read positionally (the header's exact names
don't matter, only that a row is present to skip). `load_draws` is the single
entry point the rest of the package uses to turn a CSV file into `Draw`
objects.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from pathlib import Path

from powerball.rules import (
    POWERBALL_MAX,
    POWERBALL_MIN,
    WHITE_BALL_COUNT,
    WHITE_MAX,
    WHITE_MIN,
)

# Relative to the current working directory, not to this file. `data/draws.csv`
# isn't packaged into distributions (see pyproject.toml's wheel `packages`
# list) — it's an external input the CLI/API expect to find alongside
# wherever they're run from, same as `--data path/to/file.csv` documents.
# A `Path(__file__)`-relative default would resolve fine in an editable/
# src-layout checkout but silently point outside the install once the
# package is `pip install`'d from a wheel (no `data/` sibling three
# directories up from site-packages).
DEFAULT_DATA_PATH = Path("data/draws.csv")

_DATE_FORMAT = "%a, %b %d, %Y"


@dataclass(frozen=True)
class Draw:
    """A single historical drawing."""

    date: date_type
    whites: tuple[int, ...]  # always sorted ascending, length WHITE_BALL_COUNT
    powerball: int

    def __post_init__(self) -> None:
        if len(self.whites) != WHITE_BALL_COUNT:
            raise ValueError(f"expected {WHITE_BALL_COUNT} white balls, got {len(self.whites)}")
        if len(set(self.whites)) != WHITE_BALL_COUNT:
            raise ValueError(f"white balls must be unique: {self.whites}")
        for n in self.whites:
            if not WHITE_MIN <= n <= WHITE_MAX:
                raise ValueError(f"white ball {n} out of range [{WHITE_MIN}, {WHITE_MAX}]")
        if not POWERBALL_MIN <= self.powerball <= POWERBALL_MAX:
            raise ValueError(
                f"powerball {self.powerball} out of range [{POWERBALL_MIN}, {POWERBALL_MAX}]"
            )


def load_draws(path: str | Path = DEFAULT_DATA_PATH) -> list[Draw]:
    """Parse a draws CSV into a list of `Draw`, oldest-to-newest order preserved."""
    path = Path(path)
    draws: list[Draw] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header row; names aren't checked, just skipped
        for row in reader:
            if not row:
                continue
            date_str, *numbers = row
            whites = tuple(sorted(int(n) for n in numbers[:5]))
            draws.append(
                Draw(
                    date=datetime.strptime(date_str, _DATE_FORMAT).date(),
                    whites=whites,
                    powerball=int(numbers[5]),
                )
            )
    return draws
