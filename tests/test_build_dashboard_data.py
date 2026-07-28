"""Golden test: build_dashboard_data.py must reproduce committed data.js exactly."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "build_dashboard_data", REPO / "scripts" / "build_dashboard_data.py")
b = importlib.util.module_from_spec(spec)
sys.modules["build_dashboard_data"] = b
spec.loader.exec_module(b)


def build():
    snaps = b.parse_trade_log(b.TRADE_LOG.read_text(encoding="utf-8"))
    weeks = b.parse_weekly_review(b.WEEKLY_REVIEW.read_text(encoding="utf-8"))
    return snaps, weeks, b.emit(snaps, weeks)


def test_golden_reproduces_committed_data_js():
    _, _, out = build()
    assert out == b.OUT.read_text(encoding="utf-8"), (
        "regenerated data.js differs from committed docs/dashboard/data.js — "
        "run scripts/build_dashboard_data.py and commit, or fix the parser")


def test_snapshot_counts_sane():
    snaps, weeks, _ = build()
    assert len(snaps) >= 38
    assert len(weeks) >= 7
    assert snaps[0]["d"] == "2026-04-27" and snaps[0]["v"] == 100000.00


def test_hard_fails_on_malformed_portfolio_line():
    text = b.TRADE_LOG.read_text(encoding="utf-8").replace(
        "**Portfolio:** $105,878.53", "**Portfolio:** broken")
    with pytest.raises(b.ParseError):
        b.parse_trade_log(text)


def test_hard_fails_on_missing_week_return():
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8").replace(
        "| Week return |", "| Wk return |")
    with pytest.raises(b.ParseError):
        b.parse_weekly_review(text)
