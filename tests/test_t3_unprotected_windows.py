"""T3: close unprotected windows — OTO buy (ADR 0002) + cancel-then-act order (#38).

T2 trail validators (#32) are wired on midday separately; T3 must not
regress them. Does NOT start T4 ledger.record_decision.
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
    is_leftover_fixed_stop,
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

# On-entry fixed→trail convergence (ADR 0002) — market-open + midday (not /trade).
CONVERGENCE_WORKFLOWS = (
    REPO / "routines" / "market-open.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / "routines" / "midday.md",
    REPO / ".claude" / "commands" / "midday.md",
)

PARTIAL_FILL_WORKFLOWS = (
    REPO / "routines" / "market-open.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / ".claude" / "commands" / "trade.md",
)

TRADE_WORKFLOW = REPO / ".claude" / "commands" / "trade.md"


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
    assert "order_class" in text or "build_oto_order.py oto" in text or "submit_entry.py" in text, (
        f"{path.name}: buy path must use OTO (ADR 0002)"
    )
    assert "build_oto_order.py" in text
    # Buys go through the idempotent entry script, never a hand-written order call.
    assert "submit_entry.py --symbol SYM --qty N --price P" in text
    assert "alpaca.sh order \"$OTO_JSON\"" not in text
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
    # Conversion to trailing still required after fill — via the resumable replacer.
    assert "replace_stop.py --order-id LEG_ORDER_ID --trail-percent 10" in text
    # Market-open /trade buy path is not the midday trail-tighten CLI (T2). The
    # fixed-price path (--current-stop/--new-stop) is allowed: STEP 2b uses it to
    # refuse a convert that would lower the stop.
    if "midday" not in path.name:
        assert "--gain-pct" not in text and "--proposed-trail" not in text


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_cut_is_cancel_then_close(path: Path) -> None:
    text = path.read_text()
    # Focus on STEP 3 cut block: first close/cancel pair in the cut section.
    step3 = text.split("STEP 4")[0]
    # cancel→close (CUT_LOSER_STEPS) happens inside close_position.py with
    # each step confirmed from broker state; a hand-written pair would lose
    # preflight, cancel confirmation and resume.
    assert _first_mutating_block(step3, ("cancel", "close")) == [], (
        f"{path.name}: STEP 3 must not hand-write cancel/close"
    )
    assert "close_position.py --symbol SYM" in step3, f"{path.name}: STEP 3 must use close_position.py"
    assert "cancel-then-close" in step3
    assert list(CUT_LOSER_STEPS) == ["cancel", "close"]


@pytest.mark.parametrize("path", MIDDAY_WORKFLOWS, ids=lambda p: p.name)
def test_midday_trail_tighten_cancel_before_replace(path: Path) -> None:
    text = path.read_text()
    step4 = text.split("STEP 4", 1)[1].split("STEP 5", 1)[0]
    # cancel→order (TRAIL_TIGHTEN_STEPS) happens inside replace_stop.py; a
    # hand-written pair would lose preflight, cancel confirmation and resume.
    assert _first_mutating_block(step4, ("cancel", "order")) == []
    assert "replace_stop.py --order-id ORDER_ID --trail-percent T" in step4
    assert list(TRAIL_TIGHTEN_STEPS) == ["cancel", "order"]
    # Honest: PATCH not claimed; #40 still open. T2 wires validators; does not PATCH.
    assert "#40" in step4
    assert step4.index("validate_stop_change.py") < step4.index("replace_stop.py")


def test_is_leftover_fixed_stop_detects_fixed_sell() -> None:
    assert is_leftover_fixed_stop(
        {"side": "sell", "type": "stop", "status": "new", "stop_price": "12.57",
         "trail_percent": None}
    )
    assert not is_leftover_fixed_stop(
        {"side": "sell", "type": "trailing_stop", "status": "new", "trail_percent": "10"}
    )
    assert not is_leftover_fixed_stop(
        {"side": "buy", "type": "stop", "status": "new", "stop_price": "12.57"}
    )
    assert not is_leftover_fixed_stop(
        {"side": "sell", "type": "stop", "status": "canceled", "stop_price": "12.57"}
    )
    assert not is_leftover_fixed_stop(
        {"side": "sell", "type": "stop", "status": "new", "stop_price": "12.57",
         "trail_percent": "10"}
    )


@pytest.mark.parametrize("path", CONVERGENCE_WORKFLOWS, ids=lambda p: str(p.relative_to(REPO)))
def test_on_entry_converges_leftover_fixed_stops(path: Path) -> None:
    """ADR 0002: scan leftover fixed legs and convert — not wishful 'next routine'."""
    text = path.read_text()
    assert "leftover" in text.lower() or "converg" in text.lower(), (
        f"{path}: must name leftover/convergence on entry"
    )
    assert "type" in text and "stop" in text
    # Must instruct cancel→trail conversion for leftovers (not buy-path only).
    assert "replace_stop.py --order-id ORDER_ID --trail-percent 10" in text
    # Explicit scan of open orders — not only happy-path convert after fill.
    assert "orders" in text.lower()
    assert list(CONVERT_FIXED_TO_TRAIL_STEPS) == ["cancel", "order"]


@pytest.mark.parametrize("path", PARTIAL_FILL_WORKFLOWS, ids=lambda p: str(p.relative_to(REPO)))
def test_partial_fill_is_hard_fail_incident(path: Path) -> None:
    """ADR 0002 / quant: filled_qty != qty is incident BEFORE any convert."""
    text = path.read_text()
    assert "filled_qty" in text, f"{path.name}: must check filled_qty"
    assert "incident" in text.lower(), f"{path.name}: partial fill must be an incident"
    hard = (
        "hard-fail" in text.lower()
        or "hard fail" in text.lower()
        or "filled_qty != qty" in text
        or "filled_qty != " in text
    )
    assert hard, f"{path.name}: must hard-fail when filled_qty != qty"
    # Gate before convert: filled_qty known + leg match; no assume-protected.
    low = text.lower()
    assert "leg" in low, f"{path.name}: must require leg match before convert"
    assert "do not convert" in low or "only after" in low or "gate before" in low, (
        f"{path.name}: must gate convert on fill+leg"
    )
    # Ordering inside the buy/OTO path (after entry submit): filled_qty before convert.
    # Ignore on-entry leftover convergence (STEP 2b), which also names CONVERT_*.
    buy_idx = text.find("order_class=oto")
    if buy_idx < 0:
        buy_idx = text.find("build_oto_order.py oto")
    if buy_idx < 0:
        buy_idx = text.find("submit_entry.py --symbol")
    assert buy_idx >= 0, f"{path.name}: buy OTO path missing"
    buy_path = text[buy_idx:]
    fq = buy_path.find("filled_qty")
    convert_markers = [
        i for i in (
            buy_path.find("STEP 5"),
            buy_path.find("CONVERT_FIXED_TO_TRAIL_STEPS"),
            buy_path.lower().find("convert the fixed"),
            buy_path.lower().find("convert only after"),
        )
        if i >= 0
    ]
    assert fq >= 0 and convert_markers, f"{path.name}: need filled_qty and convert in buy path"
    assert fq < min(convert_markers), (
        f"{path.name}: filled_qty hard-fail must appear BEFORE convert in buy path"
    )
    # Residual uncovered / assume-protected forbidden.
    assert (
        "residual" in low
        or "uncovered" in low
        or "do not assume" in low
        or "assume protected" in low
        or "assuming" in low
    ), f"{path.name}: must forbid assume-protected / residual uncovered"


@pytest.mark.parametrize("path", PARTIAL_FILL_WORKFLOWS, ids=lambda p: str(p.relative_to(REPO)))
def test_convert_keeps_cancel_confirm_retry_query(path: Path) -> None:
    """Keep cancel-confirm + trail retry + email on fail + query before protected."""
    text = path.read_text().lower()
    assert "rerun the same command" in text, f"{path.name}: resumable rerun required"
    assert "email" in text, f"{path.name}: email on convert fail required"
    assert "query" in text or "queryable" in text, f"{path.name}: query before protected"
    # Honesty: #40 still open — windows not fully closed.
    full = path.read_text()
    assert "#40" in full and "OPEN" in full, f"{path.name}: #40 must stay OPEN honesty"


def test_trade_sell_is_cancel_then_close() -> None:
    """#38: /trade sell must mirror midday cancel→close (not close-then-cancel)."""
    text = TRADE_WORKFLOW.read_text()
    # Isolate the SELL instruction block (before BUY convert / trailing section).
    sell_idx = text.lower().find("sell of a protected")
    if sell_idx < 0:
        sell_idx = text.upper().find("SELL")
    assert sell_idx >= 0, "trade.md must document SELL of protected position"
    # Take from SELL mention through the next numbered step that is BUY convert,
    # or a reasonable window of the sell instructions.
    chunk = text[sell_idx : sell_idx + 600]
    # The pair lives inside close_position.py (confirmed cancel, then sell);
    # a hand-written pair in the prompt would lose confirmation and resume.
    assert _first_mutating_block(chunk, ("cancel", "close")) == [], "trade.md must not hand-write cancel/close"
    assert "close_position.py --symbol SYM" in chunk, "trade.md SELL path must use close_position.py"
    assert "cancel-then-close" in chunk
    assert list(CUT_LOSER_STEPS) == ["cancel", "close"]
    # Honesty: do not claim #40 PATCH closed.
    assert "#40" in text and "OPEN" in text


# --- stop expiry renewal (GTC ~90d) -------------------------------------------


def _open_stop(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "o1", "symbol": "xlb", "qty": "412", "side": "sell",
        "type": "trailing_stop", "status": "new", "stop_price": "48.771",
        "trail_percent": "10", "expires_at": "2026-09-25T20:00:00Z",
    }
    base.update(over)
    return base


def test_expiring_stops_flags_within_window_and_rounds_level_up() -> None:
    from datetime import datetime, timezone

    from risk_engine import expiring_protective_stops

    now = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)
    due = expiring_protective_stops(
        [
            _open_stop(),
            _open_stop(id="o2", symbol="XLK", expires_at="2026-11-06T21:00:00Z"),
            _open_stop(id="o3", side="buy"),
            _open_stop(id="o4", status="filled"),
            _open_stop(id="o5", type="limit"),
        ],
        now,
        10,
    )
    assert due == [
        {
            "order_id": "o1", "symbol": "XLB", "qty": "412", "type": "trailing_stop",
            "expires_at": "2026-09-25T20:00:00Z", "renew_stop_price": "48.78",
        }
    ]


def test_expiring_stops_hard_fails_on_missing_fields() -> None:
    from datetime import datetime, timezone

    from risk_engine import expiring_protective_stops

    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="expires_at"):
        expiring_protective_stops([_open_stop(expires_at=None)], now)
    with pytest.raises(ValueError, match="timezone"):
        expiring_protective_stops([], datetime(2026, 9, 16))


def test_build_fixed_stop_payload_has_no_trail_fields() -> None:
    from risk_engine import build_fixed_stop

    body = build_fixed_stop(symbol="xlb", qty=412, protection=FixedStop(stop_price="48.78"))
    assert body == {
        "symbol": "XLB", "qty": "412", "side": "sell", "type": "stop",
        "time_in_force": "gtc", "stop_price": "48.78",
    }
    assert is_leftover_fixed_stop({**body, "status": "new"})


def test_renew_steps_are_cancel_then_order() -> None:
    from risk_engine import RENEW_EXPIRING_STOP_STEPS

    assert RENEW_EXPIRING_STOP_STEPS == ("cancel", "order")


@pytest.mark.parametrize(
    "path",
    (REPO / "routines" / "midday.md", REPO / ".claude" / "commands" / "midday.md"),
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_midday_renews_expiring_stops_as_fixed(path: Path) -> None:
    text = path.read_text()
    assert "build_oto_order.py expiring" in text
    renew = text[text.index("STEP 2c"):text.index("STEP 3 — ")]
    # Fixed replacement at the rounded-up level, through the resumable replacer.
    assert "replace_stop.py --order-id ORDER_ID --stop-price RENEW_STOP_PRICE" in renew
    assert _first_mutating_block(renew, ("cancel", "order")) == []
    assert "--kind stop" in renew


@pytest.mark.parametrize("path", CONVERGENCE_WORKFLOWS, ids=lambda p: str(p.relative_to(REPO)))
def test_convergence_gated_so_stop_never_moves_down(path: Path) -> None:
    text = path.read_text()
    step = text[text.index("STEP 2b"):text.index("STEP 3 — ")]
    gate = step.index("validate_stop_change.py --current-stop")
    assert gate < step.index("replace_stop.py --order-id"), "gate must run before the replacement"
    assert "HOLD" in step and "stop_never_lowered" in step


@pytest.mark.parametrize("path", MARKET_OPEN_WORKFLOWS + MIDDAY_WORKFLOWS, ids=lambda p: str(p.relative_to(REPO)))
def test_no_hand_written_stop_replacement(path: Path) -> None:
    """A cancel followed by an order is a stop replacement; only replace_stop.py may do it."""
    verbs = _first_mutating_block(path.read_text(), ("cancel", "order", "close"))
    for first, second in zip(verbs, verbs[1:]):
        assert (first, second) != ("cancel", "order"), f"{path.name}: use scripts/replace_stop.py"
