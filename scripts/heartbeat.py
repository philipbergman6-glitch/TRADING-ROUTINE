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
     market-open commits "market-open trades <date>" or "market-open no-trade
     <date>" every session, so "did not run" and "nothing to do" differ.
  3. GitHub Actions runs (gh api)  — protection-monitor must have succeeded at
     least once today and, per the service level in ADR 0007, the newest
     successful check must never have been older than MAX_DELAY (90 min)
     while the exchange was open (scripts/protection_sla.py measures it from
     the runs' completion times); dashboard-data and tests must not have
     failed today.

The alert email is delivery-verified by scripts/email.sh; if it cannot be
sent the job fails with exit 9 so the workflow itself becomes the signal.

Exit codes (JSON report on stdout):
    0  everything expected happened, or not a trading day
    4  a source was unavailable; nothing assessed
    5  at least one expectation missed (emailed unless --no-email)
    9  expectations missed AND the alert could not be delivered
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
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.protection_sla import MAX_DELAY, session_window, staleness_breaches  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EMAIL = ROOT / "scripts" / "email.sh"
EXIT_OK, EXIT_NO_STATE, EXIT_ISSUES, EXIT_ALERT_FAILED = 0, 4, 5, 9

# Routine -> subject prefix of the commit it pushes. Keep in sync with routines/*.md.
# market-open's subject is "market-open trades <date>" or "market-open no-trade <date>".
EXPECTED_DAILY = {
    "pre-market": "pre-market research",
    "market-open": "market-open",
    "midday": "midday scan",
    "eod": "EOD snapshot",
}
EXPECTED_LABEL = {"market-open": "market-open <trades|no-trade>"}
EXPECTED_FRIDAY = {"weekly-review": "weekly review"}
MONITOR = "protection-monitor"
MUST_NOT_FAIL = ("dashboard-data", "tests")
EXCHANGE_TZ = ZoneInfo("America/New_York")


def assessment_date(now: datetime) -> date:
    """The session day to assess. GitHub can fire the 22:45Z cron hours late; the
    exchange's date stays on the session until 04:00Z, the UTC date does not."""
    return now.astimezone(EXCHANGE_TZ).date()


def _completed_at(run: dict) -> datetime:
    raw = run.get("updated_at")
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"successful {MONITOR} run without updated_at: {run!r}")
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"updated_at is not timezone-aware: {raw!r}")
    return stamp.astimezone(timezone.utc)


def protection_check_status(today: date, monitor_ok: list[dict], now: datetime) -> dict:
    """Measure the service level: when, during today's session, was the newest
    successful protection check older than MAX_DELAY? Evidence is the
    completion time of every successful protection-monitor run today."""
    checks = sorted(_completed_at(r) for r in monitor_ok)
    breaches = staleness_breaches(checks, today, now)
    return {"level_minutes": int(MAX_DELAY.total_seconds() // 60),
            "checks": [c.isoformat() for c in checks],
            "stale_minutes": sum(b["minutes"] for b in breaches),
            "breaches": breaches}


def _breach_issue(today: date, status: dict, now: datetime) -> str:
    open_, close = session_window(today)
    session_minutes = int((min(close, now) - open_).total_seconds() // 60)
    windows = ", ".join(
        f"{b['from'][11:16]}-{b['to'][11:16]}Z ({b['minutes']} min)" for b in status["breaches"])
    return (f"protection check: stale {status['stale_minutes']} min of the {session_minutes}-min session, "
            f"over the {status['level_minutes']}-min level: {windows}")


def assess(today: date, trading_day: bool, commit_subjects: list[str], runs: list[dict], now: datetime) -> dict:
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
            issues.append(f"routine {routine}: no commit '{EXPECTED_LABEL.get(routine, prefix)} {stamp}' on main")

    by_workflow: dict[str, list[dict]] = {}
    for r in runs:
        by_workflow.setdefault(str(r.get("name")), []).append(r)
    monitor_ok = [r for r in by_workflow.get(MONITOR, []) if r.get("conclusion") == "success"]
    if not monitor_ok:
        seen = len(by_workflow.get(MONITOR, []))
        issues.append(f"workflow {MONITOR}: no successful run today ({seen} run(s) seen)")
    protection = protection_check_status(today, monitor_ok, now)
    if monitor_ok and protection["breaches"]:
        issues.append(_breach_issue(today, protection, now))
    for name in MUST_NOT_FAIL:
        failed = [r for r in by_workflow.get(name, []) if r.get("conclusion") == "failure"]
        if failed:
            issues.append(f"workflow {name}: {len(failed)} failed run(s) today, latest {failed[0].get('url', '')}")
    return {"date": stamp, "trading_day": True, "expected_routines": sorted(expected),
            "commits_seen": commit_subjects, "protection_check": protection, "issues": issues,
            "exit": EXIT_ISSUES if issues else EXIT_OK}


def send_alert(body: str, run=subprocess.run) -> bool:
    """Send through scripts/email.sh, which verifies delivery; True only when it did."""
    try:
        return run(["bash", str(EMAIL), body], check=False, timeout=120).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def exit_code(report_exit: int, alert_delivered: bool | None) -> int:
    """An undeliverable alert is the worse failure: nobody would learn about the miss."""
    return EXIT_ALERT_FAILED if alert_delivered is False else report_exit


# --- sources -----------------------------------------------------------------

def resolve_credentials(environ) -> tuple[str, str]:
    """Same rules as scripts/alpaca.sh: one profile, one key pair, never both."""
    profile = environ.get("ALPACA_PROFILE") or "production"
    if profile not in ("production", "drill"):
        raise RuntimeError(f"unknown ALPACA_PROFILE {profile!r} (production|drill)")
    prod = (environ.get("ALPACA_API_KEY"), environ.get("ALPACA_SECRET_KEY"))
    drill = (environ.get("DRILL_ALPACA_API_KEY"), environ.get("DRILL_ALPACA_SECRET_KEY"))
    if any(prod) and any(drill):
        raise RuntimeError("both ALPACA_* and DRILL_ALPACA_* key pairs are present; refusing")
    key, sec = drill if profile == "drill" else prod
    if not key or not sec:
        raise RuntimeError(f"ALPACA credentials for profile {profile} unset")
    return key, sec


def trading_day_from_alpaca(today: date, environ=os.environ) -> bool:
    endpoint = environ.get("ALPACA_ENDPOINT", "")
    if not endpoint.startswith("https://paper-api.alpaca.markets"):
        raise RuntimeError("ALPACA_ENDPOINT is not the paper endpoint; refusing")
    key, sec = resolve_credentials(environ)
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
         "--jq", ".workflow_runs[] | {name, conclusion, status, url: .html_url, created_at, updated_at}"],
        capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--date", help="YYYY-MM-DD to assess; default today in New York")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    today = date.fromisoformat(args.date) if args.date else assessment_date(now)
    repo = os.environ.get("GITHUB_REPOSITORY") or "philipbergman6-glitch/TRADING-ROUTINE"
    try:
        trading = trading_day_from_alpaca(today)
        subjects = commit_subjects_since(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
        runs = runs_today(repo, today)
    except (RuntimeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(json.dumps({"date": str(today), "exit": EXIT_NO_STATE, "error": str(exc)}))
        return EXIT_NO_STATE
    report = assess(today, trading, subjects, runs, now)
    alert_delivered = None
    if report["issues"] and not args.no_email:
        body = f"HEARTBEAT {today}: {len(report['issues'])} missed expectation(s)\n" + "\n".join(
            f"- {i}" for i in report["issues"])
        alert_delivered = send_alert(body)
    report["alert_delivered"] = alert_delivered
    report["exit"] = exit_code(report["exit"], alert_delivered)
    print(json.dumps(report, indent=2))
    return report["exit"]


if __name__ == "__main__":
    sys.exit(main())
