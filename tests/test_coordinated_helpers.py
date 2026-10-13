"""The helpers through the coordinator (ADR 0010): reservations reach the
engine, refusals are recorded, a dead writer's canceled stop is re-placed
before anything else, and the monitor recovers every run. Offline: a bare
repository plays origin, a stub the broker."""
from datetime import timedelta
import os

import pytest

from risk_engine import PortfolioState, build_oto_entry, fixed_stop_at_distance
from scripts import coordinator, validate_order
from scripts.close_position import close_position
from scripts.coordinator import Outcome, Session, fold
from scripts.protection_monitor import run_monitor
from scripts.replace_stop import replace_stop
from scripts.state_store import EXIT_STORE_UNAVAILABLE
from scripts.strategy_version import bind
from scripts.submit_entry import submit_entry
from scripts.validate_mutation import validate_mutation
from tests.store_support import NOW, Broker, Clock, git, intent_lines, make_origin, stored, writer_store

ENTRY = "en-20261013-AMD"


class Market(Broker):
    """The stub broker plus what the mutation gate reads: assets and a fresh ask."""

    def read(self, command, arg=None, *rest):
        if command == "asset":
            return {"symbol": arg, "class": "us_equity", "tradable": True, "status": "active"}
        if command == "quote":
            return {"quote": {"t": NOW.isoformat(), "ap": "100"}}
        return super().read(command, arg, *rest)


def engine_gate(broker, cash="25000"):
    """The real mutation gate and engine, on a fixed account: $100k equity, `cash` settled."""
    def check(command, argument, reservations=()):
        state = PortfolioState(equity="100000", cash=cash, is_paper=True, reservations=reservations,
                               positions=(), trades_this_week=0)
        return validate_mutation(command, argument, read=broker.read, portfolio=state, now=NOW,
                                 binding=bind(os.environ))
    return check


def oto(symbol, qty):
    return build_oto_entry(symbol=symbol, qty=str(qty), protection=fixed_stop_at_distance("100", "10"))


def entry(store, broker, clock, symbol, qty, **kw):
    with pytest.raises(Outcome) as info:
        submit_entry(oto(symbol, qty), read=broker.read, run=broker.run, now=NOW, store=store, writer="market-open",
                     check=engine_gate(broker), clock=clock, sleep=clock.sleep, fault=lambda _: None, **kw)
    return info.value


@pytest.fixture
def origin(tmp_path):
    return make_origin(tmp_path)


def test_a_pending_entry_reservation_refuses_a_buy_broker_state_alone_would_allow(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Market(), Clock()
    broker.lose_responses, broker.hidden_lookups = 1, 99
    first = entry(store, broker, clock, "AMD", 200)            # $20,000: response lost
    assert (first.code, first.detail["intent_state"]) == (8, "lost")
    broker.orders.clear()                                       # the broker shows nothing at all

    # Broker state alone ($25,000 cash, nothing held, nothing pending) allows a $10,000 buy ...
    (tmp_path / "x").mkdir()
    control = entry(writer_store(tmp_path / "x", make_origin(tmp_path / "x"), "c"), Market(), Clock(), "XLP", 100)
    assert control.state == "submitted"
    # ... the lost entry's reservation leaves $5,000 and refuses it, naming the intent.
    second = entry(store, broker, clock, "XLP", 100)
    assert (second.code, second.state) == (3, "refused") and ENTRY in second.detail["reason"]
    assert [p["symbol"] for p in broker.posts] == ["AMD"] * (1 + coordinator.LOST_REPOSTS)
    refused = intent_lines(origin, "en-20261013-XLP")
    assert [e["state"] for e in refused] == ["refused"] and ENTRY in refused[0]["reasons"][0]


def test_a_finished_intent_is_never_recorded_twice_the_next_one_is_minted(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Market(), Clock()
    refused = entry(store, broker, clock, "AMD", 900)            # 90% of equity: refused
    assert refused.state == "refused" and refused.detail["refusal_recorded"] is True
    got = entry(store, broker, clock, "AMD", 100)
    assert got.state == "submitted" and got.detail["intent"] == ENTRY + "-2"
    assert got.detail["superseded_intent"] == ENTRY and got.detail["superseded_state"] == "refused"


class Crash(BaseException):
    """The process dies: no handler runs, nothing is released."""


def crash_at(point):
    def fault(name):
        if name == point:
            raise Crash(name)
    return fault


def test_close_killed_between_cancel_and_sell_is_restored_then_closed_by_the_next_writer(
        tmp_path, origin, monkeypatch):
    broker, clock = Market(), Clock()
    broker.hold("AMD", 10)
    stop = broker.stop("AMD", 10, "90")
    monkeypatch.setattr(Session, "abandon", lambda self, exc: None)   # a real death releases nothing
    with pytest.raises(Crash):
        close_position("AMD", NOW, read=broker.read, run=broker.run, check=lambda *a, **k: None,
                       store=writer_store(tmp_path, origin, "a"), writer="midday", clock=clock,
                       sleep=clock.sleep, fault=crash_at("after_cancel"))
    assert broker.orders[stop]["status"] == "canceled" and "AMD" in broker.positions   # naked

    with pytest.raises(Outcome) as info:
        close_position("AMD", NOW, read=broker.read, run=broker.run, check=lambda *a, **k: None,
                       store=writer_store(tmp_path, origin, "b"), writer="trade", clock=clock,
                       sleep=clock.sleep, fault=lambda _: None)

    got = info.value
    assert sum(clock.slept) >= (coordinator.LEASE_TTL + coordinator.SKEW).total_seconds()  # waited, then took over
    restore = broker.by_client(f"rr-{stop}")
    assert restore["stop_price"] == "90"                       # re-placed at its own level first ...
    assert got.state == "close_submitted" and got.detail["intent"] == "cl-20261013-AMD-2"
    assert "AMD" not in broker.positions                       # ... then the new intent sold
    assert [(e["intent"], e["state"], e.get("reason")) for e in intent_lines(origin)] == [
        ("cl-20261013-AMD", "recorded", None),
        ("cl-20261013-AMD", "dead", "restored"),
        ("cl-20261013-AMD-2", "recorded", None),
        ("cl-20261013-AMD-2", "complete", None)]


def test_replace_stop_without_the_store_refuses_and_leaves_the_old_stop(tmp_path, origin):
    broker, clock = Market(), Clock()
    broker.hold("AMD", 10)
    stop = broker.stop("AMD", 10, "90", type="trailing_stop")
    store = writer_store(tmp_path, origin, "a")
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=store.repo)
    with pytest.raises(Outcome) as info:
        replace_stop(stop, trail_percent="7", read=broker.read, run=broker.run, check=lambda *a, **k: None,
                     store=store, writer="midday", clock=clock, sleep=clock.sleep, fault=lambda _: None, now=NOW)
    assert info.value.code == EXIT_STORE_UNAVAILABLE and broker.cancels == []
    assert broker.orders[stop]["status"] == "new"


def test_replace_stop_without_the_store_still_restores_a_naked_position(tmp_path, origin):
    broker, clock = Market(), Clock()
    broker.hold("AMD", 10)
    stop = broker.stop("AMD", 10, "90", status="canceled")      # an earlier run's cancel, then death
    store = writer_store(tmp_path, origin, "a")
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=store.repo)
    with pytest.raises(Outcome) as info:
        replace_stop(stop, stop_price="91", read=broker.read, run=broker.run, check=lambda *a, **k: None,
                     store=store, writer="monitor", clock=clock, sleep=clock.sleep, fault=lambda _: None, now=NOW)
    got = info.value
    assert got.state == "replaced" and broker.by_client(f"rs-{stop}")["stop_price"] == "91"
    assert got.detail["store_exception"] and "STORE UNAVAILABLE" in got.detail["alerts"][0]


def test_the_monitor_recovers_a_dead_writers_intent_on_every_live_run(tmp_path, origin, monkeypatch):
    broker = Market()
    dead_clock = Clock(NOW - timedelta(days=1))                 # long expired against the wall clock
    a = writer_store(tmp_path, origin, "a")
    snap = a.fetch()
    s = Session(store=a, writer="market-open", read=broker.read, run=broker.run, clock=dead_clock,
                sleep=dead_clock.sleep, fault=lambda _: None, binding=None, snapshot=snap, view=fold(snap.events))
    s.record("en-20261012-XLK", action="entry", symbol="XLK", qty="5", price="200", refuse=Outcome)
    monitor_store = writer_store(tmp_path, origin, "m")
    monkeypatch.setattr(coordinator, "open_store", lambda environ=None: monitor_store)

    dry = run_monitor(NOW, dry_run=True, read=broker.read)
    assert [i["intent"] for i in dry["recovery"]["non_terminal"]] == ["en-20261012-XLK"]
    assert fold(stored(origin)).intents["en-20261012-XLK"].state == "recorded"   # dry run changes nothing

    report = run_monitor(NOW, read=broker.read)
    assert report["recovery"]["recovery"] == [{"intent": "en-20261012-XLK", "from": "recorded", "to": "dead",
                                               "reason": "holder_died"}]
    takeover = [e for e in stored(origin) if e.get("op") == "acquire"][-1]
    assert takeover["supersedes"] == s.acquire["id"] and report["exit"] == 0


def test_the_monitor_reports_an_unreachable_store_and_still_runs(monkeypatch):
    report = run_monitor(NOW, read=lambda cmd, *a: [])
    assert report["exit"] == EXIT_STORE_UNAVAILABLE and report["recovery"]["state"] == "store_unavailable"


# --- the weekly count agrees with the `filled` state ------------------------------

def test_a_buy_partly_filled_then_canceled_counts_as_a_trade_this_week(monkeypatch):
    orders = [
        {"side": "buy", "filled_at": None, "filled_qty": "4", "canceled_at": "2026-10-13T15:30:00Z"},
        {"side": "buy", "filled_at": None, "filled_qty": "0", "canceled_at": "2026-10-13T15:30:00Z"},
        {"side": "buy", "filled_at": "2026-10-09T15:00:00Z", "filled_qty": "10"},       # last week
        {"side": "buy", "filled_at": "2026-10-12T14:00:00Z", "filled_qty": "10"},
    ]
    monkeypatch.setattr(validate_order, "adapter", lambda *a: orders)
    assert validate_order.trades_this_week(NOW) == 2


def test_validate_order_refuses_buys_when_the_store_is_unreachable():
    with pytest.raises(SystemExit) as info:
        validate_order.buy_reservations()
    assert info.value.code == EXIT_STORE_UNAVAILABLE


def test_the_mutation_gate_reads_reservations_minus_the_attempts_own_intent(tmp_path, origin, monkeypatch):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Market(), Clock()
    broker.lose_responses, broker.hidden_lookups = 1, 99
    entry(store, broker, clock, "AMD", 200)
    broker.orders.clear()
    monkeypatch.setenv("TRADING_STATE_REPO", str(store.repo))
    monkeypatch.setattr(validate_order, "adapter", broker.read)
    assert [r.intent_id for r in validate_order.buy_reservations()] == [ENTRY]
    assert validate_order.buy_reservations(exclude=ENTRY) == ()
    assert coordinator.intent_of_attempt(ENTRY + "-r2") == ENTRY
