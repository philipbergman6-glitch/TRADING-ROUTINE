#!/usr/bin/env python3
"""Persist a broker response against a ledger order (T4 live path).

Call after a successful (or refused) mutating alpaca submit/stop. Uses the
existing Ledger API via ledger.live_path — does not invent cancel writers,
does not bind validate→submit (#19).

    python3 scripts/record_broker_response.py \
        --order-id LEDGER_UUID --kind submit --broker-order-id BRK \
        --http-status 200 --response "$ALPACA_JSON"

    python3 scripts/record_broker_response.py \
        --order-id LEDGER_UUID --kind stop --http-status 200 \
        --response "$ALPACA_JSON"

Exit codes:
    0  recorded
    2  usage error
    6  ledger unavailable / record failed (fail closed)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger.live_path import (  # noqa: E402
    EXIT_LEDGER,
    open_live_ledger,
    persist_broker_response,
)

EXIT_USAGE = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True, help="ledger orders.id UUID")
    parser.add_argument(
        "--kind",
        required=True,
        choices=("submit", "stop"),
        help="Ledger broker_responses.kind (submit|stop only)",
    )
    parser.add_argument(
        "--http-status",
        required=True,
        type=int,
        help="HTTP status from the broker (required; never guessed)",
    )
    parser.add_argument(
        "--broker-order-id",
        help="required for kind=submit; Alpaca order id",
    )
    parser.add_argument(
        "--response",
        required=True,
        help="verbatim broker JSON body (string)",
    )
    args = parser.parse_args()

    try:
        order_id = uuid.UUID(args.order_id)
    except ValueError:
        print(f"usage: --order-id must be a UUID, got {args.order_id!r}", file=sys.stderr)
        return EXIT_USAGE

    try:
        payload = json.loads(args.response)
    except json.JSONDecodeError as exc:
        print(f"usage: --response must be JSON: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not isinstance(payload, dict):
        print("usage: --response JSON must be an object", file=sys.stderr)
        return EXIT_USAGE

    broker_order_id = args.broker_order_id
    if args.kind == "submit" and not broker_order_id:
        # Common convenience: take id from the Alpaca payload when present.
        maybe = payload.get("id")
        if isinstance(maybe, str) and maybe:
            broker_order_id = maybe
        else:
            print(
                "usage: --broker-order-id required for kind=submit "
                "(or response.id must be a string)",
                file=sys.stderr,
            )
            return EXIT_USAGE

    try:
        ledger = open_live_ledger()
        persist_broker_response(
            ledger,
            order_id,
            kind=args.kind,
            response=payload,
            http_status=args.http_status,
            broker_order_id=broker_order_id,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed
        print(f"LEDGER FAIL: {exc}", file=sys.stderr)
        return EXIT_LEDGER

    print(
        json.dumps(
            {
                "recorded": True,
                "order_id": str(order_id),
                "kind": args.kind,
                "http_status": args.http_status,
                "broker_order_id": broker_order_id,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
