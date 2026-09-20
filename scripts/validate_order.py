#!/usr/bin/env python3
"""Gate a proposed order against the risk engine, using live broker state.

This is the enforceable boundary. `scripts/alpaca.sh` sits *behind* it as a
private broker adapter; the engine decides, the adapter executes.

When DATABASE_URL is set, every verdict — approved or refused — is written to
the Postgres ledger via `ledger.live_path.persist_decision` (T4); a failed write
→ exit 6 (fail closed). When DATABASE_URL is unset the ledger is disabled: a
LEDGER DISABLED warning goes to stderr, `ledger_order_id` is null, and the
verdict stands. This does not bind validate→submit (#19); it only records.

    python3 scripts/validate_order.py --symbol AAPL --qty 100 --side buy \
        --price 187.85 --trail-percent 10

Exit codes:
    0  approved -- safe to submit (ledger_order_id printed with --json)
    3  refused  -- one or more rules broken (reasons on stderr; still ledgered)
    2  usage error
    4  could not establish broker state (never assume; refuse to guess)
    6  ledger configured but record failed (fail closed)

Nothing here submits an order. Validation and execution stay separate so this
can be run freely, including as a dry run — but dry-run still records.
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

from ledger.live_path import (  # noqa: E402
    DEFAULT_STRATEGY_VERSION,
    EXIT_LEDGER,
    LEDGER_DISABLED_WARNING,
    ledger_enabled,
    open_live_ledger,
    persist_decision,
)
from risk_engine import (  # noqa: E402
    OrderProposal,
    PortfolioState,
    Position,
    Side,
    StrategyParams,
    V1,
    max_affordable_shares,
    params_from_env,
    validate_order,
)

ADAPTER = Path(__file__).resolve().parent / "alpaca.sh"
SECTORS_FILE = Path(__file__).resolve().parent.parent / "memory" / "SECTORS.json"
EXIT_REFUSED = 3
EXIT_NO_STATE = 4


def load_sectors(path: Path = SECTORS_FILE) -> dict[str, str]:
    """Symbol -> GICS sector, recorded by the routine before entry (memory/SECTORS.json)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return {k.upper(): str(v) for k, v in data.items() if not k.startswith("_")}


def cooldown_from_fills(now: datetime, params: StrategyParams) -> frozenset[str]:
    """v2 rule 14 input: names that exited within the version's cooldown window.

    Read from broker fills (scripts/blotter.py), never from the trade log.
    Under a version with no cooldown this makes no broker call.
    """
    if params.reentry_cooldown_sessions <= 0:
        return frozenset()
    from risk_engine.blotter import cooldown_symbols  # noqa: E402  (local: keeps import cheap)
    from scripts.blotter import blotter_from_broker  # noqa: E402

    window_start = (now - timedelta(days=params.reentry_cooldown_sessions * 2 + 14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        blotter = blotter_from_broker(after=window_start)
    except (ValueError, TypeError, KeyError) as exc:
        print(f"cooldown state unavailable: {exc}", file=sys.stderr)
        sys.exit(EXIT_NO_STATE)
    return cooldown_symbols(blotter, now.date(), params.reentry_cooldown_sessions)


def adapter(*args: str) -> object:
    """Call the broker adapter and parse its JSON.

    Any failure is fatal: validating against a guess at the portfolio is worse
    than not validating at all, because it looks like it worked.
    """
    read_env = os.environ.copy()
    # Nested preflight GETs must never overwrite the outer mutation's status.
    read_env.pop("ALPACA_HTTP_STATUS_FILE", None)
    try:
        proc = subprocess.run(
            ["bash", str(ADAPTER), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            env=read_env,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"broker adapter failed ({' '.join(args)}): "
            f"exit {exc.returncode}", file=sys.stderr,
        )
        sys.exit(EXIT_NO_STATE)
    except subprocess.TimeoutExpired:
        print(f"broker adapter timed out ({' '.join(args)})", file=sys.stderr)
        sys.exit(EXIT_NO_STATE)
    try:
        return json.loads(proc.stdout, parse_float=str)
    except json.JSONDecodeError as exc:
        print(f"broker adapter returned non-JSON ({' '.join(args)}): {exc}", file=sys.stderr)
        sys.exit(EXIT_NO_STATE)


def trades_this_week(now: datetime) -> int:
    """Count filled buys since Monday 00:00 UTC.

    Derived from the broker rather than the markdown trade log: the broker is
    the authority on what actually executed, and the log can drift.
    """
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Alpaca's `after` filters on submission time. Start a week earlier so a
    # buy submitted before Monday but filled after it is still counted; the
    # filled_at filter below does the real windowing. Unbounded history would
    # eventually hit the 500-row page cap and refuse every buy forever.
    window_start = (monday - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders = adapter("orders", "closed", window_start)
    if not isinstance(orders, list) or len(orders) >= 500:
        sys.exit(EXIT_NO_STATE)
    count = 0
    for order in orders:
        if order.get("side") != "buy" or not order.get("filled_at"):
            continue
        filled = datetime.fromisoformat(order["filled_at"].replace("Z", "+00:00"))
        if filled >= monday:
            count += 1
    return count


def read_portfolio(
    now: datetime, override_trades: int | None, params: StrategyParams = V1
) -> PortfolioState:
    account = adapter("account")
    if not isinstance(account, dict) or "equity" not in account:
        sys.exit(EXIT_NO_STATE)

    raw_positions = adapter("positions")
    if not isinstance(raw_positions, list):
        sys.exit(EXIT_NO_STATE)
    sectors = load_sectors()

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
                sector=sectors.get(str(p["symbol"]).upper()),
            )
            for p in raw_positions
        ),
        trades_this_week=(
            override_trades if override_trades is not None else trades_this_week(now)
        ),
        cooldown_symbols=cooldown_from_fills(now, params),
    )


def _is_paper() -> bool:
    """Alpaca's account payload does not label paper vs live; the endpoint is
    the only signal. Default matches alpaca.sh, which defaults to paper and
    hard-fails on anything else; live overrides are not supported."""
    endpoint = os.environ.get("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets/v2")
    return endpoint == "https://paper-api.alpaca.markets/v2"


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
    parser.add_argument(
        "--idempotency-key",
        help="ledger idempotency key (default: generated live-* UUID; durable "
        "keys are a #19 concern, not invented here)",
    )
    parser.add_argument(
        "--strategy-version",
        default=None,
        help="provenance string recorded on the ledger order (default: the active "
        f"STRATEGY_VERSION name, else {DEFAULT_STRATEGY_VERSION})",
    )
    parser.add_argument(
        "--sector",
        default=None,
        help="GICS sector of the symbol (default: memory/SECTORS.json); required by versions with a sector cap",
    )
    parser.add_argument(
        "--research-ref",
        default=None,
        help="optional research log pointer recorded with the decision",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    params = params_from_env(os.environ)
    state = read_portfolio(now, args.trades_this_week, params)
    proposal = OrderProposal(
        symbol=args.symbol,
        qty=Decimal(args.qty),
        side=Side(args.side),
        price=Decimal(args.price),
        stop_price=Decimal(args.stop_price) if args.stop_price else None,
        trail_percent=Decimal(args.trail_percent) if args.trail_percent else None,
        sector=args.sector or load_sectors().get(args.symbol.upper()),
    )
    result = validate_order(proposal, state, params)
    version_label = args.strategy_version or (
        params.name if os.environ.get("STRATEGY_VERSION") else DEFAULT_STRATEGY_VERSION
    )

    recorded = None
    if ledger_enabled():
        try:
            ledger = open_live_ledger()
            recorded = persist_decision(
                ledger,
                proposal,
                result,
                idempotency_key=args.idempotency_key,
                strategy_version=version_label,
                research_ref=args.research_ref,
            )
        except Exception as exc:  # noqa: BLE001 — configured ledger: fail closed
            print(f"LEDGER FAIL: {exc}", file=sys.stderr)
            return EXIT_LEDGER
    else:
        print(LEDGER_DISABLED_WARNING, file=sys.stderr)
    ledger_ref = str(recorded.id) if recorded else "disabled"

    if args.json:
        print(
            json.dumps(
                {
                    "approved": result.approved,
                    "strategy_version": params.name,
                    "symbol": proposal.symbol,
                    "qty": str(proposal.qty),
                    "notional": str(proposal.notional),
                    "ledger_enabled": recorded is not None,
                    "ledger_order_id": str(recorded.id) if recorded else None,
                    "idempotency_key": recorded.idempotency_key if recorded else None,
                    "ledger_status": recorded.status if recorded else None,
                    "violations": [
                        {"rule": v.rule.value, "detail": v.detail}
                        for v in result.violations
                    ],
                },
                indent=2,
            )
        )
    elif result.approved:
        print(
            f"APPROVED  {proposal.side.value} {proposal.qty} {proposal.symbol} "
            f"@ {proposal.price} (notional {proposal.notional}) "
            f"ledger_order_id={ledger_ref}"
        )
    else:
        print(
            f"REFUSED   {proposal.side.value} {proposal.qty} {proposal.symbol} "
            f"ledger_order_id={ledger_ref}",
            file=sys.stderr,
        )
        for reason in result.reasons():
            print(f"  - {reason}", file=sys.stderr)
        if proposal.side is Side.BUY:
            allowed = max_affordable_shares(state, args.price, proposal.symbol, params)
            print(f"  max shares permitted right now: {allowed}", file=sys.stderr)

    return 0 if result.approved else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
