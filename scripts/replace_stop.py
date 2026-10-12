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

Version binding (ADR 0011): when the run is not bound to the approved strategy
version (scripts/strategy_version.py), nothing is canceled. The one operation
that proceeds is restoration: the old stop is already `canceled` or
`pending_cancel` (an earlier run's cancel), the symbol is held, and its live
coverage is not verified -- steps 3 and 4 then place protection under the
approved version's parameters, the outcome carries `version_exception`, and the
CLI sends a VERSION BINDING INCIDENT alert through scripts/email.sh. Every
other call refuses (exit 3, or 8 when the held position is uncovered).

Exit codes derive from broker coverage, not from what this process did: before
any refusal or read failure is classified, the symbol's live coverage is
checked through risk_engine.reconciliation (an unexpired GTC stop resting as
`new` for the full held quantity). A held position without that verified
coverage is exit 8 whichever process removed the stop, and whether or not this
run changed anything.

Exit codes (JSON state always on stdout):
    0  replaced (or already replaced), or old stop filled -- nothing unprotected
    2  usage / old order is not a replaceable protective stop (and nothing is held) /
       docs/rulebook-pins.json names no approved version
    3  refused in preflight -- the old stop verifiably still protects, untouched
    4  broker state unavailable before any mutation, and no uncovered position
       was observed -- nothing changed, retry later
    7  INCIDENT: replacement failed, old level restored as a fixed stop; email
    8  INCIDENT: position has no verified protective stop (refused, expired or
       unreadable while uncovered, or mid-replacement) -- rerun this exact
       command now; a repeat 8 needs a human
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.reconciliation import reconcile_protection  # noqa: E402
from scripts.strategy_version import VersionBindingError, bind  # noqa: E402
from scripts.validate_mutation import REPLACE_PREFIX, RESTORE_PREFIX, validate_mutation  # noqa: E402
from scripts.validate_order import adapter  # noqa: E402

ADAPTER = Path(__file__).resolve().parent / "alpaca.sh"
EMAIL = Path(__file__).resolve().parent / "email.sh"
OPEN = {"new", "accepted", "pending_new", "held", "accepted_for_bidding"}
LIVE = {"new", "accepted", "pending_new"}
EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_NO_STATE, EXIT_RESTORED, EXIT_UNPROTECTED = 0, 2, 3, 4, 7, 8


class Outcome(Exception):
    def __init__(self, code, state, **detail):
        super().__init__(state)
        self.code, self.state, self.detail = code, state, detail


def live_coverage(read, symbol: str, now: datetime, positions=None, orders=None):
    """Held-vs-verified-protection for one symbol from current broker snapshots.

    Returns (position, report) or (None, None) when the symbol is not held. The
    report is risk_engine.reconciliation's: ok only when unexpired GTC stops resting
    as `new` cover the full held quantity. A stop that is held, pending, expired,
    short, or malformed does not certify coverage -- nor does a truncated order list.
    Snapshots already read by the caller may be passed in to avoid a second read.
    """
    positions = read("positions") if positions is None else positions
    orders = read("orders", "open") if orders is None else orders
    if not isinstance(positions, list):
        raise ValueError("positions snapshot is not a list")
    if not isinstance(orders, list):
        raise ValueError("open-order snapshot is not a list")
    mine = [p for p in positions if isinstance(p, dict) and str(p.get("symbol", "")).upper() == symbol]
    if not mine:
        return None, None
    return mine[0], reconcile_protection(mine, orders, now)


def observed_unprotected(progress: dict) -> bool:
    """True once this process has seen the symbol held without verified coverage, or has
    itself begun removing protection. Drives 8-vs-4 for read failures and 8-vs-3 for refusals."""
    report = progress.get("coverage")
    return bool(progress.get("cancel_sent")) or (report is not None and not report["ok"])


def state_unavailable(progress: dict, state_after_mutation: str, **detail) -> Outcome:
    """Classify a failed broker read: resume-incident after a mutation, incident when an
    uncovered position was observed, otherwise exit 4 (nothing changed, nothing observed)."""
    if progress.get("cancel_sent"):
        return Outcome(EXIT_UNPROTECTED, state_after_mutation, **detail)
    if observed_unprotected(progress):
        return Outcome(EXIT_UNPROTECTED, "broker_state_unavailable_position_unprotected",
                       coverage=progress["coverage"], **detail)
    return Outcome(EXIT_NO_STATE, "broker_state_unavailable", **detail)


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


def replace_stop(order_id, trail_percent=None, stop_price=None, binding=None, **deps):
    if (trail_percent is None) == (stop_price is None):
        raise Outcome(EXIT_USAGE, "exactly_one_of_trail_percent_or_stop_price")
    try:
        binding = binding or bind(os.environ)
    except VersionBindingError as exc:
        raise Outcome(EXIT_USAGE, "version_binding_unreadable", order_id=order_id, reason=str(exc))
    progress = {"cancel_sent": False, "coverage": None, "binding": binding, "version_exception": None}
    try:
        try:
            _replace_stop(order_id, trail_percent, stop_price, progress, **deps)
        except SystemExit as exc:
            # A broker read failed. Classified from coverage observed so far, not from
            # this process alone: after cancel a rerun resumes; an uncovered position
            # seen before cancel is an incident; otherwise nothing changed.
            raise state_unavailable(progress, "broker_state_unavailable_rerun_to_resume", adapter_exit=exc.code)
    except Outcome as outcome:
        if progress["version_exception"]:
            outcome.detail["version_exception"] = progress["version_exception"]
        raise
    raise AssertionError("replace_stop must end in an Outcome")


def version_refusal(progress, symbol):
    """An unbound run changes nothing; the code still derives from broker coverage (ADR 0006)."""
    binding, coverage = progress["binding"], progress["coverage"]
    if observed_unprotected(progress):
        return Outcome(EXIT_UNPROTECTED, "version_binding_refused_position_unprotected", symbol=symbol,
                       reason=binding.error, coverage=coverage)
    return Outcome(EXIT_REFUSED, "version_binding_refused", symbol=symbol, reason=binding.error)


def alert_version_exception(outcome, run=subprocess.run) -> bool:
    """Email the incident; True only when scripts/email.sh verified delivery."""
    exc = outcome.detail["version_exception"]
    text = (f"VERSION BINDING INCIDENT: {outcome.detail.get('symbol')} protective stop restoration ran under "
            f"approved {exc['approved']} while the run was unbound ({exc['error']}). Result: {outcome.state} "
            f"(exit {outcome.code}). Fix STRATEGY_VERSION / the rulebook pin before the next routine.")
    try:
        return run(["bash", str(EMAIL), text], check=False, timeout=120).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _replace_stop(order_id, trail_percent, stop_price, progress, *, read=adapter, run=mutate, check=validate_mutation,
                  sleep=time.sleep, polls=20, now=None):
    now = now or datetime.now(timezone.utc)
    old = read("order-info", order_id)
    if not (isinstance(old, dict) and old.get("id") == order_id and old.get("side") == "sell"
            and old.get("type") in ("stop", "trailing_stop")):
        raise Outcome(EXIT_USAGE, "not_a_protective_stop", order_id=order_id)
    symbol = old["symbol"]
    held, coverage = live_coverage(read, symbol, now)
    progress["coverage"] = coverage
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
    binding = progress["binding"]
    if status in OPEN:
        if binding.error:
            raise version_refusal(progress, symbol)
        # 1. Preflight while the old stop still rests and protects.
        try:
            check("order", json.dumps({k: v for k, v in body.items() if k != "client_order_id"}))
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            if observed_unprotected(progress):
                raise Outcome(EXIT_UNPROTECTED, "refused_position_unprotected", symbol=symbol, reason=str(exc),
                              coverage=coverage)
            raise Outcome(EXIT_REFUSED, "refused", symbol=symbol, reason=str(exc))
        progress["cancel_sent"] = True
        cancel_ok, http, _, err = run("cancel", order_id)
        if not cancel_ok:
            # Unknown outcome: fall through to polling rather than assuming either way.
            print(f"cancel reported failure (HTTP {http}): {err}", file=sys.stderr)
    else:
        cancel_ok = True  # the broker already holds the cancel from an earlier run
        if status not in ("pending_cancel", "canceled"):
            if held is not None and observed_unprotected(progress):
                # e.g. the old stop expired: the position is held with nothing verified resting.
                raise Outcome(EXIT_UNPROTECTED, "old_stop_gone_position_unprotected", symbol=symbol,
                              status=status, coverage=coverage)
            raise Outcome(EXIT_USAGE, "old_stop_not_replaceable", symbol=symbol, status=status)
        if binding.error:
            # Restoration (ADR 0011): an earlier run's cancel left a held position without
            # verified coverage; place protection under the approved version, cancel nothing.
            if coverage is None or coverage["ok"]:
                raise version_refusal(progress, symbol)
            progress["version_exception"] = {**binding.as_dict(), "operation": "restore_after_confirmed_cancel"}
        progress["cancel_sent"] = True  # resuming an earlier run's cancel

    # 2. Confirm cancellation from broker state. A cancel the broker ACCEPTED may
    #    still complete after we stop looking, so an accepted cancel gets the full
    #    poll window and, if still open, is an incident (rerun resumes it) rather
    #    than "still protects". Only a broker-REFUSED cancel may be called rejected
    #    after a short look.
    for attempt in range(polls):
        old = read("order-info", order_id)
        status = old.get("status") if isinstance(old, dict) else None
        if status in ("canceled", "filled") or (status in OPEN and not cancel_ok and attempt >= 3):
            break
        sleep(1)
    if status == "filled":
        raise Outcome(EXIT_OK, "old_stop_filled", symbol=symbol)
    if status in OPEN and not cancel_ok:
        raise Outcome(EXIT_REFUSED, "cancel_rejected_old_stop_still_protects", symbol=symbol, status=status)
    if status in OPEN:
        raise Outcome(EXIT_UNPROTECTED, "cancel_accepted_but_unconfirmed_rerun", symbol=symbol, status=status,
                      polled_seconds=polls)
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
        alert = {"alert_delivered": alert_version_exception(outcome)} if "version_exception" in outcome.detail else {}
        print(json.dumps({"state": outcome.state, "exit": outcome.code, **outcome.detail, **alert}, default=str))
        return outcome.code
    raise AssertionError("replace_stop must end in an Outcome")


if __name__ == "__main__":
    raise SystemExit(main())
