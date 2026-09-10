"""T1: order-mutating alpaca paths must hit validate_order; read paths stay open.

Hard gate: scripts/alpaca.sh refuses mutating subcommands unless
ALPACA_RISK_OK=1. Routines must call validate_order.py before setting that
flag. Stop-change / trail ladder wiring is T2 (#32) — out of scope here.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ALPACA = REPO / "scripts" / "alpaca.sh"

# Subcommands that change broker state.
MUTATING = ("order", "close", "close-all", "cancel", "cancel-all")
READ_ONLY = ("account", "positions", "orders")

# Live unattended routines that place/modify orders (T1 scope).
LIVE_MUTATING_WORKFLOWS = (
    REPO / "routines" / "market-open.md",
    REPO / "routines" / "midday.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / ".claude" / "commands" / "midday.md",
    REPO / ".claude" / "commands" / "trade.md",
)


def _run_alpaca(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Paper endpoint + dummy keys so the paper/credential guards pass and we
    # reach the mutation gate (or curl). Never touch a real account.
    env["ALPACA_ENDPOINT"] = "https://paper-api.alpaca.markets/v2"
    env["ALPACA_API_KEY"] = "test-key-not-real"
    env["ALPACA_SECRET_KEY"] = "test-secret-not-real"
    # Drop any inherited approval so tests control it explicitly.
    env.pop("ALPACA_RISK_OK", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(ALPACA), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


@pytest.mark.parametrize("cmd,argv", [
    ("order", ["order", "{}"]),
    ("close", ["close", "AAPL"]),
    ("close-all", ["close-all"]),
    ("cancel", ["cancel", "ord-1"]),
    ("cancel-all", ["cancel-all"]),
])
def test_mutating_cmd_refuses_without_risk_ok(cmd: str, argv: list[str]) -> None:
    """Mutating paths hard-fail before any broker write when ungated."""
    result = _run_alpaca(*argv)
    assert result.returncode == 5, (
        f"{cmd} without ALPACA_RISK_OK should exit 5, got {result.returncode}\n"
        f"stderr={result.stderr!r}"
    )
    assert "ALPACA_RISK_OK" in result.stderr or "risk" in result.stderr.lower()
    # Must not have attempted a real HTTP mutation (curl would mention http / api).
    assert "paper-api.alpaca.markets" not in result.stdout


@pytest.mark.parametrize("cmd,argv", [
    ("order", ["order", "{}"]),
    ("close", ["close", "AAPL"]),
])
def test_mutating_cmd_passes_gate_with_risk_ok(cmd: str, argv: list[str]) -> None:
    """With ALPACA_RISK_OK=1 the mutation gate is satisfied (curl may still fail)."""
    result = _run_alpaca(*argv, env_extra={"ALPACA_RISK_OK": "1"})
    assert result.returncode != 5, (
        f"{cmd} with ALPACA_RISK_OK=1 must not hit the risk gate\n"
        f"stderr={result.stderr!r}"
    )
    # Exit 5 is reserved for the risk gate; any other failure is curl/API.


@pytest.mark.parametrize("cmd", READ_ONLY)
def test_read_only_cmds_do_not_require_risk_ok(cmd: str) -> None:
    """daily-summary / account reads must keep working without ALPACA_RISK_OK."""
    argv = [cmd] if cmd != "orders" else ["orders", "open"]
    result = _run_alpaca(*argv)
    assert result.returncode != 5, (
        f"read-only {cmd} must not require ALPACA_RISK_OK\nstderr={result.stderr!r}"
    )


def _mutating_mentions(text: str) -> list[str]:
    """Return lines that invoke a mutating alpaca.sh subcommand."""
    pattern = re.compile(
        r"alpaca\.sh\s+(order|close|close-all|cancel|cancel-all)\b"
    )
    return [line for line in text.splitlines() if pattern.search(line)]


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_requires_validate_order_before_mutations(path: Path) -> None:
    """Every live mutating workflow must instruct validate_order.py."""
    text = path.read_text()
    assert "validate_order.py" in text, (
        f"{path.relative_to(REPO)} mutates orders but never mentions validate_order.py"
    )
    # First validate_order mention must appear before first mutating alpaca line.
    validate_at = text.find("validate_order.py")
    mutating_lines = _mutating_mentions(text)
    assert mutating_lines, f"{path.name}: expected at least one mutating alpaca.sh call"
    first_mutate_at = min(text.find(line) for line in mutating_lines)
    assert validate_at < first_mutate_at, (
        f"{path.relative_to(REPO)}: validate_order.py must appear before "
        f"alpaca.sh mutating calls"
    )
    # Mutating invocations must carry the hard-gate flag (or be clearly gated).
    for line in mutating_lines:
        assert "ALPACA_RISK_OK" in line or "ALPACA_RISK_OK" in text, (
            f"{path.relative_to(REPO)}: mutating line lacks ALPACA_RISK_OK context:\n{line}"
        )


def test_market_open_checklist_defers_sizing_to_engine() -> None:
    """STEP 3 must not hand-check engine-owned rules; cash + 85% via validate_order."""
    text = (REPO / "routines" / "market-open.md").read_text()
    # Engine owns these — prose must not be the sole authority (stale list risk).
    assert "validate_order.py" in text
    assert "85%" in text or "deployment" in text.lower() or "MAX_DEPLOYMENT" in text
    assert "cash" in text.lower() or "SUFFICIENT_CASH" in text
    # Phantom PDT hand-check removed from the authoritative checklist.
    assert "daytrade_count" not in text
    # Catalyst remains (UNMECHANISED).
    assert "catalyst" in text.lower() or "RESEARCH-LOG" in text


def test_midday_does_not_wire_stop_change_validator() -> None:
    """T1 must not pull in T2 (#32) validate_stop_change / required_trail wiring."""
    for path in (
        REPO / "routines" / "midday.md",
        REPO / ".claude" / "commands" / "midday.md",
    ):
        text = path.read_text()
        assert "validate_stop_change" not in text
        assert "required_trail_percent" not in text
        # Still gates closes / replacement orders through validate_order.
        assert "validate_order.py" in text
