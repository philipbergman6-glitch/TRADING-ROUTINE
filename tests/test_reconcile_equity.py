"""scripts/reconcile_equity.py and the read-only alpaca.sh subcommands it needs."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import pytest

REPO = Path(__file__).resolve().parent.parent
ALPACA = REPO / "scripts" / "alpaca.sh"


def run_alpaca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run alpaca.sh with dummy paper credentials and a curl that echoes its URL."""
    env = os.environ.copy()
    env.update({"ALPACA_ENDPOINT": "https://paper-api.alpaca.markets/v2",
                "ALPACA_API_KEY": "test-key-not-real", "ALPACA_SECRET_KEY": "test-secret-not-real"})
    env.pop("ALPACA_DATA_ENDPOINT", None)
    env.pop("ALPACA_HTTP_STATUS_FILE", None)
    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "curl"
        fake.write_text('#!/bin/sh\nfor a in "$@"; do last="$a"; done\nprintf \'"%s"\\n\' "$last"\n')
        fake.chmod(0o700)
        env["PATH"] = directory + os.pathsep + env["PATH"]
        return subprocess.run(["bash", str(ALPACA), *args], capture_output=True, text=True, env=env, timeout=15)


def test_activities_all_pages_every_activity_type_in_ascending_order():
    out = run_alpaca("activities-all")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == '"https://paper-api.alpaca.markets/v2/account/activities?direction=asc&page_size=100"'
    out = run_alpaca("activities-all", "2026-04-17T00:00:00Z", "20260506000000000::abc-123")
    assert "&after=2026-04-17T00:00:00Z&page_token=20260506000000000::abc-123" in out.stdout
    assert run_alpaca("activities-all", "yesterday").returncode == 2
    assert run_alpaca("activities-all", "", "bad token!").returncode == 2


def test_portfolio_history_is_daily_and_validates_the_period():
    out = run_alpaca("portfolio-history")
    assert out.stdout.strip() == '"https://paper-api.alpaca.markets/v2/account/portfolio/history?period=1A&timeframe=1D"'
    assert "period=3M&" in run_alpaca("portfolio-history", "3M").stdout
    assert run_alpaca("portfolio-history", "forever").returncode == 2


def test_bars_hit_the_data_endpoint_with_sip_daily_closes_and_validate_every_arg():
    out = run_alpaca("bars", "AMD,XLK", "2026-09-14", "2026-09-18")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ('"https://data.alpaca.markets/v2/stocks/bars?symbols=AMD,XLK&timeframe=1Day'
                                  '&start=2026-09-14&end=2026-09-18&feed=sip&adjustment=raw&limit=10000"')
    assert "&page_token=tok-1" in run_alpaca("bars", "AMD", "2026-09-14", "2026-09-18", "tok-1").stdout
    for bad in (("bars", "amd", "2026-09-14", "2026-09-18"), ("bars", "AMD", "9/14", "2026-09-18"),
                ("bars", "AMD;rm", "2026-09-14", "2026-09-18")):
        assert run_alpaca(*bad).returncode == 2, bad
    assert run_alpaca("bars", "AMD", "2026-09-14").returncode == 1  # missing END, like every `${n:?}` usage error


@pytest.mark.parametrize("cmd", ["activities-all", "portfolio-history"])
def test_new_subcommands_are_read_only_and_never_need_risk_ok(cmd):
    assert run_alpaca(cmd).returncode == 0


# ---- the script, offline, with an injected broker reader ---------------------------------------
from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402
import json  # noqa: E402

from scripts import reconcile_equity as cli  # noqa: E402


def fill(i, t, sym, side, qty, price):
    return {"id": str(i), "activity_type": "FILL", "transaction_time": t, "symbol": sym,
            "side": side, "qty": str(qty), "price": str(price), "order_id": f"o{i}"}


ACTIVITIES = [
    {"id": "1", "activity_type": "JNLC", "date": "2026-04-17", "net_amount": "100000"},
    fill(2, "2026-04-28T13:30:00Z", "AMD", "buy", 10, "300"),
    {"id": "3", "activity_type": "FEE", "date": "2026-04-28", "net_amount": "-0.02"},
]
# 1776470400 = 2026-04-18T00:00Z -> holds the 2026-04-17 close; 1777420800 -> 2026-04-28; 1777507200 -> 2026-04-29 (today, skipped)
HISTORY = {"timestamp": [1776470400, 1777334400, 1777420800, 1777507200], "equity": ["100000", "100000", "100049.98", "100100"]}
BARS = {"bars": {"AMD": [{"t": "2026-04-28T04:00:00Z", "c": "305"}]}, "next_page_token": None}


def reader(calls, overrides=None):
    responses = {"activities-all": ACTIVITIES, "portfolio-history": HISTORY, "bars": BARS,
                 "account": {"cash": "97000.00", "equity": "100100"}, "positions": [{"symbol": "AMD", "qty": "10"}]}
    responses.update(overrides or {})

    def read(*args):
        calls.append(args)
        return responses[args[0]]
    return read


def test_report_reconciles_cash_holdings_and_each_past_session():
    calls = []
    report = cli.reconcile(reader(calls, {"account": {"cash": "96999.98"}}), today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    assert report["ok"] is True and report["unexplained"] == []
    assert report["cash"] == {"rebuilt": "96999.98", "broker": "96999.98", "ok": True}
    assert report["flows"] == {"FEE": "-0.02", "JNLC": "100000"} and report["skipped_sessions"] == ["2026-04-29"]
    assert [r["session"] for r in report["days"]] == ["2026-04-17", "2026-04-27", "2026-04-28"]
    assert report["days"][-1]["diff"] == "0.00" and report["days"][-1]["status"] == "ok"
    assert ("bars", "AMD", "2026-04-28", "2026-04-28") in calls
    assert ("portfolio-history", "1A") in calls


def test_cash_or_holdings_mismatch_today_is_unexplained():
    report = cli.reconcile(reader([]), today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    assert report["ok"] is False
    assert report["unexplained"] == ["cash: rebuilt 96999.98 vs broker 97000.00 (diff -0.02)"]
    good = reader([], {"account": {"cash": "96999.98"}, "positions": [{"symbol": "AMD", "qty": "9"}]})
    report = cli.reconcile(good, today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    assert report["unexplained"] == ["holdings AMD: fills imply 10, broker holds 9"]


def test_equity_difference_beyond_tolerance_fails_unless_recorded(tmp_path):
    bad = reader([], {"account": {"cash": "96999.98"}, "portfolio-history": {**HISTORY, "equity": ["100000", "100000", "100149.98", "1"]}})
    report = cli.reconcile(bad, today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    assert report["unexplained"] == ["2026-04-28: rebuilt 100049.98 vs broker 100149.98 (diff -100.00)"]
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"_note": "why", "2026-04-28": {"diff": "-100.00", "reason": "stale broker mark"}}))
    report = cli.reconcile(bad, today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions=cli.load_exceptions(path))
    assert report["ok"] and report["days"][-1]["status"] == "explained: stale broker mark"
    path.write_text(json.dumps({"2026-04-28": {"reason": "no diff recorded"}}))
    with pytest.raises(ValueError, match="diff"):
        cli.load_exceptions(path)


def test_bars_are_paged_and_a_short_history_or_unknown_activity_is_fatal():
    calls = []
    paged = reader(calls, {"bars": None})
    pages = [{"bars": {"AMD": [{"t": "2026-04-28T04:00:00Z", "c": "305"}]}, "next_page_token": "p2"},
             {"bars": {"AMD": []}, "next_page_token": None}]

    def read(*args):
        if args[0] == "bars":
            return pages.pop(0)
        return paged(*args)
    closes = cli.fetch_closes(read, ["AMD"], date(2026, 4, 28), date(2026, 4, 28))
    assert closes == {("AMD", date(2026, 4, 28)): Decimal("305")}
    with pytest.raises(ValueError, match="JNLS"):
        cli.reconcile(reader([], {"activities-all": ACTIVITIES + [{"id": "9", "activity_type": "JNLS", "date": "2026-04-28", "net_amount": "0"}]}),
                      today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    with pytest.raises(ValueError, match="does not reach back"):
        cli.reconcile(reader([], {"portfolio-history": {"timestamp": [1777420800], "equity": ["100049.98"]}}),
                      today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})


def test_text_report_names_the_verdict_and_every_non_ok_day(capsys):
    report = cli.reconcile(reader([], {"account": {"cash": "96999.98"}}), today=date(2026, 4, 29), tolerance=Decimal("1"), exceptions={})
    text = cli.render(report)
    assert text.startswith("RECONCILED\n") and "cash 96999.98 = broker 96999.98" in text
    assert "last session 2026-04-28: rebuilt 100049.98 vs broker 100049.98 (diff 0.00, ok)" in text
    assert "| 2026-04-28 |" not in text and "| 2026-04-28 |" in cli.render(report, show_all=True)


def test_main_exit_codes(monkeypatch):
    monkeypatch.setattr(cli, "adapter", reader([], {"account": {"cash": "96999.98"}}))
    monkeypatch.setattr(cli, "today_eastern", lambda: date(2026, 4, 29))
    monkeypatch.setattr(cli, "EXCEPTIONS_FILE", Path("/nonexistent/none.json"))
    assert cli.main([]) == 0
    monkeypatch.setattr(cli, "adapter", reader([]))
    assert cli.main([]) == 4
    assert cli.main(["--tolerance", "-1"]) == 2


@pytest.mark.parametrize("routine", [REPO / "routines" / "daily-summary.md", REPO / ".claude" / "commands" / "daily-summary.md"])
def test_daily_summary_runs_the_reconciliation_and_stops_on_exit_4(routine):
    text = routine.read_text()
    assert "python3 scripts/reconcile_equity.py" in text
    assert "RECONCILIATION MISMATCH" in text
