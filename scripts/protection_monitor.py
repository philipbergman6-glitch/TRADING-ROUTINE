#!/usr/bin/env python3
"""Independent protection monitor: runs without Claude and without the ledger.

    python3 scripts/protection_monitor.py            # plan and act
    python3 scripts/protection_monitor.py --dry-run  # plan only, no mutation
    python3 scripts/protection_monitor.py --email    # also email when anything is wrong or was done

Reads positions and open orders, verifies coverage (risk_engine.reconciliation),
then performs every due protection action through scripts/replace_stop.py:
renew expiring GTC stops, convert leftover fixed OTO legs to the trailing stop,
tighten trails per the active version's ladder. Standing conditions the rules
say to leave alone (a fixed stop inside the 3% minimum) are reported, not
touched. Nothing here opens positions or closes them.

The ledger is deliberately not consulted: the Sep 8-16 outage showed protection
must not depend on an optional component. Version comes from STRATEGY_VERSION.

Exit codes (JSON report always on stdout):
    0  all positions covered, every due action done (or nothing due)
    4  broker state unavailable; nothing changed
    5  coverage issue or a held action that leaves protection short of the rule
    7  an action failed but the prior level was restored
    8  INCIDENT: a position may be unprotected; rerun immediately
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import params_from_env  # noqa: E402
from risk_engine.monitor import plan_protection  # noqa: E402
from scripts.replace_stop import EXIT_OK, EXIT_RESTORED, EXIT_UNPROTECTED, Outcome, replace_stop  # noqa: E402
from scripts.validate_order import EXIT_NO_STATE, adapter  # noqa: E402

EMAIL = Path(__file__).resolve().parent / "email.sh"
EXIT_ISSUES = 5
MAX_RERUNS = 3


def execute(plan, replace=replace_stop, reruns=MAX_RERUNS) -> list[dict]:
    """Run each planned action; an UNPROTECTED outcome is retried in place."""
    results = []
    for action in plan.actions:
        outcome = None
        for _ in range(reruns):
            try:
                replace(action.order_id, trail_percent=action.trail_percent, stop_price=action.stop_price)
            except Outcome as got:
                outcome = got
            if outcome is not None and outcome.code != EXIT_UNPROTECTED:
                break
        results.append({**action.as_dict(), "exit": outcome.code if outcome else None,
                        "state": outcome.state if outcome else "no_outcome",
                        **({k: v for k, v in outcome.detail.items() if k != "order"} if outcome else {})})
    return results


def worst_exit(plan, results) -> int:
    codes = [r["exit"] for r in results]
    if any(c is None or c == EXIT_UNPROTECTED for c in codes):
        return EXIT_UNPROTECTED
    if any(c == EXIT_RESTORED for c in codes):
        return EXIT_RESTORED
    if plan.issues or any(c != EXIT_OK for c in codes):
        return EXIT_ISSUES
    return 0


def notify(report: dict) -> None:
    lines = [f"protection monitor {report['observed_at']} exit {report['exit']}"]
    lines += [f"ISSUE {i}" for i in report["coverage"].get("issues", [])]
    lines += [f"{r['kind']} {r['symbol']} -> {r['state']}" for r in report["results"]]
    lines += [f"HOLD {h}" for h in report["holds"]]
    lines += [f"STANDING {s}" for s in report["standing"]]
    subprocess.run(["bash", str(EMAIL), "\n".join(lines)], check=False, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="plan only; no broker mutation")
    parser.add_argument("--email", action="store_true", help="send the report when exit != 0 or an action ran")
    args = parser.parse_args()
    params = params_from_env(os.environ)
    now = datetime.now(timezone.utc)
    try:
        positions = adapter("positions")
        orders = adapter("orders", "open")
        plan = plan_protection(positions, orders, now, params)
    except SystemExit as exc:
        print(json.dumps({"exit": EXIT_NO_STATE, "state": "broker_state_unavailable", "adapter_exit": exc.code}))
        return EXIT_NO_STATE
    except (ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"exit": EXIT_NO_STATE, "state": "unreadable_broker_state", "error": str(exc)}))
        return EXIT_NO_STATE
    results = [] if args.dry_run else execute(plan)
    code = worst_exit(plan, results) if not args.dry_run else (EXIT_ISSUES if plan.issues else 0)
    report = {"exit": code, "dry_run": args.dry_run, "strategy_version": params.name,
              "observed_at": now.isoformat(), "results": results, **plan.as_dict()}
    print(json.dumps(report, indent=2, default=str))
    if args.email and (code != 0 or results):
        notify(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
