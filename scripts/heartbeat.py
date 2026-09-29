#!/usr/bin/env python3
"""Daily liveness check: did every expected routine and workflow run today?

    python3 scripts/heartbeat.py            # report; exit 5 and email when something is missing
    python3 scripts/heartbeat.py --no-email

Closes the "merged but never observed running" gap (PROJECT-STATUS, audit
AUD:39): PR #65 blocked orders for six days and PR #83's monitor failed for
eight before anyone looked. This script is the looker. It reads three sources
and never touches the broker beyond the exchange calendar:

  1. Alpaca /v2/calendar          — is today a trading day (holidays excluded)?
  2. git log on the checked-out main — one commit per routine per trading day,
     matched by the subject prefix each routine uses (routines/*.md STEP 7/8).
     market-open is exempt: on a no-trade day it has nothing to commit.
  3. GitHub Actions runs (gh api)  — protection-monitor must have succeeded at
     least once today; dashboard-data and tests must not have failed today.

Exit codes (JSON report on stdout):
    0  everything expected happened, or not a trading day
    4  a source was unavailable; nothing assessed
    5  at least one expectation missed (emailed unless --no-email)
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
EMAIL = ROOT / "scripts" / "email.sh"
EXIT_OK, EXIT_NO_STATE, EXIT_ISSUES = 0, 4, 5

# Routine -> subject prefix of the commit it pushes. Keep in sync with routines/*.md.
EXPECTED_DAILY = {
    "pre-market": "pre-market research",
    "midday": "midday scan",
    "eod": "EOD snapshot",
}
EXPECTED_FRIDAY = {"weekly-review": "weekly review"}
MONITOR = "protection-monitor"
MUST_NOT_FAIL = ("dashboard-data", "tests")


def assess(today: date, trading_day: bool, commit_subjects: list[str], runs: list[dict]) -> dict:
    """Pure: compare what happened today with what the schedule promises."""
    if not trading_day:
        return {"date": str(today), "trading_day": False, "issues": [], "exit": EXIT_OK}
    expected = dict(EXPECTED_DAILY)
    if today.weekday() == 4:
        expected.update(EXPECTED_FRIDAY)
    stamp = str(today)
    issues = []
    for routine, prefix in expected.items():
        if not any(s.startswith(prefix) and stamp in s for s in commit_subjects):
            issues.append(f"routine {routine}: no commit '{prefix} {stamp}' on main")

    by_workflow: dict[str, list[dict]] = {}
    for r in runs:
        by_workflow.setdefault(str(r.get("name")), []).append(r)
    monitor_ok = [r for r in by_workflow.get(MONITOR, []) if r.get("conclusion") == "success"]
    if not monitor_ok:
        seen = len(by_workflow.get(MONITOR, []))
        issues.append(f"workflow {MONITOR}: no successful run today ({seen} run(s) seen)")
    for name in MUST_NOT_FAIL:
        failed = [r for r in by_workflow.get(name, []) if r.get("conclusion") == "failure"]
        if failed:
            issues.append(f"workflow {name}: {len(failed)} failed run(s) today, latest {failed[0].get('url', '')}")
    return {"date": stamp, "trading_day": True, "expected_routines": sorted(expected),
            "commits_seen": commit_subjects, "issues": issues,
            "exit": EXIT_ISSUES if issues else EXIT_OK}


# --- sources -----------------------------------------------------------------

def trading_day_from_alpaca(today: date, environ=os.environ) -> bool:
    endpoint = environ.get("ALPACA_ENDPOINT", "")
    if not endpoint.startswith("https://paper-api.alpaca.markets"):
        raise RuntimeError("ALPACA_ENDPOINT is not the paper endpoint; refusing")
    key, sec = environ.get("ALPACA_API_KEY"), environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("ALPACA credentials unset")
    q = urllib.parse.urlencode({"start": str(today), "end": str(today)})
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/calendar?{q}",
                                 headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=20) as resp:
        days = json.loads(resp.read().decode("utf-8"))
    if not isinstance(days, list):
        raise RuntimeError("calendar response is not a list")
    return any(isinstance(d, dict) and d.get("date") == str(today) for d in days)


def commit_subjects_since(midnight_utc: datetime) -> list[str]:
    out = subprocess.run(["git", "log", f"--since={midnight_utc.isoformat()}", "--format=%s", "origin/main"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def runs_today(repo: str, today: date) -> list[dict]:
    out = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/actions/runs?created={today}&per_page=100",
         "--jq", ".workflow_runs[] | {name, conclusion, status, url: .html_url, created_at}"],
        capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--date", help="YYYY-MM-DD (UTC) to assess; default today")
    args = parser.parse_args()
    today = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    repo = os.environ.get("GITHUB_REPOSITORY") or "philipbergman6-glitch/TRADING-ROUTINE"
    try:
        trading = trading_day_from_alpaca(today)
        subjects = commit_subjects_since(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
        runs = runs_today(repo, today)
    except (RuntimeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(json.dumps({"date": str(today), "exit": EXIT_NO_STATE, "error": str(exc)}))
        return EXIT_NO_STATE
    report = assess(today, trading, subjects, runs)
    print(json.dumps(report, indent=2))
    if report["issues"] and not args.no_email:
        body = f"HEARTBEAT {today}: {len(report['issues'])} missed expectation(s)\n" + "\n".join(
            f"- {i}" for i in report["issues"])
        subprocess.run(["bash", str(EMAIL), body], check=False, timeout=60)
    return report["exit"]


if __name__ == "__main__":
    sys.exit(main())
