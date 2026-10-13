"""The coordinator (ADR 0010): one account-wide lease, intents recorded before
the broker sees them, reservations derived from intents, recovery that only
restores coverage. Offline: a bare repository plays origin, a stub the broker."""
from datetime import timedelta
import json

import pytest

from scripts import coordinator as co
from scripts.coordinator import (EXIT_LEASE_WAIT, EXIT_NOT_RECORDED, Outcome, Session, coordinate, fold,
                                 recover_only, session_closed_since, store_reservations)
from scripts.state_store import EXIT_STORE_UNAVAILABLE, CorruptState, new_event
from tests.store_support import NOW, Broker, Clock, git, intent_lines, make_origin, stored, writer_store


# --- the replay rule -------------------------------------------------------------

def lease(op, lid=None, prev=None, **extra):
    e = new_event("lease", "w", op=op, prev=prev, **extra)
    if lid:
        e["id"] = lid
    if op == "acquire":
        e.setdefault("expires_at", "2099-01-01T00:00:00+00:00")
        e["lease"] = e["id"]
    return e


def intent(name, state, lease_id, **extra):
    fields = {"action": "entry", "symbol": "AMD", "qty": "10", "price": "100"} if state == "recorded" else {}
    return new_event("intent", "w", intent=name, state=state, lease=lease_id, **{**fields, **extra})


def test_an_acquire_is_valid_only_on_the_current_head_with_no_live_holder():
    a = lease("acquire", "A", prev=None)
    b = lease("acquire", "B", prev=None)          # raced A from the same base
    view = fold([a, b])
    assert view.holder["id"] == "A" and "B" in view.void


def test_release_frees_the_lease_and_becomes_the_head():
    a, rel = lease("acquire", "A"), lease("release", "R", prev="A", lease="A")
    b = lease("acquire", "B", prev="R")
    assert fold([a, rel]).holder is None
    assert fold([a, rel, b]).holder["id"] == "B"


def test_a_takeover_must_supersede_the_holder():
    a = lease("acquire", "A")
    steal = lease("acquire", "S", prev="A")                     # no supersedes: void
    take = lease("acquire", "T", prev="A", supersedes="A")
    assert "S" in fold([a, steal]).void
    view = fold([a, take])
    assert view.holder["id"] == "T" and [t["id"] for t in view.takeovers] == ["T"]


def test_intent_lines_under_a_void_lease_are_ignored():
    a, b = lease("acquire", "A"), lease("acquire", "B")
    view = fold([a, b, intent("en-20261013-AMD", "recorded", "B")])
    assert view.intents == {}


def test_an_illegal_transition_under_the_valid_lease_hard_fails():
    a = lease("acquire", "A")
    with pytest.raises(CorruptState, match="illegal transition"):
        fold([a, intent("en-20261013-AMD", "recorded", "A"), intent("en-20261013-AMD", "refused", "A",
                                                                       reasons=["x"])])
    with pytest.raises(CorruptState, match="illegal transition"):
        fold([a, intent("en-20261013-AMD", "acknowledged", "A")])


def test_withdrawn_lines_and_other_kinds_are_ignored():
    a = lease("acquire", "A")
    withdraw = new_event("withdraw", "w", intent="x", withdraws=["A"])
    run = new_event("run", "r", op="start")
    assert fold([a, withdraw, run]).holder is None


def test_session_close_is_the_next_weekday_1600_new_york():
    tuesday_noon = NOW.replace(hour=16)                  # 12:00 EDT
    assert not session_closed_since(tuesday_noon, tuesday_noon.replace(hour=19, minute=59))
    assert session_closed_since(tuesday_noon, tuesday_noon.replace(hour=20))
    friday_evening = NOW.replace(day=16, hour=22)        # after Friday's close
    assert not session_closed_since(friday_evening, NOW.replace(day=18, hour=12))   # Sunday
    assert session_closed_since(friday_evening, NOW.replace(day=19, hour=20))       # Monday close


# --- coordinated actions -----------------------------------------------------------

ENTRY = "en-20261013-AMD"


@pytest.fixture
def origin(tmp_path):
    return make_origin(tmp_path)


def no_fault(name):
    pass


def act(store, broker, clock, body, writer="w1", **kw):
    with pytest.raises(Outcome) as info:
        coordinate(body, store=store, writer=writer, read=broker.read, run=broker.run, clock=clock,
                   sleep=clock.sleep, fault=kw.pop("fault", no_fault), **kw)
    return info.value


def refuse_with(code, state, **detail):
    return Outcome(code, state, **detail)


def entry_body(qty="10", name=ENTRY, cid=None):
    cid = cid or name

    def body(s):
        s.record(name, action="entry", symbol="AMD", qty=qty, price="100", client_order_id=cid,
                 refuse=refuse_with)
        order, http, err, sent = s.post(cid, json.dumps({"symbol": "AMD", "qty": qty, "side": "buy",
                                                          "type": "market", "client_order_id": cid}))
        raise Outcome(0 if order else 8, "submitted" if order else "submitted_outcome_unknown_rerun",
                      intent=name)
    return body


def test_an_entry_is_two_pushes_recorded_before_the_post_then_outcome_and_release(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    seen_at_post = []
    real_run = broker.run

    def run(command, arg):
        seen_at_post.append([e.get("state") or e.get("op") for e in stored(origin)])
        return real_run(command, arg)
    broker.run = run

    got = act(store, broker, clock, entry_body())

    assert seen_at_post == [["acquire", "recorded"]]
    assert [e.get("state") or e.get("op") for e in stored(origin)] == ["acquire", "recorded", "acknowledged",
                                                                       "release"]
    assert got.detail["intent_state"] == "acknowledged"
    assert git("log", "--format=%s", "-3", "main", cwd=origin).splitlines()[:2] == [
        f"state: w1 {ENTRY} [skip ci]", f"state: w1 {ENTRY} [skip ci]"]


def test_a_refusal_is_recorded_with_its_reasons_and_takes_no_reservation(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()

    def body(s):
        s.refuse(ENTRY, Outcome(3, "refused"), action="entry", symbol="AMD", reasons=["rule 3: no slot"])
    got = act(store, broker, clock, body)

    assert got.detail["refusal_recorded"] is True and broker.posts == []
    assert [e.get("state") or e.get("op") for e in stored(origin)] == ["acquire", "refused", "release"]
    assert intent_lines(origin)[0]["reasons"] == ["rule 3: no slot"]
    assert store_reservations(store, broker.read) == ()


def test_lost_response_404_then_422_on_repost_adopts_the_order(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    broker.lose_responses, broker.hidden_lookups = 1, 1     # POST lands, answer lost, first lookup 404

    got = act(store, broker, clock, entry_body())

    assert [p["client_order_id"] for p in broker.posts] == [ENTRY, ENTRY]   # same attempt id re-POSTed
    assert got.state == "submitted" and got.detail["intent_state"] == "acknowledged"
    assert len([o for o in broker.orders.values() if o["side"] == "buy"]) == 1


def test_lost_response_past_the_budget_is_lost_and_keeps_its_reservation(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    broker.lose_responses, broker.hidden_lookups = 1, 99

    got = act(store, broker, clock, entry_body())

    assert got.code == 8 and got.detail["intent_state"] == "lost"
    assert len(broker.posts) == 1 + co.LOST_REPOSTS
    broker.hidden_lookups = 99
    held = store_reservations(store, broker.read)
    assert [(r.intent_id, r.qty) for r in held] == [(ENTRY, 10)]


def test_partial_fill_reserves_only_the_unfilled_part_then_counts_as_filled_once_dead(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    broker.buy_status, broker.buy_filled_qty = "partially_filled", "4"

    assert act(store, broker, clock, entry_body()).detail["intent_state"] == "acknowledged"
    assert [(r.intent_id, r.qty) for r in store_reservations(store, broker.read)] == [(ENTRY, 6)]

    broker.by_client(ENTRY)["status"] = "canceled"            # the rest never fills
    report = recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                          sleep=clock.sleep, fault=no_fault)
    assert report["recovery"] == [{"intent": ENTRY, "from": "acknowledged", "to": "filled",
                                   "client_order_id": ENTRY, "filled_qty": "4"}]
    assert store_reservations(store, broker.read) == ()


def hold_lease(store, broker, clock, writer="holder", body_intent="en-20261013-XLK"):
    """A writer that has pushed acquire + recorded and not finished (alive or dead)."""
    snap = store.fetch()
    s = Session(store=store, writer=writer, read=broker.read, run=broker.run, clock=clock, sleep=clock.sleep,
                fault=no_fault, binding=None, snapshot=snap, view=fold(snap.events))
    s.record(body_intent, action="entry", symbol="XLK", qty="5", price="200", client_order_id=body_intent,
             refuse=refuse_with)
    return s


def test_two_writers_one_waits_without_mutating_until_the_holder_releases(tmp_path, origin):
    broker, clock = Broker(), Clock()
    holder = hold_lease(writer_store(tmp_path, origin, "a"), broker, clock)
    waiter = writer_store(tmp_path, origin, "b")
    posts_while_held = []

    def sleep(seconds):
        posts_while_held.append(len(broker.posts))
        clock.sleep(seconds)
        if len(clock.slept) == 2:
            holder.finish(Outcome(3, "refused_at_broker"))      # the holder ends and releases

    with pytest.raises(Outcome) as info:
        coordinate(entry_body(), store=waiter, writer="w2", read=broker.read, run=broker.run, clock=clock,
                   sleep=sleep, fault=no_fault)

    assert info.value.state == "submitted"
    assert clock.slept[:2] == [co.POLL_S, co.POLL_S] and posts_while_held == [0, 0]
    acquires = [e for e in stored(origin) if e.get("op") == "acquire"]
    assert "supersedes" not in acquires[-1]                # waited for a release, did not steal


def test_racing_writers_from_one_base_the_loser_withdraws_and_waits(tmp_path, origin):
    broker, clock = Broker(), Clock()
    a, b = writer_store(tmp_path, origin, "a"), writer_store(tmp_path, origin, "b")
    holders = []

    def b_body(s):
        if not holders:          # A lands its acquire after B replayed the same head
            holders.append(hold_lease(a, broker, clock))
        entry_body()(s)

    def sleep(seconds):
        clock.sleep(seconds)
        if seconds == co.POLL_S and holders and holders[0].acquire is not None:
            try:
                holders[0].finish(Outcome(3, "done"))
            finally:
                holders[0].acquire = None

    with pytest.raises(Outcome) as info:
        coordinate(b_body, store=b, writer="w2", read=broker.read, run=broker.run, clock=clock, sleep=sleep,
                   fault=no_fault)

    assert info.value.state == "submitted"
    events = stored(origin)
    assert any(e["kind"] == "withdraw" for e in events)
    view = fold(events)
    assert view.holder is None and view.intents[ENTRY].state == "acknowledged"


def test_crash_after_push_1_is_taken_over_after_expiry_and_skew_and_recovered_first(tmp_path, origin):
    broker, clock = Broker(), Clock()
    dead = hold_lease(writer_store(tmp_path, origin, "a"), broker, clock)   # crashed before its POST
    taker = writer_store(tmp_path, origin, "b")

    got = act(taker, broker, clock, entry_body())

    assert sum(clock.slept) >= (co.LEASE_TTL + co.SKEW).total_seconds()
    events = stored(origin)
    takeover = [e for e in events if e.get("op") == "acquire"][-1]
    assert takeover["supersedes"] == dead.acquire["id"]
    after = [e for e in events[events.index(takeover):] if e["kind"] == "intent"]
    assert [(e["intent"], e["state"], e.get("reason")) for e in after][:2] == [
        ("en-20261013-XLK", "dead", "holder_died"), (ENTRY, "recorded", None)]
    assert got.state == "submitted"


def test_lease_wait_is_bounded(tmp_path, origin, monkeypatch):
    broker, clock = Broker(), Clock()
    hold_lease(writer_store(tmp_path, origin, "a"), broker, clock)
    monkeypatch.setattr(co, "MAX_WAIT", timedelta(seconds=40))
    got = act(writer_store(tmp_path, origin, "b"), broker, clock, entry_body())
    assert got.code == EXIT_LEASE_WAIT and broker.posts == []


def test_crash_between_cancel_and_sell_restores_coverage_as_dead_restored(tmp_path, origin):
    broker, clock = Broker(), Clock()
    broker.hold("AMD", 10)
    stop = broker.stop("AMD", 10, "90")
    a = writer_store(tmp_path, origin, "a")
    snap = a.fetch()
    s = Session(store=a, writer="midday", read=broker.read, run=broker.run, clock=clock, sleep=clock.sleep,
                fault=no_fault, binding=None, snapshot=snap, view=fold(snap.events))
    s.record("cl-20261013-AMD", action="close", symbol="AMD", cancels=[stop], client_order_id="cl-20261013-AMD",
             refuse=refuse_with)
    s.run("cancel", stop)                                   # ... and the process dies here

    clock.advance(minutes=13)
    report = recover_only(store=writer_store(tmp_path, origin, "m"), writer="monitor", read=broker.read,
                          run=broker.run, clock=clock, sleep=clock.sleep, fault=no_fault)

    restore = broker.by_client(f"rr-{stop}")
    assert restore["type"] == "stop" and restore["stop_price"] == "90" and restore["qty"] == "10"
    assert report["recovery"][-1]["to"] == "dead" and report["recovery"][-1]["reason"] == "restored"
    lines = intent_lines(origin, "cl-20261013-AMD")
    assert [(e["state"], e.get("reason")) for e in lines] == [("recorded", None), ("dead", "restored")]
    # The taker's acquire landed alone before the restoring POST; dead (restored) and release follow.
    tail = stored(origin)[-3:]
    assert [e.get("op") or e.get("state") for e in tail] == ["acquire", "dead", "release"]
    assert tail[0]["supersedes"] == s.acquire["id"]


def test_recovery_restores_even_when_unbound_and_raises_the_version_incident(tmp_path, origin):
    from scripts.strategy_version import Binding
    from risk_engine import V1
    broker, clock = Broker(), Clock()
    broker.hold("AMD", 10)
    stop = broker.stop("AMD", 10, "90")
    a = writer_store(tmp_path, origin, "a")
    snap = a.fetch()
    s = Session(store=a, writer="midday", read=broker.read, run=broker.run, clock=clock, sleep=clock.sleep,
                fault=no_fault, binding=None, snapshot=snap, view=fold(snap.events))
    s.record("rs-" + stop, action="replace_stop", symbol="AMD", cancels=[stop], refuse=refuse_with)
    s.run("cancel", stop)
    clock.advance(minutes=13)

    unbound = Binding(approved="v1.1", params=V1, error="STRATEGY_VERSION is not set")
    report = recover_only(store=a, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                          sleep=clock.sleep, fault=no_fault, binding=unbound)

    assert broker.by_client(f"rr-{stop}")["status"] == "new"
    assert "VERSION BINDING INCIDENT" in report["alerts"][0]


def test_recovery_leaves_a_lost_entry_reserved_until_the_session_close(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    broker.lose_responses, broker.hidden_lookups = 1, 99
    act(store, broker, clock, entry_body())
    broker.orders.clear()                                   # it never landed after all

    report = recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                          sleep=clock.sleep, fault=no_fault)
    assert report["state"] == "recovered" and fold(stored(origin)).intents[ENTRY].state == "lost"

    clock.now = NOW.replace(hour=20, minute=5)              # 16:05 New York
    recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                 sleep=clock.sleep, fault=no_fault)
    assert [(e["state"], e.get("reason")) for e in intent_lines(origin, ENTRY)][-1] == ("dead", "not_landed")


def test_recovery_only_pushes_nothing_when_nothing_changes(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    act(store, broker, clock, entry_body())
    before = stored(origin)
    report = recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                          sleep=clock.sleep, fault=no_fault)
    assert stored(origin) == before and report["state"] == "recovered"


def test_store_unreachable_refuses_the_mutation(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=store.repo)

    got = act(store, broker, clock, entry_body())

    assert got.code == EXIT_STORE_UNAVAILABLE and broker.posts == []


def test_store_unreachable_still_lets_a_stop_go_on_a_position_with_none(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=store.repo)
    broker.hold("AMD", 10)

    def body(s):
        s.record("rs-x", action="replace_stop", symbol="AMD", cancels=["x"], refuse=refuse_with,
                 restoration=True)
        s.run("order", json.dumps({"symbol": "AMD", "qty": "10", "side": "sell", "type": "stop",
                                   "stop_price": "90", "client_order_id": "rs-x"}))
        raise Outcome(0, "replaced")
    got = act(store, broker, clock, body)

    assert got.code == 0 and got.detail["store_exception"] and "STORE UNAVAILABLE" in got.detail["alerts"][0]


def test_no_mutation_after_the_deadline(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()

    def body(s):
        s.record(ENTRY, action="entry", symbol="AMD", qty="10", price="100", refuse=refuse_with)
        clock.advance(minutes=6)
        order, _, _, sent = s.post(ENTRY, json.dumps({"symbol": "AMD", "qty": "10", "side": "buy",
                                                       "client_order_id": ENTRY}))
        raise Outcome(3, sent)
    got = act(store, broker, clock, body)

    assert broker.posts == [] and got.state == "refused"
    assert [(e["state"], e.get("reason")) for e in intent_lines(origin, ENTRY)] == [
        ("recorded", None), ("dead", "not_landed")]


def test_a_failed_push_2_after_acting_exits_not_recorded_and_alerts(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()

    def body(s):
        entry_body()(s)
    real_post = Session.post

    def post_then_lose_store(self, cid, body_json):
        result = real_post(self, cid, body_json)
        git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=store.repo)
        return result

    Session.post = post_then_lose_store
    try:
        got = act(store, broker, clock, body)
    finally:
        Session.post = real_post

    assert got.code == EXIT_NOT_RECORDED and got.state == "acted_outcome_not_recorded"
    assert got.detail["helper_state"] == "submitted" and "ACTED, OUTCOME NOT RECORDED" in got.detail["alerts"][0]
    # The lease was never released; the next writer recovers after expiry.
    assert fold(stored(origin)).holder is not None


def test_fault_injection_is_refused_outside_the_drill_profile():
    with pytest.raises(ValueError, match="drill"):
        co.env_fault({"COORDINATOR_FAULT": "after_record", "ALPACA_PROFILE": "production"})
    with pytest.raises(ValueError, match="not one of"):
        co.env_fault({"COORDINATOR_FAULT": "nowhere", "ALPACA_PROFILE": "drill"})
    assert co.env_fault({})("after_record") is None


def test_the_lose_response_drill_hook_drops_the_first_answer_and_lookup(tmp_path, origin):
    # On the drill account a real POST lands; the hook hides the answer and the first
    # lookup, so the lost-response path (re-POST, 422, adopt) runs against the broker.
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    fault = co.env_fault({"COORDINATOR_FAULT": "lose_response", "ALPACA_PROFILE": "drill"})
    got = act(store, broker, clock, entry_body(), fault=fault)
    assert [p["client_order_id"] for p in broker.posts] == [ENTRY, ENTRY]
    assert got.state == "submitted" and got.detail["intent_state"] == "acknowledged"


# --- regressions from review -------------------------------------------------------

def test_a_failed_lookup_after_the_post_never_frees_the_intent_and_the_rerun_does_not_buy_again(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    real_run = broker.run

    def run_then_reads_fail(command, arg):
        result = real_run(command, arg)
        broker.fail_reads = True                       # the adapter blips right after the POST
        return result
    broker.run = run_then_reads_fail

    def body(s):
        try:
            entry_body()(s)
        except SystemExit:
            raise Outcome(8, "submitted_outcome_unknown_rerun", intent=ENTRY)
    first = act(store, broker, clock, body)
    assert first.code == 8 and fold(stored(origin)).intents[ENTRY].state in co.NON_TERMINAL

    broker.run, broker.fail_reads = real_run, False
    broker.hidden_lookups = 1                           # not yet visible to the rerun's recovery
    clock.advance(seconds=5)
    act(store, broker, clock, entry_body())             # the printed rerun, seconds later
    assert len([o for o in broker.orders.values() if o["side"] == "buy"]) == 1
    assert fold(stored(origin)).intents[ENTRY].state == "acknowledged"


def test_a_released_recorded_intent_keeps_its_reservation_until_expiry_and_skew(tmp_path, origin):
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    left = hold_lease(store, broker, clock)            # recorded, then an unexpected error ...
    left.abandon(RuntimeError("boom"))                 # ... released with the intent still recorded
    clock.advance(seconds=5)
    report = recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                          sleep=clock.sleep, fault=no_fault)
    assert fold(stored(origin)).intents["en-20261013-XLK"].state == "recorded", report
    assert [r.intent_id for r in store_reservations(store, broker.read)] == ["en-20261013-XLK"]

    clock.advance(minutes=13)
    recover_only(store=store, writer="monitor", read=broker.read, run=broker.run, clock=clock,
                 sleep=clock.sleep, fault=no_fault)
    assert [(e["state"], e.get("reason")) for e in intent_lines(origin, "en-20261013-XLK")][-1] == (
        "dead", "holder_died")


def install_reject_hook(origin):
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)


def crashed_close(tmp_path, origin, broker, clock, held=10, stop_qty=10):
    broker.hold("AMD", held)
    stop = broker.stop("AMD", stop_qty, "90")
    a = writer_store(tmp_path, origin, "dead")
    snap = a.fetch()
    s = Session(store=a, writer="midday", read=broker.read, run=broker.run, clock=clock, sleep=clock.sleep,
                fault=no_fault, binding=None, snapshot=snap, view=fold(snap.events))
    s.record("cl-20261013-AMD", action="close", symbol="AMD", cancels=[stop], refuse=refuse_with)
    s.run("cancel", stop)
    clock.advance(minutes=13)
    return stop


def test_a_store_failure_during_recovery_is_an_outcome_not_a_crash(tmp_path, origin):
    broker, clock = Broker(), Clock()
    crashed_close(tmp_path, origin, broker, clock)
    install_reject_hook(origin)
    report = recover_only(store=writer_store(tmp_path, origin, "m"), writer="monitor", read=broker.read,
                          run=broker.run, clock=clock, sleep=clock.sleep, fault=no_fault)
    assert report["exit"] == 8 and report["state"] == "recovery_store_unavailable_position_unprotected"
    assert broker.posts == []                          # nothing restored without the acquire on main


def test_a_failed_push_1_after_a_recovery_push_still_ends_in_an_outcome(tmp_path, origin):
    broker, clock = Broker(), Clock()
    crashed_close(tmp_path, origin, broker, clock)

    def body(s):
        install_reject_hook(origin)                    # the store goes away after push 0
        s.record(ENTRY, action="entry", symbol="XLP", qty="1", price="80", refuse=refuse_with)
        raise AssertionError("unreachable")
    got = act(writer_store(tmp_path, origin, "b"), broker, clock, body)
    # The restore POST already acted, so this is "acted, outcome not recorded", not a crash.
    assert got.code == EXIT_NOT_RECORDED and got.detail["helper_state"] == "store_unavailable"
    assert got.detail["outcome_recorded"] is False and "ACTED, OUTCOME NOT RECORDED" in got.detail["alerts"][-1]


def test_a_restore_that_cannot_cover_does_not_block_every_later_action(tmp_path, origin):
    broker, clock = Broker(), Clock()
    crashed_close(tmp_path, origin, broker, clock, held=15, stop_qty=10)   # position grew after the stop
    ran = []

    def body(s):
        ran.append(True)
        raise Outcome(0, "nothing_to_do")
    got = act(writer_store(tmp_path, origin, "b"), broker, clock, body)
    assert ran and got.code == 8                      # still held without verified coverage
    assert "RECOVERY COULD NOT RESTORE" in got.detail["alerts"][0]
    assert [(e["state"], e.get("reason")) for e in intent_lines(origin, "cl-20261013-AMD")][-1] == (
        "dead", "holder_died")


def test_a_fault_set_outside_the_drill_profile_is_a_usage_outcome_for_every_helper(tmp_path, origin, monkeypatch):
    monkeypatch.setenv("COORDINATOR_FAULT", "after_record")
    monkeypatch.setenv("ALPACA_PROFILE", "production")
    store, broker, clock = writer_store(tmp_path, origin, "a"), Broker(), Clock()
    with pytest.raises(Outcome) as info:
        coordinate(entry_body(), store=store, writer="w", read=broker.read, run=broker.run, clock=clock,
                   sleep=clock.sleep)
    assert (info.value.code, info.value.state) == (2, "usage") and broker.posts == [] and stored(origin) == []
