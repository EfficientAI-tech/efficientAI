"""Command line: ``efficientai simulate --suite ... --fail-under 0.8``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Optional

from efficientai_sdk import EfficientAI, EfficientAIError
from efficientai_sdk.simulations.api import ResultBatch


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run a suite and return a process exit code.

    ``0`` when the pass rate is at least ``--fail-under`` and no result errored.
    ``1`` when the suite finishes below that bar.
    ``2`` when the arguments or the API call fail.
    """
    parser = argparse.ArgumentParser(prog="efficientai")
    sub = parser.add_subparsers(dest="command", required=True)
    simulate = sub.add_parser("simulate", help="Run a suite and fail under a pass rate")
    simulate.add_argument("--suite", required=True, help="Evaluator suite id")
    simulate.add_argument(
        "--fail-under",
        required=True,
        type=float,
        help="Exit 1 when the pass rate is below this value (0 to 1)",
    )
    simulate.add_argument(
        "--runs-per-combination",
        type=int,
        default=None,
        help="Repeat each scenario/persona pair this many times (default: the suite's saved count)",
    )
    simulate.add_argument(
        "--to-number",
        default=None,
        help="Recipient number for phone or messaging suites",
    )
    simulate.add_argument(
        "--from-number",
        default=None,
        help="Caller number when the suite places an outbound call",
    )
    simulate.add_argument(
        "--timeout", type=float, default=1800, help="Seconds to wait (default 1800)"
    )
    simulate.add_argument("--interval", type=float, default=2.0, help="Seconds between polls")

    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2

    if args.command != "simulate":
        parser.print_help(sys.stderr)
        return 2
    if not 0.0 <= args.fail_under <= 1.0:
        print("--fail-under must be between 0 and 1", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("--timeout must be greater than 0", file=sys.stderr)
        return 2

    try:
        with EfficientAI() as client:
            batch = client.suites.run(
                args.suite,
                runs_per_combination=args.runs_per_combination,
                to_number=args.to_number,
                from_number=args.from_number,
            )
            finished = batch.wait(timeout=args.timeout, interval=args.interval)
    except EfficientAIError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _print_summary(finished)
    if finished.meets(args.fail_under):
        return 0
    return 1


def _print_summary(batch: ResultBatch) -> None:
    total = len(batch.results)
    ok = sum(1 for result in batch.results if result.succeeded)
    print(f"pass rate {batch.pass_rate:.0%} ({ok}/{total})")


def entry() -> None:
    """Setuptools entry point. ``main`` returns the code so tests can call it."""
    raise SystemExit(main())


if __name__ == "__main__":
    entry()
