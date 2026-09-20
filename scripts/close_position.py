#!/usr/bin/env python3
"""Close a position through a resumable cancel -> close (spec section 6: recovered exits).

    python3 scripts/close_position.py --symbol AMD
    python3 scripts/close_position.py --symbol AMD --reason "cut at -7% per rule"

Replaces the hand-written `cancel ORDER_ID` + `close SYM` pair in the midday
cut path (CUT_LOSER_STEPS). Each step is confirmed from broker state, and the
exit order carries client_order_id cl-<YYYYMMDD>-<SYMBOL> so a rerun after a
crash or timeout resumes instead of selling twice:

  0. Lookup by client id. A live or filled close from an earlier run is
     authoritative: exit 0.
  1. Preflight the market sell through validate_mutation while the stop rests.
  2. Cancel every resting protective stop; poll until the broker confirms
     `canceled`. A stop that filled instead means the position is gone: exit 0.
     A stop that will not cancel still protects: exit 3, nothing sold.
  3. Confirm the position is still held, then submit the market sell (GTC)
     through scripts/alpaca.sh, which validates the exact body again.
  4. Confirm by client id. Not found: the position is now NAKED (stop gone,
     no exit resting): exit 8, rerun this exact command immediately.

Exit codes (JSON on stdout):
    0  close submitted or confirmed, or the position was already gone
    2  usage (no such position)
    3  refused; the resting stop still protects
    4  broker state unavailable before any change
    8  INCIDENT: position may be unprotected; rerun the same command now
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.replace_stop import (EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED,  # noqa: E402
                                  EXIT_USAGE, LIVE, OPEN, Outcome, mutate)
from scripts.validate_mutation import validate_mutation  # noqa: E402
from scripts.validate_order import adapter  # noqa: E402

CLOSE_PREFIX = "cl-"


def close_client_id(symbol: str, day) -> str:
    cid = f"{CLOSE_PREFIX}{day:%Y%m%d}-{symbol.upper()}"
    if not re.fullmatch(r"[A-Za-z0-9-]{1,48}", cid):
        raise ValueError(f"client_order_id {cid!r} is not broker-safe")
    return cid


def _held(read, symbol):
    positions = read("positions")
    if not isinstance(positions, list):
        raise ValueError("positions snapshot is not a list")
    for p in positions:
        if isinstance(p, dict) and str(p.get("symbol", "")).upper() == symbol:
            return p
    return None


def _resting_stops(read, symbol):
    orders = read("orders", "open")
    if not isinstance(orders, list):
        raise ValueError("open-order snapshot is not a list")
    return [o for o in orders if isinstance(o, dict) and str(o.get("symbol", "")).upper() == symbol
            and o.get("side") == "sell" and o.get("type") in ("stop", "trailing_stop")
            and o.get("status") in OPEN | {"partially_filled", "pending_cancel"}]


def close_position(symbol: str, now: datetime, **deps) -> None:
    symbol = symbol.upper()
    progress = {"cancel_sent": False}
    try:
        _close_position(symbol, now, progress, **deps)
    except SystemExit as exc:
        if progress["cancel_sent"]:
            raise Outcome(EXIT_UNPROTECTED, "broker_state_unavailable_rerun_to_resume", symbol=symbol,
                          adapter_exit=exc.code)
        raise Outcome(EXIT_NO_STATE, "broker_state_unavailable", symbol=symbol, adapter_exit=exc.code)
    except (ValueError, TypeError, KeyError) as exc:
        if progress["cancel_sent"]:
            raise Outcome(EXIT_UNPROTECTED, "unreadable_broker_state_rerun_to_resume", symbol=symbol,
                          error=str(exc))
        raise Outcome(EXIT_NO_STATE, "unreadable_broker_state", symbol=symbol, error=str(exc))
    raise AssertionError("close_position must end in an Outcome")


def _close_position(symbol, now, progress, *, read=adapter, run=mutate, check=validate_mutation,
                    sleep=time.sleep, polls=20):
    cid = close_client_id(symbol, now.date())
    # 0. Resume: a close from an earlier run is authoritative.
    prior = read("order-by-client", cid)
    if isinstance(prior, dict) and prior.get("status") in OPEN | {"partially_filled", "filled"}:
        raise Outcome(EXIT_OK, "already_closing" if prior.get("status") != "filled" else "already_closed",
                      symbol=symbol, client_order_id=cid, order=prior)

    held = _held(read, symbol)
    stops = _resting_stops(read, symbol)
    if held is None:
        if stops:
            raise Outcome(EXIT_USAGE, "no_position_but_stop_resting", symbol=symbol,
                          stop_order_ids=[str(o.get("id")) for o in stops])
        raise Outcome(EXIT_USAGE, "no_position", symbol=symbol)
    qty = str(Decimal(str(held["qty"])))
    body = {"symbol": symbol, "qty": qty, "side": "sell", "type": "market", "time_in_force": "gtc"}

    # 1. Preflight while the stop still rests and protects.
    try:
        check("order", json.dumps(body))
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise Outcome(EXIT_REFUSED, "refused", symbol=symbol, reason=str(exc))

    # 2. Cancel every resting stop; confirm each from broker state.
    for stop in stops:
        oid = str(stop["id"])
        if stop.get("status") != "pending_cancel":
            progress["cancel_sent"] = True
            ok, http, _, err = run("cancel", oid)
            if not ok:
                print(f"cancel {oid} reported failure (HTTP {http}): {err}", file=sys.stderr)
        else:
            progress["cancel_sent"] = True  # resuming an earlier run's cancel
        status = None
        for attempt in range(polls):
            current = read("order-info", oid)
            status = current.get("status") if isinstance(current, dict) else None
            if status in ("canceled", "filled", "expired", "rejected") or (status in OPEN and attempt >= 3):
                break
            sleep(1)
        if status == "filled":
            raise Outcome(EXIT_OK, "stop_filled_position_gone", symbol=symbol, stop_order_id=oid)
        if status in OPEN:
            raise Outcome(EXIT_REFUSED, "cancel_rejected_stop_still_protects", symbol=symbol,
                          stop_order_id=oid, status=status)
        if status not in ("canceled", "expired", "rejected"):
            raise Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed", symbol=symbol, stop_order_id=oid, status=status)

    # 3. The stop is gone. Confirm the position, then sell it.
    held = _held(read, symbol)
    if held is None:
        raise Outcome(EXIT_OK, "position_gone", symbol=symbol)
    body["qty"] = str(Decimal(str(held["qty"])))
    body["client_order_id"] = cid
    ok, http, out, err = run("order", json.dumps(body))

    # 4. Confirm by client id regardless of what the HTTP layer said.
    placed = read("order-by-client", cid)
    if isinstance(placed, dict) and placed.get("status") in LIVE | {"partially_filled", "filled"}:
        raise Outcome(EXIT_OK, "close_submitted", symbol=symbol, client_order_id=cid, order=placed,
                      http_status=http, stops_canceled=[str(o["id"]) for o in stops])
    raise Outcome(EXIT_UNPROTECTED, "close_failed_position_naked_rerun", symbol=symbol, client_order_id=cid,
                  http_status=http, reason=err or out, stops_canceled=[str(o["id"]) for o in stops])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--reason", default="", help="recorded in the JSON report only")
    args = parser.parse_args()
    try:
        close_position(args.symbol, datetime.now(timezone.utc))
    except Outcome as outcome:
        print(json.dumps({"state": outcome.state, "exit": outcome.code, "reason_given": args.reason,
                          **outcome.detail}, default=str))
        return outcome.code
    raise AssertionError("close_position must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
