#!/usr/bin/env python3
"""Replace a resting protective stop (trailing or fixed), resumably.

The one sanctioned path for cancel -> replace (midday tighten, fixed-leg
conversion). Every step is derived from broker state, so rerunning the same
command after a crash, timeout or lost response resumes instead of duplicating:

    python3 scripts/replace_stop.py --order-id OLD_BROKER_ID --trail-percent 7
    python3 scripts/replace_stop.py --order-id OLD_BROKER_ID --stop-price 104.50   # expiry renewal

  1. Preflight while the old stop still rests: the exact replacement body goes
     through validate_mutation against the old stop's actual stop_price. A
     refusal changes nothing (exit 3).
  2. Cancel, then poll until the broker confirms `canceled`. If the old stop
     filled instead, the position is gone and nothing is replaced (exit 0).
  3. Submit the replacement with client_order_id rs-<old id>. The broker
     rejects duplicate client ids, and step 0 looks it up first on a rerun.
  4. If the replacement cannot be confirmed, re-place a fixed stop at the old
     stop's exact level (rr-<old id>) and report an incident.

Exit codes (JSON state always on stdout):
    0  replaced (or already replaced), or old stop filled -- nothing unprotected
    2  usage / old order is not a replaceable protective stop
    3  refused in preflight -- old stop untouched
    4  broker state unavailable before any mutation -- old stop untouched
    7  INCIDENT: replacement failed, old level restored as a fixed stop; email
    8  INCIDENT: position may be UNPROTECTED -- rerun this exact command now
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_mutation import REPLACE_PREFIX, RESTORE_PREFIX, validate_mutation  # noqa: E402
from scripts.validate_order import adapter  # noqa: E402

ADAPTER = Path(__file__).resolve().parent / "alpaca.sh"
OPEN = {"new", "accepted", "pending_new", "held", "accepted_for_bidding"}
LIVE = {"new", "accepted", "pending_new"}
EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_NO_STATE, EXIT_RESTORED, EXIT_UNPROTECTED = 0, 2, 3, 4, 7, 8


class Outcome(Exception):
    def __init__(self, code, state, **detail):
        super().__init__(state)
        self.code, self.state, self.detail = code, state, detail


def mutate(command, argument):
    """Run a mutation through alpaca.sh (which re-validates it). Returns (ok, http, stdout, stderr)."""
    status = Path(os.environ.get("TMPDIR", "/tmp")) / f"replace_stop_{os.getpid()}_{time.time_ns()}"
    env = {**os.environ, "ALPACA_RISK_OK": "1", "ALPACA_HTTP_STATUS_FILE": str(status)}
    try:
        proc = subprocess.run(["bash", str(ADAPTER), command, argument], capture_output=True,
                              text=True, env=env, timeout=90)
        http = status.read_text().strip() if status.exists() else "000"
    except subprocess.TimeoutExpired:
        return False, "000", "", "adapter timed out; outcome unknown"
    finally:
        status.unlink(missing_ok=True)
    return proc.returncode == 0, http, proc.stdout.strip(), proc.stderr.strip()


def replace_stop(order_id, trail_percent=None, stop_price=None, **deps):
    if (trail_percent is None) == (stop_price is None):
        raise Outcome(EXIT_USAGE, "exactly_one_of_trail_percent_or_stop_price")
    progress = {"cancel_sent": False}
    try:
        _replace_stop(order_id, trail_percent, stop_price, progress, **deps)
    except SystemExit as exc:
        # A broker read failed. Before cancel nothing changed; after it, a rerun resumes.
        if progress["cancel_sent"]:
            raise Outcome(EXIT_UNPROTECTED, "broker_state_unavailable_rerun_to_resume", adapter_exit=exc.code)
        raise Outcome(EXIT_NO_STATE, "broker_state_unavailable", adapter_exit=exc.code)
    raise AssertionError("replace_stop must end in an Outcome")


def _replace_stop(order_id, trail_percent, stop_price, progress, *, read=adapter, run=mutate, check=validate_mutation,
                  sleep=time.sleep, polls=20):
    old = read("order-info", order_id)
    if not (isinstance(old, dict) and old.get("id") == order_id and old.get("side") == "sell"
            and old.get("type") in ("stop", "trailing_stop")):
        raise Outcome(EXIT_USAGE, "not_a_protective_stop", order_id=order_id)
    symbol = old["symbol"]
    qty = str(Decimal(str(old["qty"])) - Decimal(str(old.get("filled_qty") or 0)))
    rid, restore_id = REPLACE_PREFIX + order_id, RESTORE_PREFIX + order_id
    body = {"symbol": symbol, "qty": qty, "side": "sell", "time_in_force": "gtc", "client_order_id": rid}
    if trail_percent is not None:
        body.update(type="trailing_stop", trail_percent=str(Decimal(str(trail_percent))))
    else:
        body.update(type="stop", stop_price=str(Decimal(str(stop_price))))

    # 0. Resume: a replacement or restore from an earlier run is authoritative.
    for cid, code, state in ((rid, EXIT_OK, "already_replaced"), (restore_id, EXIT_RESTORED, "already_restored")):
        prior = read("order-by-client", cid)
        if isinstance(prior, dict) and prior.get("status") in OPEN | {"filled"}:
            raise Outcome(code, state, symbol=symbol, order=prior)

    status = old.get("status")
    if status == "filled":
        raise Outcome(EXIT_OK, "old_stop_filled", symbol=symbol)
    if status in OPEN:
        # 1. Preflight while the old stop still rests and protects.
        try:
            check("order", json.dumps({k: v for k, v in body.items() if k != "client_order_id"}))
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            raise Outcome(EXIT_REFUSED, "refused", symbol=symbol, reason=str(exc))
        progress["cancel_sent"] = True
        ok, http, _, err = run("cancel", order_id)
        if not ok:
            # Unknown outcome: fall through to polling rather than assuming either way.
            print(f"cancel reported failure (HTTP {http}): {err}", file=sys.stderr)
    else:
        if status not in ("pending_cancel", "canceled"):
            raise Outcome(EXIT_USAGE, "old_stop_not_replaceable", symbol=symbol, status=status)
        progress["cancel_sent"] = True  # resuming an earlier run's cancel

    # 2. Confirm cancellation from broker state.
    for attempt in range(polls):
        old = read("order-info", order_id)
        status = old.get("status") if isinstance(old, dict) else None
        if status in ("canceled", "filled") or (status in OPEN and attempt >= 3):
            break
        sleep(1)
    if status == "filled":
        raise Outcome(EXIT_OK, "old_stop_filled", symbol=symbol)
    if status in OPEN:
        raise Outcome(EXIT_REFUSED, "cancel_rejected_old_stop_still_protects", symbol=symbol, status=status)
    if status != "canceled":
        raise Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed", symbol=symbol, status=status)

    # 3. Submit the replacement; confirm by client id regardless of exit status.
    ok, http, out, err = run("order", json.dumps(body))
    placed = read("order-by-client", rid)
    if isinstance(placed, dict) and placed.get("status") in LIVE | {"filled"}:
        raise Outcome(EXIT_OK, "replaced", symbol=symbol, order=placed, http_status=http)

    # 4. Restore the exact prior level.
    restore = {"symbol": symbol, "qty": qty, "side": "sell", "type": "stop", "time_in_force": "gtc",
               "stop_price": str(old["stop_price"]), "client_order_id": restore_id}
    _, restore_http, _, _ = run("order", json.dumps(restore))
    restored = read("order-by-client", restore_id)
    if isinstance(restored, dict) and restored.get("status") in LIVE | {"filled"}:
        # http_status describes `order` (the restore) so callers can ledger it.
        raise Outcome(EXIT_RESTORED, "replacement_failed_old_level_restored", symbol=symbol,
                      order=restored, http_status=restore_http,
                      replacement_error=err or out, replacement_http_status=http)
    raise Outcome(EXIT_UNPROTECTED, "replacement_and_restore_failed", symbol=symbol,
                  replacement_error=err or out, replacement_http_status=http)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--order-id", required=True, help="broker id of the resting protective stop")
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--trail-percent", help="replacement trailing stop percent (3-10)")
    kind.add_argument("--stop-price", help="replacement fixed stop price (e.g. GTC expiry renewal)")
    args = parser.parse_args()
    try:
        replace_stop(args.order_id, args.trail_percent, args.stop_price)
    except Outcome as outcome:
        print(json.dumps({"state": outcome.state, "exit": outcome.code, **outcome.detail}, default=str))
        return outcome.code
    raise AssertionError("replace_stop must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
