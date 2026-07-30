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


def test_phase_day_parsed_and_monotonic():
    snaps, _, _ = build()
    assert snaps[0]["n"] == 0
    ns = [s["n"] for s in snaps]
    assert ns == sorted(ns), f"phase day numbers out of order: {ns}"
    assert snaps[-1]["n"] >= 66


def test_hard_fails_on_missing_phase_day():
    text = b.TRADE_LOG.read_text(encoding="utf-8").replace(
        "— EOD Snapshot (Day 66,", "— EOD Snapshot (")
    with pytest.raises(b.ParseError):
        b.parse_trade_log(text)


def test_live_figures_are_not_frozen_in_static_tail():
    """The curated tail must carry placeholders, never a baked-in number."""
    assert "__DEPLOYED__" in b.STATIC_TAIL
    assert "__DAYS__" in b.STATIC_TAIL
    snaps, weeks, out = build()
    assert "__" not in out.split("const TRADES")[1], "placeholder left unsubstituted"
    assert f"now {100 - snaps[-1]['cash']:.1f}%" in out
    assert f"in {snaps[-1]['n']} days" in out


def test_hard_fails_on_missing_week_return():
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8").replace(
        "| Week return |", "| Wk return |")
    with pytest.raises(b.ParseError):
        b.parse_weekly_review(text)
