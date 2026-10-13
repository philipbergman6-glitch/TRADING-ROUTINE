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
                      portfolio=PortfolioState(equity="100000", cash="100000", is_paper=True, reservations=(), **state))


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


@pytest.mark.parametrize("timestamp", [
    "2026-09-17T14:00:00.112598Z",   # #155: host clock 0.11 s behind the broker's
    "2026-09-17T14:00:05Z",          # host clock behind by exactly the allowed skew
    "2026-09-17T13:59:00Z",          # 60 s old
])
def test_fresh_quote_passes_within_the_clock_skew(snapshot, timestamp):
    snapshot[("quote", "AAPL")]["quote"]["t"] = timestamp
    check(order(), snapshot)


@pytest.mark.parametrize("timestamp,reason", [
    ("2026-09-17T13:58:59Z", "no more than 60 seconds old"),
    ("2026-09-17T14:00:05.001Z", "ahead of the host clock"),
    ("2026-09-17T14:00:00", "quote"),
])
def test_stale_future_or_naive_quote_refuses(snapshot, timestamp, reason):
    snapshot[("quote", "AAPL")]["quote"]["t"] = timestamp
    with pytest.raises(ValueError, match=reason):
        check(order(), snapshot)


def test_actual_resting_stop_is_not_lowered(snapshot):
    snapshot[("orders", "open")] = [{"symbol": "AAPL", "side": "sell", "stop_price": "117"}]
    snapshot[("orders", "closed", "2026-09-17T13:45:00Z")] = []
    with pytest.raises(ValueError, match="stop_never_lowered"):
        check({"symbol": "AAPL", "qty": "100", "side": "sell", "type": "trailing_stop",
               "time_in_force": "gtc", "trail_percent": "5"}, snapshot,
              positions=(Position("AAPL", "100", "12000"),))


@pytest.mark.parametrize("command", ["cancel-all", "close-all"])
def test_bulk_actions_fail_before_broker_reads(command):
    with pytest.raises(ValueError, match="bulk"):
        validate_mutation(command, "", read=lambda *args: pytest.fail("unexpected read"))


# ---- version binding (ADR 0011): an unbound runner may not trade ----------------

@pytest.mark.parametrize("env", [None, "", "V1", "v2"])
def test_unbound_runner_cannot_buy(snapshot, monkeypatch, env):
    if env is None:
        monkeypatch.delenv("STRATEGY_VERSION")
    else:
        monkeypatch.setenv("STRATEGY_VERSION", env)
    with pytest.raises(ValueError, match="version binding"):
        check(order(), snapshot)


@pytest.mark.parametrize("command,argument", [("close", "AAPL"), ("cancel", "abc-1")])
def test_unbound_runner_cannot_close_or_cancel(monkeypatch, command, argument):
    monkeypatch.delenv("STRATEGY_VERSION")
    with pytest.raises(ValueError, match="version binding"):
        validate_mutation(command, argument, read=lambda *a: pytest.fail("refused before broker reads"))


def test_unreadable_pins_refuse_every_mutation(snapshot, monkeypatch, tmp_path):
    from scripts import strategy_version
    monkeypatch.setattr(strategy_version, "PINS_FILE", tmp_path / "missing.json")
    with pytest.raises(ValueError, match="pins unreadable"):
        check(order(), snapshot)
