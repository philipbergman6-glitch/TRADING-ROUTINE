"""Recovered exit: cancel -> close with every step confirmed from broker
state, resumable through a stable client id, and never a naked position
without an exit-8 incident."""
from datetime import datetime, timezone
import json

import pytest

from scripts.close_position import close_client_id, close_position
from scripts.replace_stop import EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, EXIT_USAGE, Outcome

NOW = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)
STOP = "aaaa-1111"
CID = "cl-20260921-AMD"


class FakeBroker:
    def __init__(self, held=True, stop_status="new", cancel_to="canceled", close="new", close_http="200",
                 existing=None, fail_reads_after_cancel=False, refuse=False):
        self.positions = [{"symbol": "AMD", "qty": "10", "market_value": "1000"}] if held else []
        self.orders = {STOP: {"id": STOP, "symbol": "AMD", "side": "sell", "type": "trailing_stop",
                              "qty": "10", "filled_qty": "0", "status": stop_status}} if stop_status else {}
        self.by_client = dict(existing or {})
        self.cancel_to, self.close, self.close_http = cancel_to, close, close_http
        self.fail_reads_after_cancel, self.refuse = fail_reads_after_cancel, refuse
        self.calls = []

    def read(self, command, *args):
        if self.fail_reads_after_cancel and any(c[:2] == ("run", "cancel") for c in self.calls):
            raise SystemExit(4)
        if command == "positions":
            return self.positions
        if command == "orders":
            return [o for o in self.orders.values()]
        if command == "order-info":
            return self.orders[args[0]]
        if command == "order-by-client":
            return self.by_client.get(args[0])
        raise AssertionError(command)

    def run(self, command, arg):
        self.calls.append(("run", command, arg))
        if command == "cancel":
            self.orders[arg]["status"] = self.cancel_to
            if self.cancel_to == "filled":
                self.positions = []
            return True, "204", "", ""
        body = json.loads(arg)
        if self.close is None:
            return False, self.close_http, "", "rejected"
        self.by_client[body["client_order_id"]] = {**body, "id": "close-1", "status": self.close}
        return True, self.close_http, "{}", ""

    def check(self, command, body):
        self.calls.append(("check", command, body))
        if self.refuse:
            raise ValueError("paper account required")

    def posted(self):
        return [json.loads(c[2]) for c in self.calls if c[:2] == ("run", "order")]


def outcome(broker, symbol="AMD"):
    with pytest.raises(Outcome) as info:
        close_position(symbol, NOW, read=broker.read, run=broker.run, check=broker.check, sleep=lambda _s: None)
    return info.value


def test_client_id_is_stable_per_day_and_symbol():
    assert close_client_id("amd", NOW.date()) == CID


def test_happy_path_preflights_cancels_then_sells_with_client_id():
    broker = FakeBroker()
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_submitted")
    assert broker.calls[0][:2] == ("check", "order") and broker.calls[1][:2] == ("run", "cancel")
    sold = broker.posted()[0]
    assert sold == {"symbol": "AMD", "qty": "10", "side": "sell", "type": "market",
                    "time_in_force": "gtc", "client_order_id": CID}
    assert got.detail["stops_canceled"] == [STOP]


def test_rerun_after_a_submitted_close_does_nothing():
    broker = FakeBroker(existing={CID: {"id": "close-0", "status": "filled"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "already_closed") and broker.calls == []


def test_refused_preflight_leaves_the_stop_resting():
    broker = FakeBroker(refuse=True)
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "refused")
    assert broker.orders[STOP]["status"] == "new" and broker.posted() == []


def test_stop_that_fills_during_cancel_means_position_gone():
    got = outcome(FakeBroker(cancel_to="filled"))
    assert (got.code, got.state) == (EXIT_OK, "stop_filled_position_gone")


def test_cancel_rejected_keeps_protection_and_refuses():
    broker = FakeBroker(cancel_to="new")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "cancel_rejected_stop_still_protects") and broker.posted() == []


def test_cancel_unconfirmed_is_an_incident():
    got = outcome(FakeBroker(cancel_to="pending_cancel"))
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "cancel_unconfirmed")


def test_close_rejected_after_cancel_is_naked_incident_and_rerun_resumes():
    broker = FakeBroker(close=None, close_http="422")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "close_failed_position_naked_rerun")
    # Rerun: the stop is gone; only the sell is resubmitted.
    broker.close = "new"
    again = outcome(broker)
    assert again.state == "close_submitted" and [c[1] for c in broker.calls].count("cancel") == 1


def test_naked_position_without_a_stop_is_still_closed():
    broker = FakeBroker(stop_status=None)
    got = outcome(broker)
    assert got.state == "close_submitted" and got.detail["stops_canceled"] == []
    assert [c[:2] for c in broker.calls] == [("check", "order"), ("run", "order")]


def test_no_position_is_usage_error():
    got = outcome(FakeBroker(held=False, stop_status=None))
    assert (got.code, got.state) == (EXIT_USAGE, "no_position")
    orphan = outcome(FakeBroker(held=False))
    assert (orphan.code, orphan.state) == (EXIT_USAGE, "no_position_but_stop_resting")


def test_unavailable_state_after_cancel_is_incident_before_is_exit_4():
    got = outcome(FakeBroker(fail_reads_after_cancel=True))
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "broker_state_unavailable_rerun_to_resume")

    broker = FakeBroker()
    broker.read = lambda *_a: (_ for _ in ()).throw(SystemExit(4))
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_NO_STATE, "broker_state_unavailable")
