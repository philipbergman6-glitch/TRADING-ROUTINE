from datetime import datetime, timezone
import pytest

from risk_engine.reconciliation import reconcile_protection

NOW = datetime(2026, 9, 17, 14, tzinfo=timezone.utc)
POSITIONS = [{"symbol": "AAPL", "qty": "10"}]


def stop(**changes):
    return {"id": "stop-1", "symbol": "AAPL", "side": "sell", "type": "stop",
            "status": "new", "qty": "10", "filled_qty": "0", "stop_price": "90",
            "time_in_force": "gtc", "expires_at": "2026-12-01T00:00:00Z", **changes}


def test_current_fixed_stop_is_coverage():
    report = reconcile_protection(POSITIONS, [stop()], NOW)
    assert report["ok"]
    assert report["positions"][0]["covered_qty"] == "10"


@pytest.mark.parametrize("changes", [{"status": "canceled"}, {"status": "held"},
                                       {"expires_at": "2026-09-16T00:00:00Z"},
                                       {"qty": "9"}, {"filled_qty": "1"}, {"time_in_force": "day"}])
def test_historical_acceptance_is_not_current_coverage(changes):
    assert not reconcile_protection(POSITIONS, [stop(**changes)], NOW)["ok"]


def test_duplicate_nested_order_is_not_double_counted():
    child = stop()
    report = reconcile_protection(POSITIONS, [{"id": "parent", "side": "buy", "legs": [child]}, child], NOW)
    assert report["ok"]
    assert report["positions"][0]["covered_qty"] == "10"


def test_two_stops_for_full_position_are_flagged():
    assert not reconcile_protection(POSITIONS, [stop(), stop(id="stop-2")], NOW)["ok"]


def test_short_position_is_an_incident():
    assert not reconcile_protection([{"symbol": "AAPL", "qty": "-1"}], [], NOW)["ok"]


def test_incomplete_order_cannot_certify_coverage():
    assert not reconcile_protection(POSITIONS, [stop(expires_at=None)], NOW)["ok"]
