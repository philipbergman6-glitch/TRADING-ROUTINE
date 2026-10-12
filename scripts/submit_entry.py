#!/usr/bin/env python3
"""Submit an OTO entry idempotently (spec section 6: stable buy IDs).

    python3 scripts/submit_entry.py --symbol AMD --qty 10 --price 100
    python3 scripts/submit_entry.py --symbol AMD --qty 10 --stop-price 93
    python3 scripts/submit_entry.py --symbol AMD --qty 10 --price 100 --tag b      # deliberate 2nd entry today
    python3 scripts/submit_entry.py --symbol AMD --qty 10 --price 100 --intent en-20261012-AMD   # rerun, any day

The buy is one entry *intent* (ADR 0005) named en-<YYYYMMDD>-<SYMBOL>[-<tag>],
derived from the mint day and the name rather than generated. Each POST is an
*attempt* with client_order_id = the intent id, then -r1 .. -r5 once the
broker confirms an earlier attempt dead (canceled, expired, rejected,
replaced): Alpaca refuses a reused client id, so a dead attempt never blocks
the symbol. The JSON output names the intent and a `rerun` command carrying
--intent, so a rerun after a crash, timeout, lost response or UTC midnight
looks the order up instead of buying twice:

  0. Resolve the intent with the shared resolver (scripts/execution_identity.py):
     --intent, else a live attempt from today or yesterday, else today's
     intent. A live attempt is reported as already_submitted, a filled one as
     already_filled; exit 0 without submitting. A filled entry from yesterday
     is history and does not block a new entry today.
  1. Submit the next attempt through scripts/alpaca.sh, which validates the
     exact body against current broker state (fresh ask, sizing, pending-buy
     gate, protection).
  2. Confirm by client id regardless of what the HTTP layer said. Not found
     after a refused response: exit 3. Not found after an unknown outcome:
     exit 8 and rerun the printed command (it re-POSTs the same attempt id, so
     a landed order answers 422 and is found by lookup).

The fixed protective leg is derived at the active version's entry distance
when --price is given. Conversion to the trailing stop is the protection
monitor's job (or STEP 5 of market-open); this script never converts.

Exit codes derive from broker coverage, not from what this process did: when
the symbol is already held, its live coverage (risk_engine.reconciliation) is
read before submission, and a refusal on a held position with no verified
protective stop is reported as exit 8 rather than hidden behind exit 3.

Exit codes (JSON on stdout):
    0  submitted, or already submitted / filled by an earlier run
    2  usage (including a malformed --intent or --tag)
    3  refused by the mutation gate or the broker, or every attempt of the
       intent is dead (entry_retries_exhausted); nothing submitted, and any
       existing position in the symbol verifiably keeps its stop
    4  broker state unavailable before submission; nothing submitted
    8  outcome unknown after submission (rerun the printed command now), or
       refused while the symbol is held without a verified protective stop
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import FixedStop, build_oto_entry, fixed_stop_at_distance, params_from_env  # noqa: E402
from scripts.execution_identity import mint_intent, parse_intent, resolve_intent  # noqa: E402
from scripts.replace_stop import (EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, EXIT_USAGE,  # noqa: E402
                                  Outcome, live_coverage, mutate)
from scripts.validate_order import adapter  # noqa: E402

KIND = "en"
DEAD = {"canceled", "expired", "rejected", "replaced"}


def submit_entry(body: dict, *, intent: str | None = None, tag: str | None = None, read=adapter, run=mutate,
                 now=None) -> None:
    if "client_order_id" in body:
        raise ValueError("client_order_id is assigned from the intent; pass --intent or --tag instead")
    symbol = str(body["symbol"]).upper()
    now = now or datetime.now(timezone.utc)
    named = {}
    try:
        res = resolve_intent(read, KIND, symbol, now, intent=intent, tag=tag, dead=DEAD)
        named = {"intent": res.intent}
        if res.live or res.filled:
            raise Outcome(EXIT_OK, "already_filled" if res.filled else "already_submitted",
                          client_order_id=res.client_order_id, order=res.order, **named)
        _, coverage = live_coverage(read, symbol, now)
    except SystemExit as exc:
        raise Outcome(EXIT_NO_STATE, "broker_state_unavailable", adapter_exit=exc.code, **named)
    except (ValueError, TypeError, KeyError) as exc:
        raise Outcome(EXIT_NO_STATE, "unreadable_broker_state", error=str(exc), **named)
    cid = res.client_order_id

    def refusal(state, **detail):
        # A refused add changes nothing, but an already-held symbol with no verified
        # protective stop is an incident whichever process lost it.
        if coverage is not None and not coverage["ok"]:
            return Outcome(EXIT_UNPROTECTED, f"{state}_position_unprotected", client_order_id=cid,
                           coverage=coverage, **named, **detail)
        return Outcome(EXIT_REFUSED, state, client_order_id=cid, **named, **detail)

    if res.exhausted:
        raise refusal("entry_retries_exhausted", dead_attempts=res.dead)
    attempt = {**body, "client_order_id": cid}
    ok, http, out, err = run("order", json.dumps(attempt))
    try:
        placed = read("order-by-client", cid)
    except SystemExit as exc:
        raise Outcome(EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun", client_order_id=cid,
                      http_status=http, adapter_exit=exc.code, **named)
    if isinstance(placed, dict) and placed.get("status") not in DEAD:
        raise Outcome(EXIT_OK, "submitted", client_order_id=cid, order=placed, http_status=http,
                      dead_attempts=res.dead, **named)
    if isinstance(placed, dict):
        raise refusal("broker_rejected", order=placed, http_status=http)
    if http.startswith("4") or (http == "000" and not ok and "REFUSED" in err):
        raise refusal("refused", http_status=http, reason=err or out)
    raise Outcome(EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun", client_order_id=cid,
                  http_status=http, reason=err or out, **named)


def rerun_command(args, intent: str | None) -> str:
    """The exact command to rerun; it names the intent so a later UTC day resolves this entry."""
    parts = ["python3", "scripts/submit_entry.py", "--symbol", args.symbol.upper(), "--qty", args.qty]
    parts += ["--price", args.price] if args.price else ["--stop-price", args.stop_price]
    parts += ["--intent", intent] if intent else (["--tag", args.tag] if args.tag else [])
    return shlex.join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--qty", required=True)
    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument("--price", help="expected entry; fixed leg derived at the version's entry distance")
    price.add_argument("--stop-price", help="explicit fixed protective leg")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--tag", help="seq for a deliberate second entry the same day (not r<digits>)")
    identity.add_argument("--intent", help="resolve this entry intent (from an earlier run's output), any day")
    args = parser.parse_args()
    params = params_from_env(os.environ)
    try:
        today = datetime.now(timezone.utc).date()
        if args.intent is not None:
            parse_intent(args.intent, KIND, args.symbol, today)
        else:
            mint_intent(KIND, args.symbol, today, args.tag)  # validates symbol and tag
        protection = (FixedStop(stop_price=Decimal(args.stop_price)) if args.stop_price
                      else fixed_stop_at_distance(args.price, params.entry_stop_pct))
        body = build_oto_entry(symbol=args.symbol, qty=args.qty, protection=protection)
        submit_entry(body, intent=args.intent, tag=args.tag)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"state": "usage", "exit": EXIT_USAGE, "reason": str(exc)}))
        return EXIT_USAGE
    except Outcome as outcome:
        print(json.dumps({"state": outcome.state, "exit": outcome.code, "strategy_version": params.name,
                          **outcome.detail, "rerun": rerun_command(args, outcome.detail.get("intent"))},
                         default=str))
        return outcome.code
    raise AssertionError("submit_entry must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
