"""Command line: python -m xauusd_council run | demo | fetch. See xauusd_council/README.md."""
import argparse
import os
import sys
import textwrap
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from . import data as bars_from
from .backtest import Costs
from .council import Council
from .market import Market, TIMEFRAMES
from .report import section, write

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def printer(rounds: int, width: int = 100):
    """Prints the conversation as it happens, with a heading for each stage."""
    state = {"heading": None}

    def show(message):
        heading = section(message.to_dict(), rounds)
        if heading != state["heading"]:
            print(f"\n── {heading} " + "─" * max(0, width - len(heading) - 4))
            state["heading"] = heading
        who = message.author + (f" → {message.to}" if message.to else "") + (f" [{message.candidate}]" if message.candidate else "")
        tag = "" if message.brain in ("scripted", "code") else f" ({message.brain})"
        print(textwrap.fill(f"{who}{tag}: {message.text}", width=width, subsequent_indent="    "))
    return show


def choose_factory(brain: str):
    if brain == "scripted":
        return None, "scripted"
    from backend.llm import claude_enabled
    if brain == "auto" and not claude_enabled("council"):
        return None, "scripted"
    if brain == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("--brain claude needs ANTHROPIC_API_KEY (in .env or the environment)")
    from .claude_bots import factory
    return factory(), "claude"


def convene(bars, args, label: str) -> int:
    market = Market(bars_from.resample(bars, args.timeframe), args.timeframe)
    factory, brain = choose_factory(args.brain)
    listener = None if args.quiet else printer(args.rounds)
    council = Council(market, n_bots=args.bots, rounds=args.rounds, holdout=args.holdout,
                      costs=Costs(args.spread, args.slippage), factory=factory, quick=args.quick, listener=listener)
    print(f"{label}: {len(council.bots)} bots ({brain}), {args.rounds} debate rounds.")
    started = time.monotonic()
    result = council.run()
    result["source"] = label
    folder = Path(args.out) if args.out else PROJECT_ROOT / "data" / "council" / datetime.now().strftime("%Y%m%d-%H%M%S")
    transcript, record = write(result, folder)
    print(f"\nDone in {time.monotonic() - started:.0f}s. "
          + (f"Agreed rule: {result['short']}" if result["passed"] else "No rule held up on the holdout."))
    print(f"Transcript: {transcript}\nRecord:     {record}")
    return 0


def main(argv=None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(prog="python -m xauusd_council",
                                     description="Bots that debate and agree a XAUUSD rule for the London and New York sessions.")
    commands = parser.add_subparsers(dest="command", required=True)

    def council_options(command):
        command.add_argument("--bots", type=int, default=5, help="how many bots sit on the council (2-20, default 5)")
        command.add_argument("--rounds", type=int, default=2, help="debate rounds before the vote (default 2)")
        command.add_argument("--holdout", type=float, default=0.3, help="share of the latest days kept hidden (default 0.3)")
        command.add_argument("--timeframe", type=int, default=5, choices=TIMEFRAMES, help="bar size in minutes (default 5)")
        command.add_argument("--spread", type=float, default=0.30, help="USD per ounce per trade (default 0.30)")
        command.add_argument("--slippage", type=float, default=0.10, help="USD per ounce on breakouts and stops (default 0.10)")
        command.add_argument("--brain", choices=("auto", "scripted", "claude"), default="auto",
                             help="auto uses Claude when ANTHROPIC_API_KEY is set (default)")
        command.add_argument("--quick", action="store_true", help="search smaller grids (faster, for trying it out)")
        command.add_argument("--out", help="folder for transcript.md and result.json (default data/council/<time>)")
        command.add_argument("--quiet", action="store_true", help="don't print the conversation")

    run = commands.add_parser("run", help="convene the council on your XAUUSD data (CSV)")
    run.add_argument("--data", required=True, help="CSV of XAUUSD bars: MetaTrader, Dukascopy, HistData or ISO times")
    run.add_argument("--tz", default="UTC", help="time zone of the CSV's clock, e.g. UTC or Europe/Athens (default UTC)")
    council_options(run)

    demo = commands.add_parser("demo", help="convene the council on synthetic data (the result means nothing for real trading)")
    demo.add_argument("--years", type=float, default=3, help="years of synthetic data (default 3)")
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--edge", type=float, default=0.0, help="plant a breakout pattern of this strength, e.g. 0.1")
    council_options(demo)

    fetch = commands.add_parser("fetch", help="download free XAUUSD one-minute candles from Dukascopy")
    fetch.add_argument("--start", required=True, type=date.fromisoformat, help="first day, YYYY-MM-DD")
    fetch.add_argument("--end", type=date.fromisoformat, default=date.today(), help="last day (default today)")
    fetch.add_argument("--out", default=str(PROJECT_ROOT / "data" / "xauusd_m1.csv"))

    journal = commands.add_parser("journal", help="log what the frozen rule does on days after its holdout")
    journal.add_argument("--rule", required=True, help="result.json of the council run whose rule you froze")
    journal.add_argument("--since", help="first day to log (default: the day after that run's holdout ends)")
    journal.add_argument("--data", default=str(PROJECT_ROOT / "data" / "xauusd_m1.csv"))
    journal.add_argument("--out", default=str(PROJECT_ROOT / "data" / "journal.csv"))
    journal.add_argument("--spread", type=float, default=0.30)
    journal.add_argument("--slippage", type=float, default=0.10)

    args = parser.parse_args(argv)
    try:
        if args.command == "journal":
            from .journal import update
            added, total, added_r = update(args.rule, args.data, args.out, args.since, args.spread, args.slippage)
            print(f"Added {added} closed sessions ({added_r:+.2f}R). The journal now has {total}: {args.out}")
            return 0
        if args.command == "fetch":
            from .dukascopy import fetch as download
            print(f"Downloading XAUUSD {args.start} to {args.end} from Dukascopy...")
            path = download(args.start, args.end, Path(args.out))
            print(f"Saved {path}. Next: python -m xauusd_council run --data {path}")
            return 0
        if args.command == "demo":
            bars = bars_from.synthetic(days=int(args.years * 365), seed=args.seed, edge=args.edge)
            planted = f", with a planted breakout pattern of strength {args.edge:g}" if args.edge else ""
            return convene(bars, args, f"Synthetic gold, {args.years:g} years{planted} (not real prices)")
        bars = bars_from.load_csv(args.data, tz=args.tz)
        return convene(bars, args, f"{Path(args.data).name}")
    except FileNotFoundError as error:
        print(f"error: {error.filename} not found. Run fetch first, or check the path.", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
