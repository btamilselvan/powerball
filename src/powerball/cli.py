"""Command-line entry point: `powerball pick`, `powerball stats`, `powerball insights`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from powerball.data import DEFAULT_DATA_PATH, load_draws, recent_draws
from powerball.insights import build_stats_digest, generate_commentary_pick, generate_insights
from powerball.llm import (
    DEFAULT_PROVIDER,
    PROVIDER_ENV_VAR,
    SUPPORTED_PROVIDERS,
    LLMUnavailableError,
)
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


def cmd_insights(args: argparse.Namespace) -> None:
    draws = load_draws(args.data)
    if args.years is not None or args.months is not None:
        draws = recent_draws(draws, years=args.years, months=args.months)
    digest = build_stats_digest(draws)

    print(
        f"Analyzing {digest['draw_count']} draws ({digest['date_range']['from']} to "
        f"{digest['date_range']['to']})\n"
    )

    try:
        insights = generate_insights(
            digest, provider=args.provider, model=args.model, host=args.host
        )
    except LLMUnavailableError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    print(insights.summary)
    print()
    for note in insights.notable_patterns:
        print(f"- {note.headline}: {note.detail}")
    print(f"\n{insights.disclaimer}")

    if args.pick:
        try:
            pick = generate_commentary_pick(
                draws, digest, provider=args.provider, model=args.model, host=args.host
            )
        except LLMUnavailableError as e:
            print(f"error: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        whites = " ".join(f"{n:02d}" for n in pick.whites)
        print(f"\nAI commentary pick: {whites}  PB {pick.powerball:02d}")
        print(f"Rationale: {pick.rationale}")
        print(pick.disclaimer)


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

    insights = subparsers.add_parser(
        "insights",
        help="LLM-generated commentary on historical patterns (novelty feature, "
        "not a predictive edge)",
    )
    insights.add_argument("--data", default=DEFAULT_DATA_PATH, help="path to draws CSV")
    window = insights.add_mutually_exclusive_group()
    window.add_argument(
        "--years", type=int, default=None, help="only analyze the last N years (default: all)"
    )
    window.add_argument(
        "--months", type=int, default=None, help="only analyze the last N months (default: all)"
    )
    insights.add_argument(
        "--pick", action="store_true", help="also generate a caveated AI commentary pick"
    )
    insights.add_argument(
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        default=None,
        help=f"LLM backend (default: ${PROVIDER_ENV_VAR} or {DEFAULT_PROVIDER!r})",
    )
    insights.add_argument(
        "--model",
        default=None,
        help="model name/tag for the selected provider "
        "(default: that provider's own env var and built-in default)",
    )
    insights.add_argument(
        "--host",
        default=None,
        help="server URL for the selected provider "
        "(default: that provider's own env var and built-in default)",
    )
    insights.set_defaults(func=cmd_insights)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
