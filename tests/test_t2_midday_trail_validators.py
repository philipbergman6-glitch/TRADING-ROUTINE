"""T2: midday trail/stop changes go through validate_stop_change + required_trail_percent (#32).

Paper-only. Does NOT invent PATCH for #40; trail tighten remains cancel→order.
Does NOT start T4 ledger.record_decision.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from risk_engine import (
    MIN_STOP_DISTANCE_PCT,
    Rule,
    TRAIL_TIGHTEN_STEPS,
    required_trail_percent,
    validate_stop_change,
)

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "scripts" / "validate_stop_change.py"

MIDDAY_WORKFLOWS = (
    REPO / "routines" / "midday.md",
    REPO / ".claude" / "commands" / "midday.md",
)

EXIT_REFUSED = 3
EXIT_USAGE = 2


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=15,
    )


# --- CLI: required_trail_percent surface ------------------------------------


@pytest.mark.parametrize(
    "gain,expected",
    [
        ("0", "10"),
        ("14.99", "10"),
        ("15", "7"),
        ("19.99", "7"),
        ("20", "5"),
    ],
)
def test_cli_print_required_matches_engine(gain: str, expected: str) -> None:
    result = _run_cli("--gain-pct", gain, "--print-required")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
    assert required_trail_percent(gain) == Decimal(expected)


def test_cli_print_required_json() -> None:
    result = _run_cli("--gain-pct", "16", "--print-required", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["required_trail_percent"] == "7"
    assert payload["gain_pct"] == "16"


# --- CLI: trail path wires both validators ----------------------------------


def test_cli_approves_ladder_tighten_at_15() -> None:
    """+15% → required 7%; current 10% → proposed 7% is a raise of implied stop."""
    result = _run_cli(
        "--gain-pct",
        "15",
        "--proposed-trail",
        "7",
        "--current-trail",
        "10",
        "--current-price",
        "115",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["approved"] is True
    assert payload["required_trail_percent"] == "7"
    assert payload["engine_calls"] == [
        "required_trail_percent",
        "validate_stop_change",
    ]


def test_cli_refuses_trail_wider_than_ladder() -> None:
    """At +20% required is 5%; proposing 7% is too wide."""
    result = _run_cli(
        "--gain-pct",
        "20",
        "--proposed-trail",
        "7",
        "--current-trail",
        "10",
        "--current-price",
        "120",
        "--json",
    )
    assert result.returncode == EXIT_REFUSED
    payload = json.loads(result.stdout)
    assert payload["approved"] is False
    assert any(v["rule"] == Rule.STOP_DISTANCE.value for v in payload["violations"])


def test_cli_refuses_widening_trail() -> None:
    """Proposed trail wider than current is an effective stop lower → STOP_NEVER_LOWERED."""
    result = _run_cli(
        "--gain-pct",
        "16",
        "--proposed-trail",
        "10",
        "--current-trail",
        "7",
        "--current-price",
        "116",
        "--json",
    )
    assert result.returncode == EXIT_REFUSED
    payload = json.loads(result.stdout)
    assert payload["approved"] is False
    rules = {v["rule"] for v in payload["violations"]}
    # Wider than ladder AND widening vs current.
    assert Rule.STOP_DISTANCE.value in rules or Rule.STOP_NEVER_LOWERED.value in rules


def test_cli_refuses_trail_inside_min_distance() -> None:
    result = _run_cli(
        "--gain-pct",
        "50",
        "--proposed-trail",
        "2",
        "--current-trail",
        "5",
        "--current-price",
        "150",
        "--json",
    )
    assert result.returncode == EXIT_REFUSED
    payload = json.loads(result.stdout)
    assert any(v["rule"] == Rule.STOP_DISTANCE.value for v in payload["violations"])
    assert Decimal("2") < MIN_STOP_DISTANCE_PCT


def test_cli_tighter_than_required_is_allowed_floor() -> None:
    """required_trail_percent is widest permitted; tighter-than-required is legal."""
    # At +16% required=7%; proposing 5% is tighter (higher implied stop).
    result = _run_cli(
        "--gain-pct",
        "16",
        "--proposed-trail",
        "5",
        "--current-trail",
        "10",
        "--current-price",
        "116",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["approved"] is True
    assert payload["required_trail_percent"] == "7"


def test_cli_hold_at_required_is_allowed() -> None:
    result = _run_cli(
        "--gain-pct",
        "15",
        "--proposed-trail",
        "7",
        "--current-trail",
        "7",
        "--current-price",
        "115",
        "--json",
    )
    assert result.returncode == 0, result.stderr


# --- CLI: price path is validate_stop_change --------------------------------


def test_cli_price_path_approves_raise() -> None:
    result = _run_cli(
        "--current-stop",
        "90",
        "--new-stop",
        "95",
        "--current-price",
        "110",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["approved"] is True
    assert payload["engine_calls"] == ["validate_stop_change"]
    assert validate_stop_change("90", "95", "110")


def test_cli_price_path_refuses_lower() -> None:
    result = _run_cli(
        "--current-stop",
        "95",
        "--new-stop",
        "90",
        "--current-price",
        "110",
        "--json",
    )
    assert result.returncode == EXIT_REFUSED
    payload = json.loads(result.stdout)
    assert any(v["rule"] == Rule.STOP_NEVER_LOWERED.value for v in payload["violations"])


def test_cli_usage_error_when_mixed_or_incomplete() -> None:
    result = _run_cli("--proposed-trail", "7")
    assert result.returncode == EXIT_USAGE


# --- Midday workflows must call the CLI (not prose ladder alone) ------------


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_step4_wires_validate_stop_change_cli(path: Path) -> None:
    text = path.read_text()
    step4 = text.split("STEP 4", 1)[1].split("STEP 5", 1)[0]
    assert "validate_stop_change.py" in step4, (
        f"{path.name}: STEP 4 must call scripts/validate_stop_change.py"
    )
    assert "required_trail_percent" in step4 or "--print-required" in step4 or "--gain-pct" in step4
    # Prose ladder must not be the sole authority.
    assert "Ladder stays prose only" not in step4
    assert "do NOT wire stop-change" not in step4
    assert "Do NOT wire T2" not in step4


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_step4_still_cancel_then_order_no_patch(path: Path) -> None:
    """#40 OPEN — T2 must not invent PATCH; TRAIL_TIGHTEN_STEPS remain cancel→order."""
    text = path.read_text()
    step4 = text.split("STEP 4", 1)[1].split("STEP 5", 1)[0]
    assert "TRAIL_TIGHTEN_STEPS" in step4 or (
        "cancel" in step4 and "order" in step4
    )
    assert list(TRAIL_TIGHTEN_STEPS) == ["cancel", "order"]
    # Must not claim PATCH closed the naked window.
    assert re.search(r"\bPATCH\b", step4) is None or "#40" in step4
    assert "naked window" in step4.lower() or "#40" in step4


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_step4_keeps_validate_order_and_alpaca_risk_ok(path: Path) -> None:
    """T1 honesty: replacement sell still goes through validate_order + ALPACA_RISK_OK."""
    text = path.read_text()
    step4 = text.split("STEP 4", 1)[1].split("STEP 5", 1)[0]
    assert "validate_order.py" in step4
    assert "ALPACA_RISK_OK" in step4


def test_architecture_no_longer_claims_stop_validators_uncalled() -> None:
    text = (REPO / "ARCHITECTURE.md").read_text()
    # Must mention the CLI / midday wiring for #32.
    assert "validate_stop_change.py" in text or "T2" in text
    # Must not still say ladder validators remain uncalled without qualification.
    assert "ladder validators remain uncalled (issue #32 / T2)" not in text


def test_cli_script_exists_and_is_executable_bit_or_python() -> None:
    assert CLI.is_file()
    head = CLI.read_text().splitlines()[0]
    assert head.startswith("#!")
