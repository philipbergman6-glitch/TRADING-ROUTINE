"""Daily accounting reconciliation: broker activities + closes rebuild equity, offline.

Research 0006 reconciled the paper account to the cent by hand once; these tests
pin that result (equity $103,282.35 at the 2026-09-18 close, fees -$0.46) and the
rules for what counts as an unexplained difference.
"""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest

from risk_engine.accounting import (
    DayRow, cash_after, holdings_after, parse_activities, rebuild_days, session_equity,
    unexplained,
)

FIXTURE = Path(__file__).parent / "fixtures" / "activities_through_2026-09-18.json"


def fill(i, t, sym, side, qty, price):
    return {"id": str(i), "activity_type": "FILL", "transaction_time": t, "symbol": sym,
            "side": side, "qty": str(qty), "price": str(price), "order_id": f"o{i}"}


def flow(i, kind, on, amount, **extra):
    return {"id": str(i), "activity_type": kind, "date": on, "net_amount": str(amount), **extra}


ROWS = [
    flow(1, "JNLC", "2026-04-17", "100000"),
    fill(2, "2026-04-28T13:30:00Z", "AMD", "buy", 10, "300"),
    fill(3, "2026-04-30T19:59:00Z", "AMD", "sell", 4, "310"),        # 15:59 ET, same session
    flow(4, "FEE", "2026-04-30", "-0.02", activity_sub_type="TAF"),
    fill(5, "2026-05-01T00:30:00Z", "XLK", "buy", 2, "100"),          # 20:30 ET Apr 30 -> Apr 30 session
]


def test_parse_splits_fills_from_cash_flows_and_dates_fills_in_eastern_time():
    fills, flows = parse_activities(ROWS)
    assert [(f.symbol, f.side, str(f.qty)) for f in fills] == [("AMD", "buy", "10"), ("AMD", "sell", "4"), ("XLK", "buy", "2")]
    assert [(c.kind, c.on.isoformat(), str(c.amount)) for c in flows] == [
        ("JNLC", "2026-04-17", "100000"), ("FEE", "2026-04-30", "-0.02")]
    assert cash_after(fills, flows) == Decimal("100000") - 3000 + 1240 - Decimal("0.02") - 200
    assert holdings_after(fills) == {"AMD": Decimal(6), "XLK": Decimal(2)}


def test_unknown_or_quantity_moving_activity_types_hard_fail():
    with pytest.raises(ValueError, match="JNLS"):
        parse_activities(ROWS + [flow(9, "JNLS", "2026-05-01", "0")])
    with pytest.raises(ValueError, match="missing"):
        parse_activities([{"id": "x", "activity_type": "FEE", "date": "2026-05-01"}])
    with pytest.raises(TypeError, match="float"):
        parse_activities([{"id": "x", "activity_type": "FEE", "date": "2026-05-01", "net_amount": -0.02}])


def test_session_equity_shifts_midnight_utc_points_back_one_day_and_drops_prefunding_zeros():
    # 1789776000 = 2026-09-19T00:00Z, which holds the 2026-09-18 close (research 0006).
    assert session_equity([1789689600, 1789776000], ["103631.88", "103282.35"]) == {
        date(2026, 9, 17): Decimal("103631.88"), date(2026, 9, 18): Decimal("103282.35")}
    assert session_equity([1789689600], ["0.0"]) == {}
    with pytest.raises(ValueError, match="length"):
        session_equity([1, 2], ["1"])


CLOSES = {("AMD", date(2026, 4, 28)): Decimal("305"), ("AMD", date(2026, 4, 29)): Decimal("301"),
          ("AMD", date(2026, 4, 30)): Decimal("311"), ("XLK", date(2026, 4, 30)): Decimal("99")}
BROKER = {date(2026, 4, 16): Decimal("100000"), date(2026, 4, 17): Decimal("100000"),
          date(2026, 4, 28): Decimal("100050"), date(2026, 4, 29): Decimal("100014"),
          date(2026, 4, 30): Decimal("100104")}


def test_rebuild_prices_held_lots_at_the_session_close_and_starts_at_the_first_cash_flow():
    fills, flows = parse_activities(ROWS)
    rows = rebuild_days(fills, flows, CLOSES, BROKER, tolerance=Decimal("1"), exceptions={})
    assert [r.session.isoformat() for r in rows] == ["2026-04-17", "2026-04-28", "2026-04-29", "2026-04-30"]
    apr30 = rows[-1]
    assert apr30 == DayRow(session=date(2026, 4, 30), cash=Decimal("98039.98"), holdings={"AMD": Decimal(6), "XLK": Decimal(2)},
                           market_value=Decimal("2064"), rebuilt=Decimal("100103.98"), broker=Decimal("100104"),
                           diff=Decimal("-0.02"), status="ok")
    assert [str(r.diff) for r in rows] == ["0", "0", "-4", "-0.02"]
    assert [r.status for r in rows] == ["ok", "ok", "UNEXPLAINED", "ok"]
    assert unexplained(rows) == ["2026-04-29: rebuilt 100010.00 vs broker 100014.00 (diff -4.00)"]


def test_a_recorded_exception_explains_a_difference_only_at_its_recorded_size():
    fills, flows = parse_activities(ROWS)
    known = {date(2026, 4, 29): ("broker snapshot carried a stale AMD mark", Decimal("-4"))}
    rows = rebuild_days(fills, flows, CLOSES, BROKER, Decimal("1"), known)
    assert rows[2].status == "explained: broker snapshot carried a stale AMD mark"
    assert unexplained(rows) == []
    drifted = {date(2026, 4, 29): ("stale mark", Decimal("-40"))}
    rows = rebuild_days(fills, flows, CLOSES, BROKER, Decimal("1"), drifted)
    assert rows[2].status == "UNEXPLAINED" and len(unexplained(rows)) == 1


def test_a_missing_close_for_a_held_symbol_is_an_error_not_a_zero():
    fills, flows = parse_activities(ROWS)
    closes = {k: v for k, v in CLOSES.items() if k != ("XLK", date(2026, 4, 30))}
    with pytest.raises(ValueError, match="no close for XLK on 2026-04-30"):
        rebuild_days(fills, flows, closes, BROKER, Decimal("1"), {})
    with pytest.raises(ValueError, match="no cash flows"):
        rebuild_days(fills, [], CLOSES, BROKER, Decimal("1"), {})


def test_research_0006_numbers_reproduce_from_broker_activities():
    fills, flows = parse_activities(json.loads(FIXTURE.read_text()))
    assert sum(c.amount for c in flows if c.kind == "FEE") == Decimal("-0.46")
    assert sum(c.amount for c in flows if c.kind == "JNLC") == Decimal("100000")
    assert holdings_after(fills) == {"XLB": Decimal(412), "XLE": Decimal(311), "XLK": Decimal(112), "XLP": Decimal(250)}
    sep18 = date(2026, 9, 18)
    closes = {("XLB", sep18): Decimal("49.99"), ("XLE", sep18): Decimal("64.31"),
              ("XLK", sep18): Decimal("189.6"), ("XLP", sep18): Decimal("82.8")}
    broker = session_equity([1789776000], ["103282.35"])
    rows = rebuild_days(fills, flows, closes, broker, Decimal("1"), {})
    assert len(rows) == 1 and rows[0].rebuilt == Decimal("103282.35") and rows[0].diff == 0
