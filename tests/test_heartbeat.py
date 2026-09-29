"""Heartbeat: every expected routine commit and workflow outcome for a trading day, nothing on holidays."""
from datetime import date

from scripts.heartbeat import EXIT_ISSUES, EXIT_OK, assess

MON = date(2026, 9, 28)
FRI = date(2026, 9, 25)
GOOD_COMMITS = ["EOD snapshot 2026-09-28", "midday scan 2026-09-28", "market-open trades 2026-09-28",
                "pre-market research 2026-09-28", "dashboard data: 2026-09-28 [skip ci]"]
GOOD_RUNS = [{"name": "protection-monitor", "conclusion": "success"},
             {"name": "dashboard-data", "conclusion": "success"},
             {"name": "tests", "conclusion": "success"}]


def test_full_trading_day_is_clean():
    r = assess(MON, True, GOOD_COMMITS, GOOD_RUNS)
    assert r["exit"] == EXIT_OK and r["issues"] == []


def test_holiday_expects_nothing():
    r = assess(MON, False, [], [])
    assert r["exit"] == EXIT_OK and r["trading_day"] is False


def test_missing_midday_and_eod_are_named():
    r = assess(MON, True, ["pre-market research 2026-09-28"], GOOD_RUNS)
    assert r["exit"] == EXIT_ISSUES
    assert sorted(i.split(":")[0] for i in r["issues"]) == ["routine eod", "routine midday"]


def test_yesterdays_commit_does_not_count():
    stale = [s.replace("2026-09-28", "2026-09-25") for s in GOOD_COMMITS]
    r = assess(MON, True, stale, GOOD_RUNS)
    assert len(r["issues"]) == 3


def test_market_open_is_optional():
    r = assess(MON, True, [s for s in GOOD_COMMITS if "market-open" not in s], GOOD_RUNS)
    assert r["issues"] == []


def test_friday_requires_weekly_review():
    commits = [s.replace("2026-09-28", "2026-09-25") for s in GOOD_COMMITS]
    assert assess(FRI, True, commits, GOOD_RUNS)["issues"] == ["routine weekly-review: no commit 'weekly review 2026-09-25' on main"]
    assert assess(FRI, True, commits + ["weekly review 2026-09-25"], GOOD_RUNS)["issues"] == []


def test_monitor_needs_one_success_and_failures_of_others_are_flagged():
    runs = [{"name": "protection-monitor", "conclusion": "failure"},
            {"name": "protection-monitor", "conclusion": "failure"},
            {"name": "dashboard-data", "conclusion": "failure", "url": "u"},
            {"name": "tests", "conclusion": "success"}]
    issues = assess(MON, True, GOOD_COMMITS, runs)["issues"]
    assert issues == ["workflow protection-monitor: no successful run today (2 run(s) seen)",
                      "workflow dashboard-data: 1 failed run(s) today, latest u"]
    runs[0]["conclusion"] = "success"
    assert assess(MON, True, GOOD_COMMITS, runs)["issues"] == ["workflow dashboard-data: 1 failed run(s) today, latest u"]
