#!/usr/bin/env python3
"""Close a position through a resumable cancel -> close (spec section 6: recovered exits).

    python3 scripts/close_position.py --symbol AMD
    python3 scripts/close_position.py --symbol AMD --reason "cut at -7% per rule"
    python3 scripts/close_position.py --symbol AMD --intent cl-20261012-AMD   # rerun, any day

Replaces the hand-written `cancel ORDER_ID` + `close SYM` pair in the midday
cut path (CUT_LOSER_STEPS). Each step is confirmed from broker state, and the
whole close is one coordinated action (scripts/coordinator.py, ADR 0010): the
account-wide lease is taken, unfinished intents are recovered, a refusal is
recorded, and the intent (with the stops it will cancel) is recorded before
the first cancel, so a process that dies between cancel and sell leaves
enough for recovery to re-place those stops. The exit
is one close *intent* (ADR 0005) named cl-<YYYYMMDD>-<SYMBOL>[-<seq>]; each
sell submitted for it is an *attempt* with client_order_id = the intent id,
then -r1 .. -r5 after the broker confirms an earlier attempt dead. A rerun
after a crash or timeout resumes the intent instead of selling twice. The JSON
output names the intent and a `rerun` command carrying --intent, so a rerun
after UTC midnight resolves the same intent.

  0. Resolve the intent (scripts/execution_identity.py): --intent, else a live
     attempt from today or yesterday, else today's latest intent or a new one.
  1. Read holdings. A close is complete only when the symbol is not held AND
     no buy for it is live: a filled close attempt proves an earlier position
     lifecycle ended, never that today's holdings are zero. A filled intent
     with the symbol still held means a new lifecycle: a new intent (-2, -3..)
     is minted. A live close attempt is adopted only while the symbol is held.
  2. Refuse when the run is not bound to the approved strategy version (ADR
     0011): a close is never protective restoration. Then preflight the
     market sell through validate_mutation while the stop rests.
  3. Cancel every resting protective stop; poll until the broker confirms
     `canceled`. A stop that filled instead proves nothing about quantity added
     after it was sized: holdings are re-read and any remainder is sold under
     the same intent. A stop that will not cancel still protects: exit 3.
  4. Re-read holdings, then submit the market sell (GTC) through
     scripts/alpaca.sh, which validates the exact body again.
  5. Confirm by client id. Not found: the position is now NAKED (stop gone,
     no exit resting): exit 8, rerun the printed command immediately.

Exit codes derive from broker coverage, not from what this process did: the
symbol's live coverage (risk_engine.reconciliation: an unexpired GTC stop
resting as `new` for the full held quantity) is read before preflight, and
every refusal or read failure is classified against it. A rerun after an
earlier process canceled the stop and died therefore reports 8, never 3.

Exit codes (JSON on stdout):
    0  close submitted, a live close attempt adopted while held, or complete
       (close_complete / position_gone / stop_filled_position_gone: the symbol
       is not held and no buy for it is live)
    2  usage: no such position, malformed --intent, rulebook pins that name no
       approved version, or an anomaly that needs a human (a stop or a close
       attempt resting with nothing held)
    3  refused; nothing changed and nothing held is uncovered: a verified
       protective stop still rests, or the symbol is no longer held but a buy
       for it is live (position_gone_buy_live: another writer is re-entering)
    4  broker state unavailable before any change, with no uncovered position
       observed; retry later
    8  INCIDENT: the position has no verified protective stop (refused or
       unreadable while uncovered, or mid cancel->close); rerun the printed
       command now, and escalate if it repeats
   10  state store unavailable; nothing changed
   11  the lease stayed held past the wait budget; nothing changed
   12  acted, but the outcome could not be recorded in the store (alerted)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import shlex
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import coordinator  # noqa: E402
from scripts.coordinator import live_buys as _live_buys  # noqa: E402
from scripts.execution_identity import Resolution, next_free_intent, parse_intent, resolve_intent  # noqa: E402
from scripts.replace_stop import (EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, EXIT_USAGE, LIVE,  # noqa: E402
                                  OPEN, Outcome, live_coverage, mutate, observed_unprotected,
                                  state_unavailable)
from scripts.state_store import StoreUnavailable  # noqa: E402
from scripts.strategy_version import bind  # noqa: E402
from scripts.validate_mutation import validate_mutation  # noqa: E402
from scripts.validate_order import adapter  # noqa: E402

KIND = "cl"


def _not_held(symbol, orders, state, **detail):
    """Holdings are zero. The close is complete only if no buy for the symbol is live."""
    buys = _live_buys(orders, symbol)
    if buys:
        raise Outcome(EXIT_REFUSED, "position_gone_buy_live", symbol=symbol,
                      buy_client_order_ids=[o.get("client_order_id") for o in buys],
                      buy_order_ids=[str(o.get("id")) for o in buys], **detail)
    raise Outcome(EXIT_OK, state, symbol=symbol, **detail)


def _resting_stops(orders, symbol):
    """Every stop of ours still at the broker, including ones that do not certify coverage
    (held, pending_cancel): all of them must be gone before the market sell."""
    return [o for o in orders if isinstance(o, dict) and str(o.get("symbol", "")).upper() == symbol
            and o.get("side") == "sell" and o.get("type") in ("stop", "trailing_stop")
            and o.get("status") in OPEN | {"partially_filled", "pending_cancel"}]


def close_position(symbol: str, now: datetime, intent: str | None = None, binding=None, *, read=adapter,
                   run=mutate, store=None, writer=None, clock=None, sleep=time.sleep, fault=None, **deps) -> None:
    symbol = symbol.upper()
    binding = binding or bind(os.environ)  # pins naming no approved version: VersionBindingError (usage)
    clock = clock or coordinator._now  # lease timing is wall time, never the caller's `now`
    storeless = None
    if store is None:
        try:
            store = coordinator.open_store()
        except StoreUnavailable as exc:
            storeless = str(exc)

    def body(session):
        _coordinated_close(session, symbol, now, intent, binding, read=read, sleep=sleep, **deps)
    coordinator.coordinate(body, store=store, writer=writer or coordinator.writer_id("close_position"),
                           read=read, run=run, clock=clock, sleep=sleep, fault=fault, binding=binding,
                           storeless_error=storeless)


def _coordinated_close(session, symbol, now, intent, binding, **deps):
    progress = {"cancel_sent": False, "coverage": None, "intent": None, "binding": binding}
    try:
        _close_position(symbol, now, progress, intent, session=session, **deps)
    except Outcome as outcome:
        if progress["intent"]:
            outcome.detail.setdefault("intent", progress["intent"])
        raise
    except SystemExit as exc:
        # Classified from coverage observed so far, not from this process alone.
        raise state_unavailable(progress, "broker_state_unavailable_rerun_to_resume", symbol=symbol,
                                adapter_exit=exc.code, **_named(progress))
    except (ValueError, TypeError, KeyError) as exc:
        unreadable = state_unavailable(progress, "unreadable_broker_state_rerun_to_resume", symbol=symbol,
                                       error=str(exc), **_named(progress))
        if unreadable.state == "broker_state_unavailable":
            unreadable.state = "unreadable_broker_state"
        raise unreadable
    raise AssertionError("close_position must end in an Outcome")


def _named(progress):
    return {"intent": progress["intent"]} if progress["intent"] else {}


def _close_position(symbol, now, progress, intent, *, session, read=adapter, check=validate_mutation,
                    sleep=time.sleep, polls=20):
    run = session.run
    orders = read("orders", "open")
    held, coverage = live_coverage(read, symbol, now, orders=orders)
    progress["coverage"] = coverage
    # 0. Resolve the intent. Its attempts are evidence about earlier sells, not holdings;
    #    the store also knows intents that never reached the broker.
    known = session.known_intents()
    res = resolve_intent(read, KIND, symbol, now, intent=intent, known=known)
    progress["intent"] = res.intent
    stops = _resting_stops(orders, symbol)

    # 1. Not held: complete only when no buy is live; anything resting otherwise is an anomaly.
    if held is None:
        if res.live:
            raise Outcome(EXIT_USAGE, "close_resting_without_position", symbol=symbol,
                          client_order_id=res.client_order_id, order=res.order)
        if _live_buys(orders, symbol):
            _not_held(symbol, orders, "position_gone")
        if stops:
            raise Outcome(EXIT_USAGE, "no_position_but_stop_resting", symbol=symbol,
                          stop_order_ids=[str(o.get("id")) for o in stops])
        if res.filled:
            _not_held(symbol, orders, "close_complete", client_order_id=res.client_order_id, order=res.order)
        raise Outcome(EXIT_USAGE, "no_position", symbol=symbol)

    # Held: a live close attempt from an earlier run is still working on it.
    if res.live:
        raise Outcome(EXIT_OK, "already_closing", symbol=symbol, client_order_id=res.client_order_id,
                      order=res.order)
    superseded = {}
    stored = session.state_of(res.intent)
    finished = stored is not None and stored not in coordinator.NON_TERMINAL
    if res.filled or finished:
        # That intent's lifecycle ended (or the store holds it as finished); this
        # is a new one and gets a new intent.
        superseded = ({"superseded_intent": res.intent, "superseded_order": res.order} if res.filled
                      else {"superseded_intent": res.intent, "superseded_state": stored})
        nxt = next_free_intent(read, KIND, symbol, now, known=known)
        if nxt is None:
            raise Outcome(EXIT_UNPROTECTED if observed_unprotected(progress) else EXIT_REFUSED,
                          "close_intents_exhausted_manual_exit_required", symbol=symbol, coverage=coverage,
                          **superseded)
        res = Resolution(nxt, nxt)
        progress["intent"] = nxt
    if res.exhausted:
        raise Outcome(EXIT_UNPROTECTED if observed_unprotected(progress) else EXIT_REFUSED,
                      "close_retries_exhausted_manual_exit_required", symbol=symbol, dead_attempts=res.dead,
                      coverage=coverage)
    cid, dead = res.client_order_id, res.dead
    qty = str(Decimal(str(held["qty"])))
    body = {"symbol": symbol, "qty": qty, "side": "sell", "type": "market", "time_in_force": "gtc"}

    def refusal(state, code=EXIT_REFUSED, **detail):
        if observed_unprotected(progress):
            return Outcome(EXIT_UNPROTECTED, f"{state}_position_unprotected", symbol=symbol, coverage=coverage,
                           **detail)
        return Outcome(code, state, symbol=symbol, **detail)

    def refuse(state, reason):
        session.refuse(res.intent, refusal(state, reason=reason), action="close", symbol=symbol, reasons=[reason])

    # 2. An unbound run changes nothing; the code still derives from coverage (ADR 0006).
    if progress["binding"].error:
        refuse("version_binding_refused", progress["binding"].error)

    #    Preflight while the stop still rests. A refusal is "still protects" only when
    #    the broker verifiably covers the position; otherwise it is already an incident.
    try:
        check("order", json.dumps(body))
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        refuse("refused", str(exc))
    # Push 1: the intent and the stops it is about to cancel (recovery re-places them).
    session.record(res.intent, action="close", symbol=symbol, client_order_id=cid,
                   cancels=[str(o["id"]) for o in stops if o.get("id")],
                   refuse=lambda code, state, **d: refusal(state, code, **d))

    # 3. Cancel every resting stop; confirm each from broker state.
    stop_filled = None
    for stop in stops:
        oid = str(stop["id"])
        if stop.get("status") != "pending_cancel":
            progress["cancel_sent"] = True
            cancel_ok, http, _, err = run("cancel", oid)
            if not cancel_ok:
                print(f"cancel {oid} reported failure (HTTP {http}): {err}", file=sys.stderr)
        else:
            progress["cancel_sent"] = True  # resuming an earlier run's cancel
            cancel_ok = True
        # An ACCEPTED cancel may complete after we stop looking: full poll window,
        # then an incident (rerun resumes). Only a REFUSED cancel is "rejected" early.
        status = None
        for attempt in range(polls):
            current = read("order-info", oid)
            status = current.get("status") if isinstance(current, dict) else None
            if status in ("canceled", "filled", "expired", "rejected") or (status in OPEN and not cancel_ok and attempt >= 3):
                break
            sleep(1)
        if status == "filled":
            stop_filled = oid  # proves nothing about quantity added after it was sized
            continue
        if status in OPEN and not cancel_ok:
            raise Outcome(EXIT_REFUSED, "cancel_rejected_stop_still_protects", symbol=symbol,
                          stop_order_id=oid, status=status)
        if status in OPEN:
            raise Outcome(EXIT_UNPROTECTED, "cancel_accepted_but_unconfirmed_rerun", symbol=symbol,
                          stop_order_id=oid, status=status, polled_seconds=polls)
        if status not in ("canceled", "expired", "rejected"):
            raise Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed", symbol=symbol, stop_order_id=oid, status=status)

    # 4. The stops are gone. Re-read holdings, then sell whatever is still held.
    orders = read("orders", "open")
    held, _ = live_coverage(read, symbol, now, orders=orders)
    if held is None:
        if stop_filled:
            _not_held(symbol, orders, "stop_filled_position_gone", stop_order_id=stop_filled)
        _not_held(symbol, orders, "position_gone")
    body["qty"] = str(Decimal(str(held["qty"])))
    body["client_order_id"] = cid
    # Run records collect this line (ADR 0012); the intent itself is already on main.
    print(f"intent {progress['intent']}: submitting attempt {cid}", file=sys.stderr, flush=True)
    # 5. Confirm by client id regardless of what the HTTP layer said (lost-response
    #    budget included: the same attempt id is re-POSTed, never a new one).
    placed, http, reason, _ = session.post(cid, json.dumps(body))
    if isinstance(placed, dict) and placed.get("status") in LIVE | {"partially_filled", "filled"}:
        raise Outcome(EXIT_OK, "close_submitted", symbol=symbol, client_order_id=cid, order=placed,
                      http_status=http, stops_canceled=[str(o["id"]) for o in stops], dead_attempts=dead,
                      **({"stop_filled": stop_filled} if stop_filled else {}), **superseded)
    raise Outcome(EXIT_UNPROTECTED, "close_failed_position_naked_rerun", symbol=symbol, client_order_id=cid,
                  http_status=http, reason=reason, stops_canceled=[str(o["id"]) for o in stops])


def rerun_command(symbol: str, intent: str | None, reason: str) -> str:
    """The exact command a human or routine reruns; it names the intent so a rerun on
    a later UTC day resolves this close rather than minting a new one."""
    parts = ["python3", "scripts/close_position.py", "--symbol", symbol.upper()]
    if intent:
        parts += ["--intent", intent]
    if reason:
        parts += ["--reason", reason]
    return shlex.join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--reason", default="", help="recorded in the JSON report only")
    parser.add_argument("--intent", help="resolve this close intent (from an earlier run's output), any day")
    args = parser.parse_args()
    try:
        if args.intent is not None:
            parse_intent(args.intent, KIND, args.symbol, datetime.now(timezone.utc).date())
        close_position(args.symbol, datetime.now(timezone.utc), intent=args.intent)
    except ValueError as exc:  # --intent validation or unreadable pins; broker reads are classified inside
        print(json.dumps({"state": "usage", "exit": EXIT_USAGE, "reason": str(exc)}))
        return EXIT_USAGE
    except Outcome as outcome:
        coordinator.send_alerts(outcome)
        intent = outcome.detail.get("intent")
        print(json.dumps({"state": outcome.state, "exit": outcome.code, "reason_given": args.reason,
                          **outcome.detail, "rerun": rerun_command(args.symbol, intent, args.reason)},
                         default=str))
        return outcome.code
    raise AssertionError("close_position must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
