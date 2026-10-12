"""Recovered exit: cancel -> close with every step confirmed from broker
state, resumable through a stable client id, and never a naked position
without an exit-8 incident."""
from datetime import datetime, timezone
import json

import pytest

from scripts.close_position import close_position
from scripts.execution_identity import MAX_RETRIES, attempt_id, mint_intent
from scripts.replace_stop import EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, EXIT_USAGE, Outcome

NOW = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)
STOP = "aaaa-1111"
CID = "cl-20260921-AMD"


class FakeBroker:
    def __init__(self, held=True, stop_status="new", cancel_to="canceled", close="new", close_http="200",
                 existing=None, fail_reads_after_cancel=False, refuse=False, cancel_ok=True, buys=(),
                 remainder=None):
        self.positions = [{"symbol": "AMD", "qty": "10", "market_value": "1000"}] if held else []
        # Full broker shape: coverage is verified through risk_engine.reconciliation,
        # which needs an unexpired GTC stop with a price and remaining quantity.
        self.orders = {STOP: {"id": STOP, "symbol": "AMD", "side": "sell", "type": "trailing_stop",
                              "qty": "10", "filled_qty": "0", "status": stop_status, "stop_price": "95",
                              "time_in_force": "gtc", "expires_at": "2026-12-18T21:00:00Z"}} if stop_status else {}
        for i, status in enumerate(buys):
            self.orders[f"buy-{i}"] = {"id": f"buy-{i}", "client_order_id": f"en-20260921-AMD-{i + 2}",
                                       "symbol": "AMD", "side": "buy", "type": "market", "qty": "5",
                                       "status": status}
        self.remainder = remainder
        self.by_client = dict(existing or {})
        self.cancel_to, self.close, self.close_http = cancel_to, close, close_http
        self.fail_reads_after_cancel, self.refuse, self.cancel_ok = fail_reads_after_cancel, refuse, cancel_ok
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
            if not self.cancel_ok:
                return False, "422", "", "order is not cancelable"
            self.orders[arg]["status"] = self.cancel_to
            if self.cancel_to == "filled":
                self.positions = ([{"symbol": "AMD", "qty": self.remainder, "market_value": "500"}]
                                  if self.remainder else [])
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


def outcome(broker, symbol="AMD", now=NOW, intent=None):
    with pytest.raises(Outcome) as info:
        close_position(symbol, now, intent=intent, read=broker.read, run=broker.run, check=broker.check,
                       sleep=lambda _s: None)
    return info.value


def test_intent_is_minted_per_day_and_symbol():
    assert mint_intent("cl", "amd", NOW.date()) == CID


def test_happy_path_preflights_cancels_then_sells_with_client_id():
    broker = FakeBroker()
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_submitted")
    assert broker.calls[0][:2] == ("check", "order") and broker.calls[1][:2] == ("run", "cancel")
    sold = broker.posted()[0]
    assert sold == {"symbol": "AMD", "qty": "10", "side": "sell", "type": "market",
                    "time_in_force": "gtc", "client_order_id": CID}
    assert got.detail["stops_canceled"] == [STOP]


def test_repeated_close_after_a_filled_exit_is_complete_only_because_holdings_are_zero():
    broker = FakeBroker(held=False, stop_status=None, existing={CID: {"id": "close-0", "status": "filled"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_complete") and broker.calls == []
    assert got.detail["client_order_id"] == CID and got.detail["intent"] == CID


def test_refused_preflight_leaves_the_stop_resting():
    broker = FakeBroker(refuse=True)
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "refused")
    assert broker.orders[STOP]["status"] == "new" and broker.posted() == []


def test_stop_that_fills_during_cancel_means_position_gone():
    got = outcome(FakeBroker(cancel_to="filled"))
    assert (got.code, got.state) == (EXIT_OK, "stop_filled_position_gone")


def test_broker_refused_cancel_keeps_protection_and_refuses():
    broker = FakeBroker(cancel_ok=False)
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "cancel_rejected_stop_still_protects") and broker.posted() == []


def test_accepted_cancel_still_open_after_full_window_is_an_incident():
    broker = FakeBroker(cancel_to="new")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "cancel_accepted_but_unconfirmed_rerun")
    assert broker.posted() == [] and got.detail["polled_seconds"] == 20


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


def test_dead_prior_close_is_not_reused_rerun_sells_under_retry_id():
    # An earlier run's close was recorded by the broker as rejected and the stop is
    # already gone. Reusing cl-... would be refused as a duplicate forever (naked loop).
    broker = FakeBroker(stop_status=None, existing={CID: {"id": "close-0", "status": "rejected"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_submitted")
    assert got.detail["client_order_id"] == CID + "-r1"
    assert got.detail["dead_attempts"] == [{"client_order_id": CID, "status": "rejected"}]
    assert broker.posted()[0]["client_order_id"] == CID + "-r1"


def test_live_retry_attempt_is_authoritative_over_dead_first_attempt():
    broker = FakeBroker(stop_status=None, existing={CID: {"id": "c0", "status": "canceled"},
                                                    CID + "-r1": {"id": "c1", "status": "accepted"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "already_closing") and got.detail["client_order_id"] == CID + "-r1"
    assert broker.posted() == []


def test_all_retry_ids_dead_is_an_incident_not_a_silent_loop():
    existing = {attempt_id(CID, r): {"id": f"c{r}", "status": "rejected"}
                for r in range(MAX_RETRIES + 1)}
    got = outcome(FakeBroker(stop_status=None, existing=existing))
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "close_retries_exhausted_manual_exit_required")


# --- Exit codes derive from broker coverage, not from what this process did (#95) ---


def test_resumed_refusal_after_crash_post_cancel_is_still_an_incident():
    # Audit probe repro_v1_foundation.py:45. An earlier process canceled the stop and
    # died; this rerun sees the held position with no stop. A preflight refusal must
    # not read "refused; the resting stop still protects" -- nothing protects.
    broker = FakeBroker(stop_status=None, refuse=True)
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "refused_position_unprotected")
    assert got.detail["reason"] == "paper account required" and got.detail["coverage"]["ok"] is False
    assert broker.posted() == []


def test_refusal_with_a_stop_that_does_not_certify_coverage_is_an_incident():
    # A stop that rests but cannot be verified (held, pending, expired, short) does
    # not downgrade the refusal to "still protects".
    for order in ({"status": "held"}, {"expires_at": "2026-09-01T00:00:00Z"}, {"qty": "4"}):
        broker = FakeBroker(refuse=True)
        broker.orders[STOP].update(order)
        got = outcome(broker)
        assert (got.code, got.state) == (EXIT_UNPROTECTED, "refused_position_unprotected"), order
        assert got.detail["coverage"]["issues"]


def test_portfolio_read_failure_in_preflight_on_an_uncovered_position_is_an_incident():
    # The mutation gate reads the portfolio; the broker goes away mid-preflight while
    # the position has no verified stop: 8, not 4.
    broker = FakeBroker(stop_status=None)
    broker.check = lambda *_a: (_ for _ in ()).throw(SystemExit(4))
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_UNPROTECTED, "broker_state_unavailable_position_unprotected")

    covered = FakeBroker()
    covered.check = lambda *_a: (_ for _ in ()).throw(SystemExit(4))
    assert outcome(covered).code == EXIT_NO_STATE  # verified stop rests: nothing changed, retry later


# --- Completion is reconciled holdings, not a filled attempt (ADR 0005, #96) ---


def test_new_same_day_position_is_not_reported_closed_from_old_exit():
    # Audit probe repro_v1_foundation.py:31, verbatim stub: every client id looks
    # filled, yet AMD is still held. A filled close proves an earlier lifecycle
    # ended, nothing about today's holdings.
    def read(command, *args):
        if command == "order-by-client":
            return {"id": "earlier-exit", "status": "filled", "symbol": "AMD", "qty": "10"}
        if command == "positions":
            return [{"symbol": "AMD", "qty": "5", "market_value": "500"}]
        if command == "orders":
            return []
        raise AssertionError(command)
    with pytest.raises(Outcome) as got:
        close_position("AMD", NOW, read=read)
    assert got.value.state != "already_closed" and got.value.code != EXIT_OK


def test_same_day_reentry_then_close_sells_the_new_lifecycle_under_a_new_intent():
    # The morning's close filled; AMD was bought again and is held with a stop.
    broker = FakeBroker(existing={CID: {"id": "close-0", "status": "filled"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_submitted")
    assert got.detail["intent"] == CID + "-2" and got.detail["superseded_intent"] == CID
    assert broker.posted()[0]["client_order_id"] == CID + "-2"
    # Repeating the close now finds the new intent filled-or-live, never the morning's.
    broker.by_client[CID + "-2"]["status"] = "filled"
    broker.positions = []
    again = outcome(broker)
    assert (again.code, again.state, again.detail["intent"]) == (EXIT_OK, "close_complete", CID + "-2")


def test_live_close_attempt_is_adopted_only_while_the_symbol_is_held():
    held = FakeBroker(stop_status=None, existing={CID: {"id": "c0", "status": "accepted"}})
    assert (outcome(held).code, outcome(held).state) == (EXIT_OK, "already_closing")
    gone = FakeBroker(held=False, stop_status=None, existing={CID: {"id": "c0", "status": "accepted"}})
    got = outcome(gone)
    assert (got.code, got.state) == (EXIT_USAGE, "close_resting_without_position")


def test_zero_holdings_with_a_live_buy_is_not_complete():
    broker = FakeBroker(held=False, stop_status=None, buys=["accepted"],
                        existing={CID: {"id": "close-0", "status": "filled"}})
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "position_gone_buy_live")
    assert got.detail["buy_client_order_ids"] == ["en-20260921-AMD-2"] and broker.calls == []


def test_filled_stop_does_not_prove_the_added_quantity_gone():
    # The stop covered the original 10; 5 shares added since are still held.
    broker = FakeBroker(cancel_to="filled", remainder="5")
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_OK, "close_submitted")
    assert broker.posted()[0]["qty"] == "5" and broker.posted()[0]["client_order_id"] == CID


def test_filled_stop_with_a_live_buy_is_not_complete():
    broker = FakeBroker(cancel_to="filled", buys=["new"])
    got = outcome(broker)
    assert (got.code, got.state) == (EXIT_REFUSED, "position_gone_buy_live") and broker.posted() == []


def test_live_close_from_before_midnight_is_adopted_after_it():
    after_midnight = datetime(2026, 9, 22, 0, 15, tzinfo=timezone.utc)
    broker = FakeBroker(stop_status=None, existing={CID: {"id": "c0", "status": "accepted"}})
    got = outcome(broker, now=after_midnight)
    assert (got.code, got.state, got.detail["intent"]) == (EXIT_OK, "already_closing", CID)


def test_rejected_close_from_yesterday_resumes_its_intent_only_when_named():
    after_midnight = datetime(2026, 9, 22, 0, 15, tzinfo=timezone.utc)
    existing = {CID: {"id": "c0", "status": "rejected"}}
    named = FakeBroker(stop_status=None, existing=existing)
    got = outcome(named, now=after_midnight, intent=CID)
    assert got.state == "close_submitted" and got.detail["client_order_id"] == CID + "-r1"
    fresh = FakeBroker(stop_status=None, existing=existing)
    got = outcome(fresh, now=after_midnight)
    assert got.state == "close_submitted" and got.detail["intent"] == "cl-20260922-AMD"


def test_every_outcome_names_the_intent_and_main_prints_a_rerun_with_it(monkeypatch, capsys):
    import scripts.close_position as cp

    got = outcome(FakeBroker(close=None, close_http="422"))
    assert got.detail["intent"] == CID

    def fake(symbol, now, intent=None):
        raise Outcome(EXIT_UNPROTECTED, "close_failed_position_naked_rerun", symbol=symbol, intent=CID)
    monkeypatch.setattr(cp, "close_position", fake)
    monkeypatch.setattr("sys.argv", ["close_position.py", "--symbol", "AMD", "--reason", "cut at -7% per rule"])
    assert cp.main() == EXIT_UNPROTECTED
    printed = json.loads(capsys.readouterr().out)
    assert printed["intent"] == CID
    assert printed["rerun"] == ("python3 scripts/close_position.py --symbol AMD --intent " + CID
                                + " --reason 'cut at -7% per rule'")


def test_malformed_intent_is_a_usage_error(monkeypatch, capsys):
    import scripts.close_position as cp
    monkeypatch.setattr("sys.argv", ["close_position.py", "--symbol", "AMD", "--intent", "cl-20260921-AMD-r1"])
    assert cp.main() == EXIT_USAGE
    assert "attempt id" in json.loads(capsys.readouterr().out)["reason"]
