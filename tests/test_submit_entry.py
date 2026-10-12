"""Idempotent entry: a rerun looks the buy up by its stable client id instead
of buying twice, and the outcome is always confirmed from broker state."""
from datetime import datetime, timezone
import json

import pytest

from scripts.replace_stop import EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, Outcome
from scripts.execution_identity import MAX_RETRIES, attempt_id
from scripts.submit_entry import submit_entry

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


CID = "en-20260921-AMD"
AFTER_MIDNIGHT = datetime(2026, 9, 22, 0, 10, tzinfo=timezone.utc)


def body():
    return {"symbol": "AMD", "qty": "10", "side": "buy", "type": "market", "time_in_force": "gtc",
            "order_class": "oto", "stop_loss": {"stop_price": "93"}}


def outcome(broker, b=None, now=NOW, **identity):
    with pytest.raises(Outcome) as info:
        submit_entry(b or body(), read=broker.read, run=broker.run, now=now, **identity)
    return info.value


def test_the_caller_never_stamps_the_client_id():
    b = {**body(), "client_order_id": CID}
    with pytest.raises(ValueError, match="intent"):
        submit_entry(b, read=FakeBroker().read, run=FakeBroker().run, now=NOW)


def test_submits_once_and_confirms_by_client_id(capsys):
    broker = FakeBroker()
    got = outcome(broker)
    assert f"intent {CID}: submitting attempt {CID}" in capsys.readouterr().err
    assert (got.code, got.state, got.detail["intent"]) == (EXIT_OK, "submitted", CID)
    assert broker.submitted[0]["client_order_id"] == CID
    assert got.detail["order"]["id"] == "broker-1"


def test_rerun_finds_the_earlier_buy_and_does_not_submit():
    for status, state in (("accepted", "already_submitted"), ("filled", "already_filled")):
        broker = FakeBroker(existing={CID: {"id": "broker-0", "status": status}})
        got = outcome(broker)
        assert (got.code, got.state, got.detail["intent"]) == (EXIT_OK, state, CID) and broker.submitted == []


def test_retry_after_a_dead_attempt_uses_the_next_attempt_id_not_the_same_one():
    # Alpaca answers a reused client id with 422 forever; a dead attempt is skipped.
    for dead in ("canceled", "expired", "rejected", "replaced"):
        broker = FakeBroker(existing={CID: {"id": "broker-0", "status": dead}})
        got = outcome(broker)
        assert got.state == "submitted" and broker.submitted[0]["client_order_id"] == CID + "-r1", dead
        assert got.detail["dead_attempts"] == [{"client_order_id": CID, "status": dead}]


def test_rejected_then_canceled_retries_twice_then_exhausts_with_a_hard_failure():
    broker = FakeBroker(existing={CID: {"id": "b0", "status": "rejected"}, CID + "-r1": {"id": "b1", "status": "canceled"}})
    assert outcome(broker).detail["client_order_id"] == CID + "-r2"
    spent = FakeBroker(existing={attempt_id(CID, n): {"id": f"b{n}", "status": "rejected"}
                                 for n in range(MAX_RETRIES + 1)})
    got = outcome(spent)
    assert (got.code, got.state) == (EXIT_REFUSED, "entry_retries_exhausted") and spent.submitted == []


def test_live_entry_from_before_midnight_is_found_after_it():
    broker = FakeBroker(existing={CID: {"id": "broker-0", "status": "new"}})
    got = outcome(broker, now=AFTER_MIDNIGHT)
    assert (got.state, got.detail["intent"]) == ("already_submitted", CID) and broker.submitted == []


def test_filled_entry_yesterday_does_not_block_a_new_entry_today():
    broker = FakeBroker(existing={CID: {"id": "broker-0", "status": "filled"}})
    got = outcome(broker, now=AFTER_MIDNIGHT)
    assert got.state == "submitted" and broker.submitted[0]["client_order_id"] == "en-20260922-AMD"


def test_named_intent_resumes_across_midnight_with_its_next_attempt():
    broker = FakeBroker(existing={CID: {"id": "broker-0", "status": "rejected"}})
    got = outcome(broker, now=AFTER_MIDNIGHT, intent=CID)
    assert got.detail["intent"] == CID and broker.submitted[0]["client_order_id"] == CID + "-r1"


def test_tag_is_a_deliberate_second_entry_the_same_day():
    broker = FakeBroker(existing={CID: {"id": "broker-0", "status": "filled"}})
    got = outcome(broker, tag="b")
    assert got.state == "submitted" and broker.submitted[0]["client_order_id"] == CID + "-b"


def test_main_prints_the_intent_and_a_rerun_that_names_it(monkeypatch, capsys):
    import scripts.submit_entry as se

    def fake(b, intent=None, tag=None):
        raise Outcome(EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun", intent=CID, client_order_id=CID)
    monkeypatch.setattr(se, "submit_entry", fake)
    monkeypatch.setattr("sys.argv", ["submit_entry.py", "--symbol", "AMD", "--qty", "10", "--price", "100"])
    assert se.main() == EXIT_UNPROTECTED
    printed = json.loads(capsys.readouterr().out)
    assert printed["intent"] == CID
    assert printed["rerun"] == f"python3 scripts/submit_entry.py --symbol AMD --qty 10 --price 100 --intent {CID}"


@pytest.mark.parametrize("flags", [["--tag", "r1"], ["--tag", "bad tag"], ["--intent", "en-20260921-AMD-r1"],
                                   ["--intent", "cl-20260921-AMD"], ["--intent", "en-20990101-AMD"]])
def test_bad_identity_flags_are_usage_errors_before_any_broker_call(monkeypatch, capsys, flags):
    import scripts.submit_entry as se
    monkeypatch.setattr(se, "submit_entry", lambda *a, **k: pytest.fail("must not reach the broker"))
    monkeypatch.setattr("sys.argv", ["submit_entry.py", "--symbol", "AMD", "--qty", "10", "--price", "100", *flags])
    assert se.main() == 2
    assert json.loads(capsys.readouterr().out)["state"] == "usage"


def test_intent_and_tag_together_are_rejected(monkeypatch):
    import scripts.submit_entry as se
    monkeypatch.setattr("sys.argv", ["submit_entry.py", "--symbol", "AMD", "--qty", "10", "--price", "100",
                                     "--intent", CID, "--tag", "b"])
    with pytest.raises(SystemExit) as exc:
        se.main()
    assert exc.value.code == 2


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
