"""T3: close unprotected windows — OTO buy (ADR 0002) + cancel-then-act order (#38).

Does NOT wire T2 trail validators (#32) or T4 ledger.record_decision.
Does NOT claim PATCH closes the trail-tighten naked window — that needs #40.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from risk_engine import (
    CUT_LOSER_STEPS,
    CONVERT_FIXED_TO_TRAIL_STEPS,
    TRAIL_TIGHTEN_STEPS,
    FixedStop,
    TrailingStop,
    assert_leg_matches_fixed,
    build_oto_entry,
    build_trailing_stop,
    fixed_stop_at_distance,
)

REPO = Path(__file__).resolve().parent.parent
BUILD_OTO = REPO / "scripts" / "build_oto_order.py"

MARKET_OPEN_WORKFLOWS = (
    REPO / "routines" / "market-open.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / ".claude" / "commands" / "trade.md",
)

MIDDAY_WORKFLOWS = (
    REPO / "routines" / "midday.md",
    REPO / ".claude" / "commands" / "midday.md",
)


def test_oto_stop_loss_has_stop_price_only() -> None:
    body = build_oto_entry(
        symbol="F",
        qty=3,
        protection=FixedStop(stop_price=Decimal("12.57")),
    )
    assert body["order_class"] == "oto"
    assert body["side"] == "buy"
    assert body["type"] == "market"
    assert body["stop_loss"] == {"stop_price": "12.57"}
    assert "trail_percent" not in body["stop_loss"]
    assert "trail_price" not in body["stop_loss"]


def test_oto_rejects_trailing_protection() -> None:
    with pytest.raises(TypeError, match="FixedStop"):
        build_oto_entry(
            symbol="F",
            qty=1,
            protection=TrailingStop(trail_percent=Decimal("10")),  # type: ignore[arg-type]
        )


def test_oto_rejects_fractional_qty() -> None:
    with pytest.raises(ValueError, match="whole shares"):
        build_oto_entry(
            symbol="F",
            qty=Decimal("1.5"),
            protection=FixedStop(stop_price="10"),
        )


def test_fixed_stop_at_distance_ten_percent() -> None:
    stop = fixed_stop_at_distance("13.97", "10")
    assert stop.stop_price == Decimal("12.57")


def test_assert_leg_matches_fixed_accepts_clean_leg() -> None:
    expected = FixedStop(stop_price="12.57")
    assert_leg_matches_fixed(
        {"type": "stop", "stop_price": "12.57", "trail_percent": None},
        expected,
    )


def test_assert_leg_rejects_silent_downgrade_trail() -> None:
    expected = FixedStop(stop_price="12.57")
    with pytest.raises(AssertionError, match="trail_percent"):
        assert_leg_matches_fixed(
            {"type": "stop", "stop_price": "12.57", "trail_percent": "10"},
            expected,
        )


def test_assert_leg_rejects_trailing_type() -> None:
    with pytest.raises(AssertionError, match="fixed"):
        assert_leg_matches_fixed(
            {"type": "trailing_stop", "stop_price": "12.57"},
            FixedStop(stop_price="12.57"),
        )


def test_build_trailing_stop_payload() -> None:
    body = build_trailing_stop(
        symbol="xlk",
        qty=10,
        protection=TrailingStop(trail_percent=Decimal("7")),
    )
    assert body == {
        "symbol": "XLK",
        "qty": "10",
        "side": "sell",
        "type": "trailing_stop",
        "time_in_force": "gtc",
        "trail_percent": "7",
    }


def test_cut_loser_steps_are_cancel_then_close() -> None:
    assert CUT_LOSER_STEPS == ("cancel", "close")


def test_trail_tighten_and_convert_steps_are_cancel_then_order() -> None:
    assert TRAIL_TIGHTEN_STEPS == ("cancel", "order")
    assert CONVERT_FIXED_TO_TRAIL_STEPS == ("cancel", "order")


def test_cli_oto_emits_valid_json() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(BUILD_OTO),
            "oto",
            "--symbol",
            "F",
            "--qty",
            "3",
            "--price",
            "13.97",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    body = json.loads(proc.stdout.strip())
    assert body["order_class"] == "oto"
    assert set(body["stop_loss"]) == {"stop_price"}


def _first_mutating_block(text: str, verbs: tuple[str, ...]) -> list[str]:
    """Ordered mutating alpaca.sh verbs in document order."""
    pattern = re.compile(
        r"alpaca\.sh\s+(" + "|".join(verbs) + r")\b"
    )
    return [m.group(1) for m in pattern.finditer(text)]


@pytest.mark.parametrize("path", MARKET_OPEN_WORKFLOWS, ids=lambda p: p.name)
def test_buy_path_uses_oto_not_naked_market_buy(path: Path) -> None:
    text = path.read_text()
    assert "order_class" in text or "build_oto_order.py oto" in text, (
        f"{path.name}: buy path must use OTO (ADR 0002)"
    )
    assert "build_oto_order.py" in text
    # Must not instruct a bare two-call market buy without OTO.
    bare = re.search(
        r"alpaca\.sh order '\{[^']*\"side\":\"buy\"[^']*\}'",
        text,
    )
    if bare:
        assert "order_class" in bare.group(0) or "oto" in bare.group(0).lower(), (
            f"{path.name}: bare buy order JSON must be OTO"
        )
    # Validate with stop-price for the fixed OTO leg (not trail-only on entry).
    assert "--stop-price" in text or "fixed_stop" in text or "build_oto_order.py oto" in text
    # Conversion to trailing still required after fill.
    assert "trailing_stop" in text or "build_oto_order.py trail" in text
    # T2 must stay unwired.
    assert "validate_stop_change" not in text
    assert "required_trail_percent" not in text


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_cut_is_cancel_then_close(path: Path) -> None:
    text = path.read_text()
    # Focus on STEP 3 cut block: first close/cancel pair in the cut section.
    step3 = text.split("STEP 4")[0]
    verbs = _first_mutating_block(step3, ("cancel", "close"))
    assert verbs, f"{path.name}: STEP 3 must cancel and close"
    # First cancel must precede first close (#38).
    assert verbs.index("cancel") < verbs.index("close"), (
        f"{path.name}: cut losers must be cancel-then-close, got {verbs}"
    )
    assert list(CUT_LOSER_STEPS) == ["cancel", "close"]


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_trail_tighten_cancel_before_replace(path: Path) -> None:
    text = path.read_text()
    step4 = text.split("STEP 4", 1)[1].split("STEP 5", 1)[0]
    verbs = _first_mutating_block(step4, ("cancel", "order"))
    assert verbs[:2] == list(TRAIL_TIGHTEN_STEPS), (
        f"{path.name}: trail tighten must be cancel-then-order, got {verbs}"
    )
    # Honest: PATCH not claimed; #40 still open.
    assert "validate_stop_change" not in text
