"""Exercise payload validation with complete offline broker snapshots."""
from datetime import datetime, timezone
import json

import pytest

from risk_engine import PortfolioState, Position
from scripts.validate_mutation import validate_mutation

NOW = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def snapshot():
    return {
        ("asset", "AAPL"): {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True},
        ("orders", "open"): [],
        ("quote", "AAPL"): {"quote": {"ap": "100.00", "t": "2026-09-17T14:00:00Z"}},
    }


def order(**changes):
    return {"symbol": "AAPL", "qty": "100", "side": "buy", "type": "market",
            "time_in_force": "gtc", "order_class": "oto", "stop_loss": {"stop_price": "90"}, **changes}


def check(body, snapshot, **state):
    validate_mutation("order", json.dumps(body),
                      read=lambda *args: snapshot[args], now=NOW,
                      portfolio=PortfolioState(equity="100000", cash="100000", is_paper=True, **state))


def test_exact_valid_oto_is_accepted(snapshot):
    check(order(), snapshot)


@pytest.mark.parametrize("change,reason", [
    ({"qty": "201"}, "max_position_pct"),
    ({"order_class": "simple"}, "OTO"),
    ({"stop_loss": {"stop_price": "1"}}, "stop_distance"),
    ({"stop_loss": {"stop_price": "90", "trail_percent": "10"}}, "fixed stop_loss"),
    ({"extended_hours": True}, "unsupported order fields"),
    ({"time_in_force": "day"}, "GTC"),
])
def test_changed_payload_cannot_reuse_an_approval(snapshot, change, reason):
    check(order(), snapshot)
    with pytest.raises(ValueError, match=reason):
        check(order(**change), snapshot)


def test_broker_class_is_checked_even_for_stock_shaped_symbol(snapshot):
    snapshot[("asset", "AAPL")]["class"] = "crypto"
    with pytest.raises(ValueError, match="US equity"):
        check(order(), snapshot)


def test_pending_buy_blocks_additional_commitment(snapshot):
    snapshot[("orders", "open")] = [{"side": "buy", "symbol": "MSFT"}]
    with pytest.raises(ValueError, match="pending buy"):
        check(order(), snapshot)


@pytest.mark.parametrize("timestamp", ["2026-09-17T13:58:00Z", "2026-09-17T14:00:01Z", "2026-09-17T14:00:00"])
def test_stale_future_or_naive_quote_refuses(snapshot, timestamp):
    snapshot[("quote", "AAPL")]["quote"]["t"] = timestamp
    with pytest.raises(ValueError, match="quote"):
        check(order(), snapshot)


def test_actual_resting_stop_is_not_lowered(snapshot):
    snapshot[("orders", "open")] = [{"symbol": "AAPL", "side": "sell", "stop_price": "117"}]
    with pytest.raises(ValueError, match="stop_never_lowered"):
        check({"symbol": "AAPL", "qty": "100", "side": "sell", "type": "trailing_stop",
               "time_in_force": "gtc", "trail_percent": "5"}, snapshot,
              positions=(Position("AAPL", "100", "12000"),))


@pytest.mark.parametrize("command", ["cancel-all", "close-all"])
def test_bulk_actions_fail_before_broker_reads(command):
    with pytest.raises(ValueError, match="bulk"):
        validate_mutation(command, "", read=lambda *args: pytest.fail("unexpected read"))
