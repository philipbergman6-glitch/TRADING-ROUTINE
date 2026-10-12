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
must not depend on an optional component.

Version binding (ADR 0011): the plan uses the approved version named by
docs/rulebook-pins.json. When the run is not bound to it (STRATEGY_VERSION
missing, malformed or different; rulebook marker or hash off), every action
still goes to replace_stop, which refuses all of them except restoration of a
naked position after an earlier run's cancel; the run exits 6 and always
alerts. Pins that name no approved version leave nothing to plan with:
coverage is still verified and reported, no action runs, exit 6.

With --email the report is sent through scripts/email.sh, which verifies
delivery with Resend; a lost alert must fail the job (ADR 0007), so:

Exit codes (JSON report always on stdout):
    0  all positions covered, every due action done (or nothing due)
    4  broker state unavailable; nothing changed
    5  coverage issue or a held action that leaves protection short of the rule
    6  not bound to the approved strategy version: maintenance refused (replaces 0 or 5)
    7  an action failed but the prior level was restored
    8  INCIDENT: a position may be unprotected; rerun immediately
    9  the alert could not be delivered (replaces 0, 5 or 6; 7 and 8 keep their code)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.monitor import Plan, plan_protection  # noqa: E402
from risk_engine.reconciliation import reconcile_protection  # noqa: E402
from scripts.replace_stop import EXIT_OK, EXIT_RESTORED, EXIT_UNPROTECTED, Outcome, replace_stop  # noqa: E402
from scripts.strategy_version import VersionBindingError, bind  # noqa: E402
from scripts.validate_order import EXIT_NO_STATE, adapter  # noqa: E402

EMAIL = Path(__file__).resolve().parent / "email.sh"
EXIT_ISSUES = 5
EXIT_VERSION_BINDING = 6
EXIT_ALERT_FAILED = 9
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


def notify(report: dict, run=subprocess.run) -> bool:
    """Email the report; True only when scripts/email.sh verified delivery."""
    lines = [f"protection monitor {report['observed_at']} exit {report['exit']}"]
    binding = report.get("version_binding") or {}
    if binding.get("error"):
        lines.append(f"VERSION BINDING FAILED (approved {binding.get('approved')}): {binding['error']}")
    lines += [f"ISSUE {i}" for i in report["coverage"].get("issues", [])]
    lines += [f"{r['kind']} {r['symbol']} -> {r['state']}" for r in report["results"]]
    lines += [f"HOLD {h}" for h in report["holds"]]
    lines += [f"STANDING {s}" for s in report["standing"]]
    try:
        return run(["bash", str(EMAIL), "\n".join(lines)], check=False, timeout=120).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def exit_code(code: int, alert_delivered: bool | None) -> int:
    """A lost alert fails the job. It replaces a clean or coverage-issue code so
    the failure is named; a broker-state outcome (7, 8) is kept as the more
    urgent signal and the report still records alert_delivered."""
    if alert_delivered is False and code in (0, EXIT_ISSUES, EXIT_VERSION_BINDING):
        return EXIT_ALERT_FAILED
    return code


def run_monitor(now, *, dry_run=False, email=False, read=adapter, replace=replace_stop, send=notify,
                environ=None) -> dict:
    """One monitor pass; returns the report (its "exit" is the process exit code)."""
    try:
        binding = bind(os.environ if environ is None else environ)
        version = binding.as_dict()
    except VersionBindingError as exc:
        binding, version = None, {"approved": None, "engine": None, "error": str(exc)}
    try:
        positions = read("positions")
        orders = read("orders", "open")
        plan = (plan_protection(positions, orders, now, binding.params) if binding
                else Plan(coverage=reconcile_protection(positions, orders, now)))
    except SystemExit as exc:
        return {"exit": EXIT_NO_STATE, "state": "broker_state_unavailable", "adapter_exit": exc.code,
                "version_binding": version}
    except (ValueError, TypeError, KeyError) as exc:
        return {"exit": EXIT_NO_STATE, "state": "unreadable_broker_state", "error": str(exc),
                "version_binding": version}
    results = [] if dry_run else execute(plan, replace=partial(replace, binding=binding))
    code = worst_exit(plan, results) if not dry_run else (EXIT_ISSUES if plan.issues else 0)
    if version["error"] and code in (0, EXIT_ISSUES):
        code = EXIT_VERSION_BINDING
    report = {"exit": code, "dry_run": dry_run, "strategy_version": version["engine"], "version_binding": version,
              "observed_at": now.isoformat(), "results": results, **plan.as_dict()}
    alert_delivered = send(report) if email and (code != 0 or results) else None
    report["alert_delivered"] = alert_delivered
    report["exit"] = exit_code(code, alert_delivered)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="plan only; no broker mutation")
    parser.add_argument("--email", action="store_true", help="send the report when exit != 0 or an action ran")
    args = parser.parse_args()
    report = run_monitor(datetime.now(timezone.utc), dry_run=args.dry_run, email=args.email)
    print(json.dumps(report, indent=2, default=str))
    return report["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
