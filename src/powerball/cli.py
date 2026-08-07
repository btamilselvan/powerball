"""Command-line entry point: `powerball pick` and `powerball stats`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from powerball.data import DEFAULT_DATA_PATH, load_draws
from powerball.picker import quick_pick, smart_pick
from powerball.stats import cold_numbers, hot_numbers, powerball_frequency, white_ball_frequency


def _format_draw(draw) -> str:
    whites = " ".join(f"{n:02d}" for n in draw.whites)
    return f"{whites}  PB {draw.powerball:02d}"


def cmd_pick(args: argparse.Namespace) -> None:
    if args.strategy == "quick":
        for _ in range(args.count):
            print(_format_draw(quick_pick()))
    else:
        draws = load_draws(args.data)
        for _ in range(args.count):
            print(_format_draw(smart_pick(draws)))


def cmd_stats(args: argparse.Namespace) -> None:
    draws = load_draws(args.data)
    print(f"Loaded {len(draws)} draws from {args.data}\n")

    print(f"Hot white balls (top {args.top}):")
    for n, count in hot_numbers(white_ball_frequency(draws), args.top):
        print(f"  {n:2d}  x{count}")

    print(f"\nCold white balls (bottom {args.top}):")
    for n, count in cold_numbers(white_ball_frequency(draws), args.top):
        print(f"  {n:2d}  x{count}")

    print(f"\nHot powerballs (top {args.top}):")
    for n, count in hot_numbers(powerball_frequency(draws), args.top):
        print(f"  {n:2d}  x{count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerball", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pick = subparsers.add_parser("pick", help="generate ticket picks")
    pick.add_argument("--strategy", choices=["quick", "smart"], default="quick")
    pick.add_argument("--count", type=int, default=1)
    pick.add_argument("--data", default=DEFAULT_DATA_PATH, help="path to draws CSV")
    pick.set_defaults(func=cmd_pick)

    stats = subparsers.add_parser("stats", help="show hot/cold number frequency")
    stats.add_argument("--data", default=DEFAULT_DATA_PATH, help="path to draws CSV")
    stats.add_argument("--top", type=int, default=10)
    stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
