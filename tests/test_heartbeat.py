"""Heartbeat: every expected routine commit and workflow outcome for a trading day, nothing on holidays."""
from datetime import date, datetime, timedelta, timezone
import subprocess

import pytest

from scripts.heartbeat import EXIT_ALERT_FAILED, EXIT_ISSUES, EXIT_OK, assess, assessment_date, exit_code, send_alert

MON = date(2026, 9, 28)
FRI = date(2026, 9, 25)
GOOD_COMMITS = ["EOD snapshot 2026-09-28", "midday scan 2026-09-28", "market-open trades 2026-09-28",
                "pre-market research 2026-09-28", "dashboard data: 2026-09-28 [skip ci]"]
AFTER_CLOSE = datetime(2026, 9, 28, 22, 45, tzinfo=timezone.utc)


def monitor_runs(day, *hhmm_utc, conclusion="success"):
    return [{"name": "protection-monitor", "conclusion": conclusion,
             "updated_at": f"{day}T{h:02d}:{m:02d}:00Z"} for h, m in hhmm_utc]


# EDT session 13:30-20:00Z; a check every 30 minutes keeps every gap inside the level.
EVERY_30 = [(13, 30 + 30 * i) if i < 1 else (13 + (30 + 30 * i) // 60, (30 + 30 * i) % 60) for i in range(14)]
GOOD_RUNS = monitor_runs("2026-09-28", *EVERY_30) + [
    {"name": "dashboard-data", "conclusion": "success"},
    {"name": "tests", "conclusion": "success"}]


def test_full_trading_day_is_clean():
    r = assess(MON, True, GOOD_COMMITS, GOOD_RUNS, AFTER_CLOSE)
    assert r["exit"] == EXIT_OK and r["issues"] == []


def test_holiday_expects_nothing():
    r = assess(MON, False, [], [], AFTER_CLOSE)
    assert r["exit"] == EXIT_OK and r["trading_day"] is False


def test_missing_midday_and_eod_are_named():
    r = assess(MON, True, ["pre-market research 2026-09-28", "market-open no-trade 2026-09-28"], GOOD_RUNS, AFTER_CLOSE)
    assert r["exit"] == EXIT_ISSUES
    assert sorted(i.split(":")[0] for i in r["issues"]) == ["routine eod", "routine midday"]


def test_yesterdays_commit_does_not_count():
    stale = [s.replace("2026-09-28", "2026-09-25") for s in GOOD_COMMITS]
    r = assess(MON, True, stale, GOOD_RUNS, AFTER_CLOSE)
    assert len(r["issues"]) == 4


def test_market_open_must_leave_a_record_even_without_trades():
    # A no-trade session commits "market-open no-trade <date>"; silence is a miss.
    without = [s for s in GOOD_COMMITS if "market-open" not in s]
    assert assess(MON, True, without, GOOD_RUNS, AFTER_CLOSE)["issues"] == [
        "routine market-open: no commit 'market-open <trades|no-trade> 2026-09-28' on main"]
    assert assess(MON, True, without + ["market-open no-trade 2026-09-28"], GOOD_RUNS, AFTER_CLOSE)["issues"] == []


def test_friday_requires_weekly_review():
    commits = [s.replace("2026-09-28", "2026-09-25") for s in GOOD_COMMITS]
    runs = monitor_runs("2026-09-25", *EVERY_30) + GOOD_RUNS[-2:]
    fri_close = datetime(2026, 9, 25, 22, 45, tzinfo=timezone.utc)
    assert assess(FRI, True, commits, runs, fri_close)["issues"] == ["routine weekly-review: no commit 'weekly review 2026-09-25' on main"]
    assert assess(FRI, True, commits + ["weekly review 2026-09-25"], runs, fri_close)["issues"] == []


def test_monitor_needs_one_success_and_failures_of_others_are_flagged():
    runs = [{"name": "protection-monitor", "conclusion": "failure"},
            {"name": "protection-monitor", "conclusion": "failure"},
            {"name": "dashboard-data", "conclusion": "failure", "url": "u"},
            {"name": "tests", "conclusion": "success"}]
    issues = assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)["issues"]
    assert issues == ["workflow protection-monitor: no successful run today (2 run(s) seen)",
                      "workflow dashboard-data: 1 failed run(s) today, latest u"]
    runs[0]["conclusion"] = "success"
    runs[0]["updated_at"] = "2026-09-28T13:40:00Z"
    issues = assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)["issues"]
    assert issues[0].startswith("protection check: stale") and issues[1] == "workflow dashboard-data: 1 failed run(s) today, latest u"


def test_cron_delayed_past_utc_midnight_still_assesses_the_session_day():
    # 2026-09-30: the 22:45Z cron fired at 01:34Z and assessed a day that had not started.
    assert assessment_date(datetime(2026, 9, 30, 1, 34, tzinfo=timezone.utc)) == date(2026, 9, 29)
    assert assessment_date(datetime(2026, 9, 29, 22, 45, tzinfo=timezone.utc)) == date(2026, 9, 29)


def test_two_afternoon_checks_breach_the_level_and_name_the_windows():
    # The observed GitHub-cron day (research 0008): successes at 18:16Z and 22:30Z only.
    runs = monitor_runs("2026-09-28", (18, 16), (22, 30)) + GOOD_RUNS[-2:]
    r = assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)
    assert r["exit"] == EXIT_ISSUES
    # Stale from the open until the first check, and again from 19:46Z (18:16Z + 90 min) to the close.
    assert r["issues"] == ["protection check: stale 300 min of the 390-min session, over the 90-min level: "
                           "13:30-18:16Z (286 min), 19:46-20:00Z (14 min)"]
    assert r["protection_check"] == {"level_minutes": 90, "checks": ["2026-09-28T18:16:00+00:00", "2026-09-28T22:30:00+00:00"],
                                     "stale_minutes": 300,
                                     "breaches": [{"from": "2026-09-28T13:30:00+00:00", "to": "2026-09-28T18:16:00+00:00", "minutes": 286},
                                                  {"from": "2026-09-28T19:46:00+00:00", "to": "2026-09-28T20:00:00+00:00", "minutes": 14}]}


def test_successful_monitor_run_without_completion_time_is_rejected():
    runs = [{"name": "protection-monitor", "conclusion": "success"}] + GOOD_RUNS[-2:]
    with pytest.raises(ValueError, match="updated_at"):
        assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)


def test_alert_failure_fails_the_job_even_when_only_issues_exist():
    def refused(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 2)

    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    assert send_alert("x", run=refused) is False
    assert send_alert("x", run=hung) is False
    assert send_alert("x", run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0)) is True
    assert exit_code(EXIT_ISSUES, alert_delivered=True) == EXIT_ISSUES
    assert exit_code(EXIT_ISSUES, alert_delivered=False) == EXIT_ALERT_FAILED
    assert exit_code(EXIT_OK, alert_delivered=None) == EXIT_OK
