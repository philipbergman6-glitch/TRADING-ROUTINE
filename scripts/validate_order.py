#!/usr/bin/env python3
"""Gate a proposed order against the risk engine, using live broker state.

This is the enforceable boundary. `scripts/alpaca.sh` sits *behind* it as a
private broker adapter; the engine decides, the adapter executes.

    python3 scripts/validate_order.py --symbol AAPL --qty 100 --side buy \
        --price 187.85 --trail-percent 10

Exit codes:
    0  approved -- safe to submit
    3  refused  -- one or more rules broken (reasons on stderr)
    2  usage error
    4  could not establish broker state (never assume; refuse to guess)

Nothing here submits an order. Validation and execution stay separate so this
can be run freely, including as a dry run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import (  # noqa: E402
    OrderProposal,
    PortfolioState,
    Position,
    Side,
    max_affordable_shares,
    validate_order,
)

ADAPTER = Path(__file__).resolve().parent / "alpaca.sh"
EXIT_REFUSED = 3
EXIT_NO_STATE = 4


def adapter(*args: str) -> object:
    """Call the broker adapter and parse its JSON.

    Any failure is fatal: validating against a guess at the portfolio is worse
    than not validating at all, because it looks like it worked.
    """
    try:
        proc = subprocess.run(
            ["bash", str(ADAPTER), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(
            f"broker adapter failed ({' '.join(args)}): "
            f"exit {exc.returncode}: {exc.stderr.strip()}"
        )
    except subprocess.TimeoutExpired:
        sys.exit(f"broker adapter timed out ({' '.join(args)})")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        sys.exit(f"broker adapter returned non-JSON ({' '.join(args)}): {exc}")


def trades_this_week(now: datetime) -> int:
    """Count filled buys since Monday 00:00 UTC.

    Derived from the broker rather than the markdown trade log: the broker is
    the authority on what actually executed, and the log can drift.
    """
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    orders = adapter("orders", "closed")
    if not isinstance(orders, list):
        sys.exit(EXIT_NO_STATE)
    count = 0
    for order in orders:
        if order.get("side") != "buy" or not order.get("filled_at"):
            continue
        filled = datetime.fromisoformat(order["filled_at"].replace("Z", "+00:00"))
        if filled >= monday:
            count += 1
    return count


def read_portfolio(now: datetime, override_trades: int | None) -> PortfolioState:
    account = adapter("account")
    if not isinstance(account, dict) or "equity" not in account:
        sys.exit(EXIT_NO_STATE)

    raw_positions = adapter("positions")
    if not isinstance(raw_positions, list):
        sys.exit(EXIT_NO_STATE)

    # The adapter refuses non-paper endpoints outright (see alpaca.sh), but the
    # engine re-checks rather than trusting that upstream guard held.
    return PortfolioState(
        equity=str(account["equity"]),
        # Rule 13 is cash-only: this must stay "cash" and never become
        # "buying_power", which is ~4x equity on a margin account. Missing key
        # falls back to 0, which fails closed (every buy refused).
        cash=str(account.get("cash", "0")),
        is_paper=_is_paper(),
        positions=tuple(
            Position(
                symbol=p["symbol"],
                qty=str(p["qty"]),
                market_value=str(p["market_value"]),
            )
            for p in raw_positions
        ),
        trades_this_week=(
            override_trades if override_trades is not None else trades_this_week(now)
        ),
    )


def _is_paper() -> bool:
    """Alpaca's account payload does not label paper vs live; the endpoint is
    the only signal. Default matches alpaca.sh, which defaults to paper and
    hard-fails on anything else unless ALPACA_ALLOW_LIVE=1."""
    endpoint = os.environ.get("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets/v2")
    return "paper-api.alpaca.markets" in endpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--qty", required=True)
    parser.add_argument("--side", required=True, choices=[s.value for s in Side])
    parser.add_argument("--price", required=True, help="entry price, as a string")
    parser.add_argument("--stop-price")
    parser.add_argument("--trail-percent")
    parser.add_argument(
        "--trades-this-week",
        type=int,
        help="override the broker-derived count (for testing)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    state = read_portfolio(now, args.trades_this_week)
    proposal = OrderProposal(
        symbol=args.symbol,
        qty=Decimal(args.qty),
        side=Side(args.side),
        price=Decimal(args.price),
        stop_price=Decimal(args.stop_price) if args.stop_price else None,
        trail_percent=Decimal(args.trail_percent) if args.trail_percent else None,
    )
    result = validate_order(proposal, state)

    if args.json:
        print(
            json.dumps(
                {
                    "approved": result.approved,
                    "symbol": proposal.symbol,
                    "qty": str(proposal.qty),
                    "notional": str(proposal.notional),
                    "violations": [
                        {"rule": v.rule.value, "detail": v.detail}
                        for v in result.violations
                    ],
                },
                indent=2,
            )
        )
    elif result.approved:
        print(f"APPROVED  {proposal.side.value} {proposal.qty} {proposal.symbol} "
              f"@ {proposal.price} (notional {proposal.notional})")
    else:
        print(f"REFUSED   {proposal.side.value} {proposal.qty} {proposal.symbol}", file=sys.stderr)
        for reason in result.reasons():
            print(f"  - {reason}", file=sys.stderr)
        if proposal.side is Side.BUY:
            allowed = max_affordable_shares(state, args.price, proposal.symbol)
            print(f"  max shares permitted right now: {allowed}", file=sys.stderr)

    return 0 if result.approved else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
