"""Heartbeat: every expected routine commit and workflow outcome for a trading day, nothing on holidays."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

import pytest

from scripts.heartbeat import (EXIT_ALERT_FAILED, EXIT_ISSUES, EXIT_OK, MONITOR_DRY, MONITOR_LIVE, assess,
                               assessment_date, exit_code, send_alert)

MONITOR_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "protection-monitor.yml"

MON = date(2026, 9, 28)
FRI = date(2026, 9, 25)
GOOD_COMMITS = ["EOD snapshot 2026-09-28", "midday scan 2026-09-28", "market-open trades 2026-09-28",
                "pre-market research 2026-09-28", "dashboard data: 2026-09-28 [skip ci]"]
AFTER_CLOSE = datetime(2026, 9, 28, 22, 45, tzinfo=timezone.utc)


def monitor_runs(day, *hhmm_utc, conclusion="success", title="protection-monitor live"):
    # display_title is the workflow's run-name: it carries the dry-run mode, which the run list does not.
    return [{"name": "protection-monitor", "display_title": title, "conclusion": conclusion,
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
    assert issues == ["workflow protection-monitor: no successful live run today (2 run(s) seen, 0 dry run(s))",
                      "workflow dashboard-data: 1 failed run(s) today, latest u"]
    runs[0] = monitor_runs("2026-09-28", (13, 40))[0]
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


def test_a_day_of_only_dry_runs_has_no_protection_check():
    # A dry run plans but does no due work, so it is not a protection check (ADR 0007).
    runs = monitor_runs("2026-09-28", *EVERY_30, title="protection-monitor dry run") + GOOD_RUNS[-2:]
    r = assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)
    assert r["exit"] == EXIT_ISSUES
    assert r["issues"] == ["workflow protection-monitor: no successful live run today (14 run(s) seen, 14 dry run(s))"]
    assert r["protection_check"]["checks"] == []


def test_dry_runs_do_not_fill_the_gaps_between_live_checks():
    # Live checks at 18:16Z and 22:30Z only; a dry run every 30 minutes changes nothing.
    dry = monitor_runs("2026-09-28", *EVERY_30, title="protection-monitor dry run")
    runs = dry + monitor_runs("2026-09-28", (18, 16), (22, 30)) + GOOD_RUNS[-2:]
    r = assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)
    assert r["issues"] == ["protection check: stale 300 min of the 390-min session, over the 90-min level: "
                           "13:30-18:16Z (286 min), 19:46-20:00Z (14 min)"]
    assert r["protection_check"]["checks"] == ["2026-09-28T18:16:00+00:00", "2026-09-28T22:30:00+00:00"]


def test_monitor_workflow_stamps_the_mode_the_step_runs_in():
    # The run list has no dispatch inputs; run-name is the only observable mode. It must
    # use the very condition that selects --dry-run, and yield the titles assess() reads.
    yml = MONITOR_YML.read_text()
    dry_if = re.search(r'if \[ "\$\{\{ github.event_name \}\}" = "workflow_dispatch" \] && '
                       r'\[ "\$\{\{ inputs.dry_run \}\}" = "true" \]; then\s*\n\s+python3 scripts/protection_monitor.py --dry-run', yml)
    assert dry_if, "the dry-run step condition changed; update run-name to match"
    (run_name,) = re.findall(r"^run-name: (.+)$", yml, re.M)
    assert run_name == ("${{ github.event_name == 'workflow_dispatch' && format('{0}', inputs.dry_run) == 'true' "
                        f"&& '{MONITOR_DRY}' || '{MONITOR_LIVE}' }}}}")


def test_successful_monitor_run_with_unknown_title_is_rejected():
    # A run-name that drifted (or a run from before it existed) must not be guessed live or dry.
    runs = monitor_runs("2026-09-28", *EVERY_30) + monitor_runs("2026-09-28", (15, 0), title="protection-monitor")
    with pytest.raises(ValueError, match="display_title 'protection-monitor'"):
        assess(MON, True, GOOD_COMMITS, runs + GOOD_RUNS[-2:], AFTER_CLOSE)


def test_successful_monitor_run_without_completion_time_is_rejected():
    runs = [{"name": "protection-monitor", "display_title": "protection-monitor live", "conclusion": "success"}] + GOOD_RUNS[-2:]
    with pytest.raises(ValueError, match="updated_at"):
        assess(MON, True, GOOD_COMMITS, runs, AFTER_CLOSE)


def test_alert_failure_fails_the_job_even_when_only_issues_exist():
    def refused(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 2)

    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    assert send_alert("x", run=refused) == "failed"
    assert send_alert("x", run=hung) == "failed"
    assert exit_code(EXIT_ISSUES, alert_delivered=True) == EXIT_ISSUES
    assert exit_code(EXIT_ISSUES, alert_delivered=False) == EXIT_ALERT_FAILED
    assert exit_code(EXIT_OK, alert_delivered=None) == EXIT_OK


def email_sh(code, stdout=""):
    """A fake scripts/email.sh run: exit code plus the stdout it would print."""
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")


@pytest.mark.parametrize("code, stdout, delivery", [
    (0, "sent id=e1\nlast_event=delivered\ndelivery=verified\n", "verified"),
    (0, "sent id=e1\ndelivery=unverified reason=restricted_api_key\n", "unverified"),
    (0, "sent id=e1\n", "unverified"),  # exit 0 without a verdict proves nothing more than "sent"
    (4, "sent id=e1\nlast_event=bounced\n", "failed"),
    (2, "", "failed"),
])
def test_alert_delivery_is_verified_unverified_or_failed(code, stdout, delivery):
    assert send_alert("x", run=email_sh(code, stdout)) == delivery


def test_send_only_key_reports_sent_unverified_and_keeps_the_exit(monkeypatch, capsys):
    """Ticket #147: the restricted key is a configuration warning, not a lost alert."""
    import scripts.heartbeat as hb
    monkeypatch.setattr(hb, "trading_day_from_alpaca", lambda today: True)
    monkeypatch.setattr(hb, "commit_subjects_since", lambda since: [])
    monkeypatch.setattr(hb, "runs_today", lambda repo, today: [])
    for code, stdout, expect_exit, expect_delivery in [
            (0, "delivery=unverified reason=restricted_api_key\n", EXIT_ISSUES, "unverified"),
            (0, "delivery=verified\n", EXIT_ISSUES, "verified"),
            (4, "", EXIT_ALERT_FAILED, "failed")]:
        monkeypatch.setattr(hb, "send_alert", lambda body, c=code, o=stdout: hb.alert_delivery.send(
            body, run=email_sh(c, o)))
        monkeypatch.setattr("sys.argv", ["heartbeat.py", "--date", "2026-09-28"])
        assert hb.main() == expect_exit
        out = capsys.readouterr().out
        report = json.loads(out)
        assert report["alert_delivery"] == expect_delivery
        assert report["alert_delivered"] is (expect_delivery != "failed")
