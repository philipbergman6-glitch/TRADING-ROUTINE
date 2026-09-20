"""Protection monitor: planning is pure and version-aware; execution drives
replace_stop and never invents a cancel/place pair."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from risk_engine import V1, V2
from risk_engine.monitor import plan_protection
from scripts.protection_monitor import EXIT_ISSUES, execute, worst_exit
from scripts.replace_stop import EXIT_OK, EXIT_RESTORED, EXIT_UNPROTECTED, Outcome

NOW = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
FAR = (NOW + timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%SZ")
SOON = (NOW + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


def position(symbol, qty="100", entry="100", price="100"):
    return {"symbol": symbol, "qty": qty, "avg_entry_price": entry, "current_price": price,
            "market_value": str(Decimal(qty) * Decimal(price))}


def stop(oid, symbol, kind, level, qty="100", trail=None, expires=FAR, status="new"):
    return {"id": oid, "symbol": symbol, "side": "sell", "type": kind, "status": status, "qty": qty,
            "filled_qty": "0", "stop_price": level, "trail_percent": trail, "expires_at": expires,
            "time_in_force": "gtc"}


def test_covered_book_with_nothing_due_is_a_no_op():
    plan = plan_protection([position("AMD")], [stop("s1", "AMD", "trailing_stop", "90", trail="10")], NOW)
    assert plan.actions == [] and plan.holds == [] and plan.coverage["ok"]


def test_uncovered_position_is_an_issue_not_an_action():
    plan = plan_protection([position("AMD")], [], NOW)
    assert plan.coverage["ok"] is False and "AMD" in plan.coverage["issues"][0]
    assert worst_exit(plan, []) == EXIT_ISSUES


def test_expiring_stop_is_renewed_at_its_level_rounded_up():
    plan = plan_protection([position("XLB", price="50")],
                           [stop("s1", "XLB", "stop", "48.781", expires=SOON)], NOW)
    assert [(a.kind, str(a.stop_price)) for a in plan.actions] == [("renew", "48.79")]


def test_v1_converts_leftover_fixed_leg_when_trail_would_not_lower():
    plan = plan_protection([position("AMD", entry="100", price="101")],
                           [stop("s1", "AMD", "stop", "90")], NOW, V1)
    assert [(a.kind, str(a.trail_percent)) for a in plan.actions] == [("convert", "10")]


def test_v1_holds_fixed_leg_when_conversion_would_lower_it():
    plan = plan_protection([position("XLB", entry="52", price="50")],
                           [stop("s1", "XLB", "stop", "48.78")], NOW, V1)
    assert plan.actions == [] and "HOLD fixed 48.78" in plan.holds[0]
    assert "inside the 3% minimum" in plan.standing[0]


def test_v2_converts_only_once_gain_reaches_threshold():
    below = plan_protection([position("AMD", entry="100", price="104")],
                            [stop("s1", "AMD", "stop", "93")], NOW, V2)
    assert below.actions == [] and "below v2 conversion threshold 5%" in below.holds[0]
    above = plan_protection([position("AMD", entry="100", price="105")],
                            [stop("s1", "AMD", "stop", "93")], NOW, V2)
    assert [(a.kind, str(a.trail_percent)) for a in above.actions] == [("convert", "10")]


@pytest.mark.parametrize("params, price, expected", [
    (V1, "116", "7"), (V1, "121", "5"), (V2, "121", "7"), (V2, "114", None)])
def test_tighten_follows_the_version_ladder(params, price, expected):
    plan = plan_protection([position("MU", entry="100", price=price)],
                           [stop("s1", "MU", "trailing_stop", str(Decimal(price) * Decimal("0.9")), trail="10")],
                           NOW, params)
    got = [(a.kind, str(a.trail_percent)) for a in plan.actions]
    assert got == ([("tighten", expected)] if expected else [])


def test_tighten_never_lowers_below_resting_stop():
    # Resting trail already sits at 112 (high-water mark 124.4); mark fell to 116.
    plan = plan_protection([position("MU", entry="100", price="116")],
                           [stop("s1", "MU", "trailing_stop", "112", trail="10")], NOW, V1)
    assert plan.actions == [] and "tighten to 7% refused" in plan.holds[0]


def test_renewal_takes_precedence_over_tightening_this_run():
    plan = plan_protection([position("MU", entry="100", price="116")],
                           [stop("s1", "MU", "trailing_stop", "104.4", trail="10", expires=SOON)], NOW)
    assert [a.kind for a in plan.actions] == ["renew"]


def test_position_missing_price_fields_is_an_error():
    with pytest.raises(ValueError, match="missing"):
        plan_protection([{"symbol": "AMD", "qty": "1"}], [], NOW)


def test_execute_reruns_unprotected_then_reports_worst_exit():
    plan = plan_protection([position("AMD", price="101")], [stop("s1", "AMD", "stop", "90")], NOW)
    calls = []
    outcomes = iter([Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed"), Outcome(EXIT_OK, "replaced")])

    def replace(order_id, trail_percent=None, stop_price=None):
        calls.append((order_id, trail_percent, stop_price))
        raise next(outcomes)

    results = execute(plan, replace=replace)
    assert len(calls) == 2 and calls[0] == ("s1", Decimal("10"), None)
    assert results[0]["state"] == "replaced" and worst_exit(plan, results) == 0

    def restored(*_a, **_k):
        raise Outcome(EXIT_RESTORED, "replacement_failed_old_level_restored")

    assert worst_exit(plan, execute(plan, replace=restored)) == EXIT_RESTORED

    def never(*_a, **_k):
        raise Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed")

    assert worst_exit(plan, execute(plan, replace=never, reruns=2)) == EXIT_UNPROTECTED
