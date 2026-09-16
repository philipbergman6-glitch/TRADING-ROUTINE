"""Rule 12 backstop: consecutive under-band sessions -> mandate, computed not remembered."""

import importlib.util
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "deployment_status", REPO / "scripts" / "deployment_status.py")
ds = importlib.util.module_from_spec(spec)
sys.modules["deployment_status"] = ds
spec.loader.exec_module(ds)


def snaps(*cash_pcts, last="2026-09-16"):
    """Oldest first; only the last date matters for staleness."""
    out = [{"d": "2026-09-01", "cash": c} for c in cash_pcts]
    out[-1]["d"] = last
    return out


TODAY = date(2026, 9, 17)


def test_counts_only_trailing_run():
    assert ds.sessions_under_band(snaps(40, 20, 40, 39, 39)) == 3
    assert ds.sessions_under_band(snaps(40, 40, 20)) == 0


def test_boundary_75_is_in_band():
    assert ds.sessions_under_band(snaps(25.0)) == 0
    assert ds.sessions_under_band(snaps(25.01)) == 1


def test_mandate_after_three_sessions():
    r = ds.evaluate(snaps(20, 39, 39, 39), D("100000"), D("60000"), D("40000"), TODAY)
    assert r["mandate"] and r["exemption_allowed"]
    assert r["sessions_under_band"] == 3
    assert r["target_notional"] == 20000  # 80% midpoint gap, = 20% cap


def test_no_exemption_after_first_due_session():
    r = ds.evaluate(snaps(39, 39, 39, 39), D("100000"), D("60000"), D("40000"), TODAY)
    assert r["mandate"] and not r["exemption_allowed"]


def test_two_sessions_no_mandate():
    r = ds.evaluate(snaps(20, 39, 39), D("100000"), D("60000"), D("40000"), TODAY)
    assert not r["mandate"]


def test_live_back_in_band_clears_mandate():
    r = ds.evaluate(snaps(39, 39, 39), D("100000"), D("78000"), D("22000"), TODAY)
    assert not r["mandate"] and r["target_notional"] == 0


def test_target_capped_by_cash():
    r = ds.evaluate(snaps(39, 39, 39), D("100000"), D("60000"), D("5000"), TODAY)
    assert r["target_notional"] == 5000


def test_stale_log_hard_fails():
    with pytest.raises(ValueError, match="untrustworthy"):
        ds.evaluate(snaps(39, 39, 39, last="2026-09-08"), D("100000"), D("60000"),
                    D("40000"), TODAY)


def test_cli_exit_codes(tmp_path):
    assert ds.main(["--equity", "100", "--today", "2026-09-17"]) == 2
    bad = tmp_path / "log.md"
    bad.write_text("no snapshots here")
    assert ds.main(["--equity", "100", "--long-market-value", "60",
                    "--trade-log", str(bad), "--today", "2026-09-17"]) == 4
