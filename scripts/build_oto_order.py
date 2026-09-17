#!/usr/bin/env python3
"""Emit Alpaca order JSON for ADR 0002 OTO entry or trailing conversion.

Paper-only seam helper — does not submit. Callers still must:
  1. python3 scripts/validate_order.py ... (exit 0)
  2. ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$(python3 scripts/build_oto_order.py ...)"

Examples:
  python3 scripts/build_oto_order.py oto --symbol F --qty 10 --price 12.50
  python3 scripts/build_oto_order.py oto --symbol F --qty 10 --stop-price 11.25
  python3 scripts/build_oto_order.py trail --symbol F --qty 10 --trail-percent 10
  python3 scripts/build_oto_order.py stop --symbol F --qty 10 --stop-price 11.25
  bash scripts/alpaca.sh orders | python3 scripts/build_oto_order.py expiring
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import (  # noqa: E402
    BASE_TRAIL_PCT,
    FixedStop,
    TrailingStop,
    RENEWAL_WINDOW_DAYS,
    build_fixed_stop,
    build_oto_entry,
    build_trailing_stop,
    expiring_protective_stops,
    fixed_stop_at_distance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    oto = sub.add_parser("oto", help="market buy + fixed stop_loss (order_class=oto)")
    oto.add_argument("--symbol", required=True)
    oto.add_argument("--qty", required=True)
    oto.add_argument("--price", help="entry price; used to derive stop at --distance-pct")
    oto.add_argument("--stop-price", help="explicit fixed stop_price (skips derivation)")
    oto.add_argument(
        "--distance-pct",
        default=str(BASE_TRAIL_PCT),
        help=f"percent below entry for derived stop (default {BASE_TRAIL_PCT})",
    )
    oto.add_argument("--tif", default="gtc", choices=("day", "gtc"))

    trail = sub.add_parser("trail", help="standalone trailing_stop sell")
    trail.add_argument("--symbol", required=True)
    trail.add_argument("--qty", required=True)
    trail.add_argument("--trail-percent", default=str(BASE_TRAIL_PCT))
    trail.add_argument("--tif", default="gtc", choices=("day", "gtc"))

    stop = sub.add_parser("stop", help="standalone fixed stop sell (expiry renewal)")
    stop.add_argument("--symbol", required=True)
    stop.add_argument("--qty", required=True)
    stop.add_argument("--stop-price", required=True)
    stop.add_argument("--tif", default="gtc", choices=("day", "gtc"))

    expiring = sub.add_parser(
        "expiring",
        help="read open orders JSON on stdin; print protective stops due for renewal",
    )
    expiring.add_argument("--window-days", type=int, default=RENEWAL_WINDOW_DAYS)

    args = parser.parse_args()

    if args.cmd == "expiring":
        orders = json.load(sys.stdin)
        if not isinstance(orders, list):
            parser.error("stdin must be the JSON array from `alpaca.sh orders`")
        due = expiring_protective_stops(
            orders, datetime.now(timezone.utc), args.window_days
        )
        print(json.dumps(due, indent=2))
        return 0

    if args.cmd == "stop":
        body = build_fixed_stop(
            symbol=args.symbol,
            qty=args.qty,
            protection=FixedStop(stop_price=Decimal(args.stop_price)),
            time_in_force=args.tif,
        )
    elif args.cmd == "oto":
        if args.stop_price:
            protection = FixedStop(stop_price=Decimal(args.stop_price))
        elif args.price:
            protection = fixed_stop_at_distance(args.price, args.distance_pct)
        else:
            parser.error("oto requires --stop-price or --price")
        body = build_oto_entry(
            symbol=args.symbol,
            qty=args.qty,
            protection=protection,
            time_in_force=args.tif,
        )
    else:
        body = build_trailing_stop(
            symbol=args.symbol,
            qty=args.qty,
            protection=TrailingStop(trail_percent=Decimal(args.trail_percent)),
            time_in_force=args.tif,
        )

    print(json.dumps(body, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
