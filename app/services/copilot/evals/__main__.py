"""Run the copilot eval suite against a real workspace (costs LLM tokens).

    python -m app.services.copilot.evals --org <uuid> --workspace <uuid> --user <uuid> \\
        [--var evaluation_id=<uuid>] [--case activity_this_week] [--out report.json] [--min-pass-rate 0.9]

Exits non-zero when the pass rate is below --min-pass-rate, so it can gate a
release or a model change.
"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from app.services.copilot.evals.harness import run_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True, type=UUID)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--user", required=True, type=UUID)
    parser.add_argument("--var", action="append", default=[], help="name=value for case placeholders")
    parser.add_argument("--case", action="append", default=[], help="only run these case ids")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--out")
    parser.add_argument("--min-pass-rate", type=float, default=0.0)
    args = parser.parse_args(argv)

    variables = dict(v.split("=", 1) for v in args.var)
    report = run_cases(
        organization_id=args.org,
        workspace_id=args.workspace,
        user_id=args.user,
        variables=variables,
        only=set(args.case) or None,
        timezone_name=args.timezone,
    )
    for r in report["results"]:
        mark = "SKIP" if r["skipped"] else ("PASS" if r["passed"] else "FAIL")
        print(f"{mark}  {r['id']:<36} tools={r['tools']}")
        for failure in r["failures"]:
            print(f"        - {failure}")
        if r["skipped"]:
            print(f"        - {r['skipped']}")
    print(f"\npass rate {report['pass_rate']} ({report['passed']}/{report['ran']}), "
          f"p50 {report['p50_latency_ms']} ms, p95 {report['p95_latency_ms']} ms, {report['total_tokens']} tokens")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 0 if (report["pass_rate"] or 0) >= args.min_pass_rate else 1


if __name__ == "__main__":
    sys.exit(main())
