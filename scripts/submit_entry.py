#!/usr/bin/env python3
"""Submit an OTO entry idempotently (spec section 6: stable buy IDs).

    python3 scripts/submit_entry.py --symbol AMD --qty 10 --price 100
    python3 scripts/submit_entry.py --symbol AMD --qty 10 --stop-price 93

The order carries client_order_id en-<YYYYMMDD>-<SYMBOL>[-<tag>], derived from
the day and the name rather than generated, so a rerun after a crash, timeout
or lost response looks the order up instead of buying twice:

  0. Lookup by client id. Found (any status but canceled/expired/rejected):
     report it and exit 0 without submitting.
  1. Submit through scripts/alpaca.sh, which validates the exact body against
     current broker state (fresh ask, sizing, pending-buy gate, protection).
  2. Confirm by client id regardless of what the HTTP layer said. Not found
     after a refused response: exit 3. Not found after an unknown outcome:
     exit 8 and rerun this exact command.

The fixed protective leg is derived at the active version's entry distance
when --price is given. Conversion to the trailing stop is the protection
monitor's job (or STEP 5 of market-open); this script never converts.

Exit codes (JSON on stdout):
    0  submitted, or already submitted by an earlier run
    2  usage
    3  refused by the mutation gate; nothing submitted
    4  broker state unavailable before submission; nothing submitted
    8  outcome unknown after submission; rerun the same command now
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import FixedStop, build_oto_entry, fixed_stop_at_distance, params_from_env  # noqa: E402
from scripts.replace_stop import EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_UNPROTECTED, EXIT_USAGE, Outcome, mutate  # noqa: E402
from scripts.validate_order import adapter  # noqa: E402

ENTRY_PREFIX = "en-"
DEAD = {"canceled", "expired", "rejected", "replaced"}


def entry_client_id(symbol: str, day, tag: str | None = None) -> str:
    cid = f"{ENTRY_PREFIX}{day:%Y%m%d}-{symbol.upper()}"
    if tag:
        if not re.fullmatch(r"[A-Za-z0-9]{1,8}", tag):
            raise ValueError("tag must be 1-8 alphanumerics")
        cid += f"-{tag}"
    if not re.fullmatch(r"[A-Za-z0-9-]{1,48}", cid):
        raise ValueError(f"client_order_id {cid!r} is not broker-safe")
    return cid


def submit_entry(body: dict, *, read=adapter, run=mutate) -> None:
    cid = body["client_order_id"]
    try:
        prior = read("order-by-client", cid)
    except SystemExit as exc:
        raise Outcome(EXIT_NO_STATE, "broker_state_unavailable", adapter_exit=exc.code)
    if isinstance(prior, dict) and prior.get("status") not in DEAD:
        raise Outcome(EXIT_OK, "already_submitted", client_order_id=cid, order=prior)

    ok, http, out, err = run("order", json.dumps(body))
    try:
        placed = read("order-by-client", cid)
    except SystemExit as exc:
        raise Outcome(EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun", client_order_id=cid,
                      http_status=http, adapter_exit=exc.code)
    if isinstance(placed, dict) and placed.get("status") not in DEAD:
        raise Outcome(EXIT_OK, "submitted", client_order_id=cid, order=placed, http_status=http)
    if isinstance(placed, dict):
        raise Outcome(EXIT_REFUSED, "broker_rejected", client_order_id=cid, order=placed, http_status=http)
    if http.startswith("4") or (http == "000" and not ok and "REFUSED" in err):
        raise Outcome(EXIT_REFUSED, "refused", client_order_id=cid, http_status=http, reason=err or out)
    raise Outcome(EXIT_UNPROTECTED, "submitted_outcome_unknown_rerun", client_order_id=cid,
                  http_status=http, reason=err or out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--qty", required=True)
    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument("--price", help="expected entry; fixed leg derived at the version's entry distance")
    price.add_argument("--stop-price", help="explicit fixed protective leg")
    parser.add_argument("--tag", help="optional suffix for a deliberate second entry the same day")
    args = parser.parse_args()
    params = params_from_env(os.environ)
    try:
        cid = entry_client_id(args.symbol, datetime.now(timezone.utc).date(), args.tag)
        protection = (FixedStop(stop_price=Decimal(args.stop_price)) if args.stop_price
                      else fixed_stop_at_distance(args.price, params.entry_stop_pct))
        body = build_oto_entry(symbol=args.symbol, qty=args.qty, protection=protection)
        body["client_order_id"] = cid
        submit_entry(body)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"state": "usage", "exit": EXIT_USAGE, "reason": str(exc)}))
        return EXIT_USAGE
    except Outcome as outcome:
        print(json.dumps({"state": outcome.state, "exit": outcome.code, "strategy_version": params.name,
                          **outcome.detail}, default=str))
        return outcome.code
    raise AssertionError("submit_entry must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
