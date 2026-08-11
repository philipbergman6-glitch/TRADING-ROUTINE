"""Golden test: build_dashboard_data.py must reproduce committed data.js exactly."""

import importlib.util
import os
import re
import subprocess
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


# ---- benchmark chain integrity ------------------------------------------
# The S&P series is the scoreboard for "beat the S&P", so it gets the same
# hard-fail treatment as the equity series.

def test_spxc_is_chained_from_logged_closes():
    """Every non-est week's spxc must equal close/prev_close - 1."""
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8")
    weeks = b.parse_weekly_review(text)
    closes = []
    for row in re.findall(r"^\| S&P 500 week \| (.+?) \|$", text, re.M):
        levels = b.SPX_LEVEL.findall(row)
        if len(levels) >= 2:
            closes.append(float(levels[1].replace(",", "")))
    chained = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    got = [w["spxc"] for w in weeks if not w["est"]]
    assert len(got) == len(chained) > 0
    for g, c in zip(got, chained):
        assert abs(g - c) < 0.005, f"spxc {g} is not the chained value {c}"


def test_known_chain_breaks_are_exactly_the_ones_present():
    """Guards both directions: no undocumented break, no stale grandfather."""
    weeks = b.parse_weekly_review(b.WEEKLY_REVIEW.read_text(encoding="utf-8"))
    assert len(weeks) >= 9
    assert set(b.KNOWN_SPX_CHAIN_BREAKS) == {"2026-07-24", "2026-07-31", "2026-08-07"}


def test_hard_fails_on_new_chain_break():
    """Restating a week's starting level must break the build, not pass quietly."""
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8").replace(
        "| S&P 500 week | +1.71% (7,357.49 Jun 26 → 7,483.24 Jul 2; Jul 3 holiday) |",
        "| S&P 500 week | +1.71% (7,300.00 Jun 26 → 7,424.83 Jul 2; Jul 3 holiday) |")
    with pytest.raises(b.ParseError, match="chain break"):
        b.parse_weekly_review(text)


def test_hard_fails_when_percent_contradicts_levels():
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8").replace(
        "| S&P 500 week | -1.91% (7,500.58 Jun 18 → 7,357.49 Jun 26; Jun 19 holiday) |",
        "| S&P 500 week | +9.99% (7,500.58 Jun 18 → 7,357.49 Jun 26; Jun 19 holiday) |")
    with pytest.raises(b.ParseError, match="levels imply"):
        b.parse_weekly_review(text)


def test_hard_fails_on_repaired_but_still_grandfathered_break():
    """If a logged break is fixed, the grandfather entry must be removed too."""
    # A real repair fixes the start level AND the percent it implies.
    text = b.WEEKLY_REVIEW.read_text(encoding="utf-8").replace(
        "| S&P 500 week | -0.33% (7,441.68 Jul 17 → 7,417.10 Jul 24",
        "| S&P 500 week | -0.78% (7,475.69 Jul 17 → 7,417.10 Jul 24")
    with pytest.raises(b.ParseError, match="no longer present"):
        b.parse_weekly_review(text)


# ---- paper-only guard ----------------------------------------------------

def test_alpaca_wrapper_refuses_live_endpoint():
    """Runs keyless: the guard must fire before credentials are even checked."""
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
           "ALPACA_ENDPOINT": "https://api.alpaca.markets/v2"}
    r = subprocess.run(["bash", str(REPO / "scripts" / "alpaca.sh"), "account"],
                       capture_output=True, text=True, env=env, cwd=REPO)
    assert r.returncode == 4, f"expected refusal, got {r.returncode}: {r.stdout}{r.stderr}"
    assert "REFUSING" in r.stderr


def test_alpaca_wrapper_allows_live_with_explicit_override():
    """The override must be reachable — but only when deliberately set."""
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
           "ALPACA_ENDPOINT": "https://api.alpaca.markets/v2",
           "ALPACA_ALLOW_LIVE": "1", "ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}
    r = subprocess.run(["bash", str(REPO / "scripts" / "alpaca.sh"), "account"],
                       capture_output=True, text=True, env=env, cwd=REPO)
    assert r.returncode != 4 and "REFUSING" not in r.stderr


def test_env_file_does_not_override_process_env():
    """A stale .env must never clobber a deliberately exported variable."""
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
           "ALPACA_ENDPOINT": "https://api.alpaca.markets/v2"}
    r = subprocess.run(["bash", str(REPO / "scripts" / "alpaca.sh"), "account"],
                       capture_output=True, text=True, env=env, cwd=REPO)
    assert "api.alpaca.markets" in r.stderr and "paper-api" not in r.stderr


# --- Freshness stamps: curated prose must never pass as live data -----------


def test_emits_both_freshness_dates():
    """The dashboard needs two independent dates to distinguish generated
    figures from curated narrative."""
    snaps, _, out = build()
    assert f'const LOG_ASOF = "{snaps[-1]["d"]}";' in out
    assert f'const ANALYSIS_ASOF = "{b.ANALYSIS_ASOF}";' in out


def test_analysis_asof_is_an_iso_date():
    from datetime import date

    assert date.fromisoformat(b.ANALYSIS_ASOF)


def test_editorial_header_is_substituted_not_hardcoded():
    """A hardcoded date in the template is how the header drifted stale before."""
    assert "__ANALYSIS_ASOF__" in b.STATIC_TAIL, (
        "editorial header must use the placeholder so ANALYSIS_ASOF stays the "
        "single source of truth")
    _, _, out = build()
    assert "__ANALYSIS_ASOF__" not in out
    assert f"analysis as of {b.ANALYSIS_ASOF}" in out


def test_no_stale_2026_07_28_stamp_survives_anywhere():
    """Regression guard for the specific drift this fixed: the module docstring
    claimed 2026-07-28 while the editorial block said 2026-08-11."""
    source = (REPO / "scripts" / "build_dashboard_data.py").read_text(encoding="utf-8")
    stale = [ln for ln in source.splitlines()
             if "2026-07-28" in ln and "analysis" in ln.lower()]
    assert not stale, f"stale analysis stamp still present: {stale}"
