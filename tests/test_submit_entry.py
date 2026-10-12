"""Idempotent entry: a rerun looks the buy up by its stable client id instead
of buying twice, and the outcome is always confirmed from broker state."""
from datetime import date, datetime, timezone
import json

import pytest

from scripts.replace_stop import EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, Outcome
from scripts.submit_entry import entry_client_id, submit_entry

DAY = date(2026, 9, 21)
NOW = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)


class FakeBroker:
    def __init__(self, existing=None, placed="new", http="200", fail_reads=False, fail_reads_after_submit=False):
        self.by_client = dict(existing or {})
        self.placed, self.http = placed, http
        self.fail_reads, self.fail_reads_after_submit = fail_reads, fail_reads_after_submit
        self.submitted = []
        self.positions, self.orders = [], []

    def read(self, command, arg=None):
        if self.fail_reads or (self.fail_reads_after_submit and self.submitted):
            raise SystemExit(4)
        if command == "positions":
            return self.positions
        if command == "orders":
            return self.orders
        assert command == "order-by-client"
        return self.by_client.get(arg)

    def run(self, command, arg):
        assert command == "order"
        body = json.loads(arg)
        self.submitted.append(body)
        if self.placed is None:
            return False, self.http, "", "REFUSED: pending buy exists" if self.http == "000" else "rejected"
        self.by_client[body["client_order_id"]] = {**body, "id": "broker-1", "status": self.placed}
        return True, self.http, "{}", ""


def body(cid="en-20260921-AMD"):
    return {"symbol": "AMD", "qty": "10", "side": "buy", "type": "market", "time_in_force": "gtc",
            "order_class": "oto", "stop_loss": {"stop_price": "93"}, "client_order_id": cid}


def outcome(broker, b=None):
    with pytest.raises(Outcome) as info:
        submit_entry(b or body(), read=broker.read, run=broker.run, now=NOW)
    return info.value


def test_client_id_is_derived_from_day_and_symbol():
    assert entry_client_id("amd", DAY) == "en-20260921-AMD"
    assert entry_client_id("AMD", DAY, "b") == "en-20260921-AMD-b"
    with pytest.raises(ValueError, match="tag"):
        entry_client_id("AMD", DAY, "bad tag")
    with pytest.raises(ValueError, match="broker-safe"):
        entry_client_id("BRK.B", DAY)


def test_submits_once_and_confirms_by_client_id():
    broker = FakeBroker()
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "submitted")
    assert broker.submitted[0]["client_order_id"] == "en-20260921-AMD"
    assert got.detail["order"]["id"] == "broker-1"


def test_rerun_finds_the_earlier_buy_and_does_not_submit():
    broker = FakeBroker(existing={"en-20260921-AMD": {"id": "broker-0", "status": "filled"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "already_submitted") and broker.submitted == []


def test_dead_earlier_order_does_not_block_a_fresh_submit():
    broker = FakeBroker(existing={"en-20260921-AMD": {"id": "broker-0", "status": "canceled"}})
    assert outcome(broker).state == "submitted" and len(broker.submitted) == 1


def test_gate_refusal_is_exit_3_with_nothing_submitted_to_the_broker():
    broker = FakeBroker(placed=None, http="000")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "refused") and "REFUSED" in got.detail["reason"]


def test_broker_4xx_is_a_refusal():
    broker = FakeBroker(placed=None, http="422")
    assert outcome(broker).code == EXIT_REFUSED


def test_broker_rejected_status_is_exit_3():
    broker = FakeBroker(placed="rejected")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "broker_rejected")


def test_unknown_outcome_after_submit_is_exit_8_and_rerun_resolves_it():
    broker = FakeBroker(placed=None, http="000")
    broker.run = lambda c, a: (False, "000", "", "adapter timed out; outcome unknown")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun")

    unreadable = FakeBroker(fail_reads_after_submit=True)
    assert outcome(unreadable).code == EXIT_UNPROTECTED


def test_unavailable_broker_before_submit_is_exit_4():
    got = outcome(FakeBroker(fail_reads=True))
    assert (got.code, got.state) == (EXIT_NO_STATE, "broker_state_unavailable")


# --- Exit codes derive from broker coverage, not from what this process did (#95) ---


def test_refused_add_to_a_held_position_with_no_verified_stop_is_an_incident():
    # The symbol is already held and nothing verifiably protects it: a refused add is
    # still an unprotected incident, whichever process lost the stop.
    broker = FakeBroker(placed=None, http="000")
    broker.positions = [{"symbol": "AMD", "qty": "10", "market_value": "1000"}]
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "refused_position_unprotected")
    assert got.detail["coverage"]["ok"] is False and "REFUSED" in got.detail["reason"]

    covered = FakeBroker(placed=None, http="000")
    covered.positions = [{"symbol": "AMD", "qty": "10", "market_value": "1000"}]
    covered.orders = [{"id": "s1", "symbol": "AMD", "side": "sell", "type": "trailing_stop", "qty": "10",
                       "filled_qty": "0", "status": "new", "stop_price": "90", "time_in_force": "gtc",
                       "expires_at": "2026-12-18T21:00:00Z"}]
    assert (outcome(covered).code, outcome(covered).state) == (EXIT_REFUSED, "refused")


def test_broker_rejected_add_to_an_unprotected_position_is_an_incident():
    broker = FakeBroker(placed="rejected")
    broker.positions = [{"symbol": "AMD", "qty": "10", "market_value": "1000"}]
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "broker_rejected_position_unprotected")
