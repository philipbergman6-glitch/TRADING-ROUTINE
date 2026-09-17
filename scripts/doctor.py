#!/usr/bin/env python3
"""Read-only project health report. --broker additionally checks live paper coverage.

No orders, cancellations, repairs, emails or credential values are emitted.
Exit 0 means requested checks passed; 4 means an issue or unavailable state.
Offline success never implies live protection is verified.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import build_dashboard_data as dashboard
from scripts.validate_order import adapter
from risk_engine.reconciliation import reconcile_protection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", action="store_true", help="read current paper positions and orders")
    args = parser.parse_args()
    report = {"mode": "paper", "broker_verified": False, "issues": [], "checks": {}}
    try:
        snaps = dashboard.parse_trade_log(dashboard.TRADE_LOG.read_text())
        weeks = dashboard.parse_weekly_review(dashboard.WEEKLY_REVIEW.read_text())
        generated = dashboard.emit(snaps, weeks)
        report["checks"]["last_log"] = snaps[-1]["d"]
        report["checks"]["dashboard_current"] = dashboard.OUT.read_text() == generated
        if not report["checks"]["dashboard_current"]:
            report["issues"].append("dashboard requires regeneration")
        report["checks"]["ledger_configured"] = bool(os.environ.get("DATABASE_URL"))
        if report["checks"]["ledger_configured"] and importlib.util.find_spec("psycopg") is None:
            report["issues"].append("ledger configured but psycopg unavailable")
        if args.broker:
            coverage = reconcile_protection(adapter("positions"), adapter("orders", "open"),
                                            datetime.now(timezone.utc))
            report["coverage"] = coverage
            report["broker_verified"] = coverage["ok"]
            report["issues"].extend(coverage["issues"])
    except SystemExit as exc:
        report["issues"].append(f"broker state unavailable (exit {exc.code})")
    except (ValueError, TypeError, KeyError, OSError, dashboard.ParseError) as exc:
        report["issues"].append(str(exc))
    report["ok"] = not report["issues"]
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
