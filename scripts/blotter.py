#!/usr/bin/env python3
"""Rebuild the trade blotter from broker fills (read-only).

    python3 scripts/blotter.py --json            # round trips + open lots
    python3 scripts/blotter.py --markdown        # table for the trade log / reviews
    python3 scripts/blotter.py --cooldown        # symbols inside the active version's re-entry cooldown
    python3 scripts/blotter.py --check           # open lots must equal broker positions (exit 4 otherwise)

Fills are the record; markdown is the narrative. Sector per symbol comes from
memory/SECTORS.json (rule 10 needs it; a missing sector is an error with
--sector-streaks, never a guess). Engineering test fills are excluded with
--exclude-symbol, and that exclusion is printed so it cannot be silent.

Exit codes: 0 ok · 2 usage · 4 broker state unavailable or reconciliation failed
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.blotter import (  # noqa: E402
    Blotter, build_blotter, cooldown_symbols, parse_fills, sector_failure_streaks,
)
from risk_engine import params_from_env  # noqa: E402
from scripts.validate_order import EXIT_NO_STATE, adapter  # noqa: E402

SECTORS_FILE = Path(__file__).resolve().parent.parent / "memory" / "SECTORS.json"
MAX_PAGES = 200


def fetch_fills(read=adapter, after: str | None = None) -> list[dict]:
    """Page through /account/activities/FILL until a short page."""
    rows: list[dict] = []
    token = None
    for _ in range(MAX_PAGES):
        args = ["activities", after or ""]
        if token:
            args.append(token)
        page = read(*args)
        if not isinstance(page, list):
            raise ValueError("activities response is not a list")
        rows.extend(page)
        if len(page) < 100:
            return rows
        token = str(page[-1]["id"])
    raise ValueError(f"more than {MAX_PAGES} activity pages; refusing an unbounded read")


def load_sectors(path: Path = SECTORS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return {k.upper(): str(v) for k, v in data.items() if not k.startswith("_")}


def blotter_from_broker(read=adapter, exclude: frozenset[str] = frozenset(), after=None) -> Blotter:
    return build_blotter(parse_fills(fetch_fills(read, after)), exclude)


def to_json(blotter: Blotter) -> dict:
    return {
        "round_trips": [
            {"symbol": t.symbol, "entered": t.entered.isoformat(), "exited": t.exited.isoformat(),
             "qty": str(t.qty), "avg_in": str(t.avg_in), "avg_out": str(t.avg_out),
             "pnl": str(t.pnl), "pnl_pct": str(t.pnl_pct),
             "entry_order_ids": list(t.entry_order_ids), "exit_order_ids": list(t.exit_order_ids)}
            for t in blotter.round_trips
        ],
        "open_lots": [
            {"symbol": o.symbol, "entered": o.entered.isoformat(), "qty": str(o.qty),
             "avg_in": str(o.avg_in), "entry_order_ids": list(o.entry_order_ids)}
            for o in blotter.open_lots
        ],
    }


def to_markdown(blotter: Blotter) -> str:
    lines = ["| Sym | In | Out | Qty | Avg in | Avg out | P&L $ | P&L % |", "|---|---|---|---|---|---|---|---|"]
    for t in blotter.round_trips:
        lines.append(f"| {t.symbol} | {t.entered:%m-%d} | {t.exited:%m-%d} | {t.qty} | {t.avg_in:.2f} | "
                     f"{t.avg_out:.2f} | {t.pnl:+,.2f} | {t.pnl_pct:+.2f} |")
    if blotter.open_lots:
        lines += ["", "| Open | In | Qty | Avg in |", "|---|---|---|---|"]
        for o in blotter.open_lots:
            lines.append(f"| {o.symbol} | {o.entered:%m-%d} | {o.qty} | {o.avg_in:.2f} |")
    return "\n".join(lines)


def check_positions(blotter: Blotter, positions: list) -> list[str]:
    """Open lots from fills must equal the broker's positions, quantity for quantity."""
    issues = []
    held = {p["symbol"]: Decimal(str(p["qty"])) for p in positions}
    opens = blotter.open_qty()
    for symbol in sorted(set(held) | set(opens)):
        if held.get(symbol, Decimal(0)) != opens.get(symbol, Decimal(0)):
            issues.append(f"{symbol}: broker holds {held.get(symbol, 0)}, fills imply {opens.get(symbol, 0)}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--markdown", action="store_true")
    mode.add_argument("--cooldown", action="store_true", help="print symbols in re-entry cooldown, one per line")
    mode.add_argument("--sector-streaks", action="store_true", help="consecutive closed losers per sector (rule 10)")
    mode.add_argument("--check", action="store_true", help="reconcile open lots against broker positions")
    parser.add_argument("--exclude-symbol", action="append", default=[], help="engineering test symbol to exclude")
    parser.add_argument("--after", help="only fills after this UTC time (YYYY-MM-DDTHH:MM:SSZ)")
    args = parser.parse_args()
    exclude = frozenset(s.upper() for s in args.exclude_symbol)
    try:
        blotter = blotter_from_broker(exclude=exclude, after=args.after)
        if exclude:
            print(f"excluded symbols: {', '.join(sorted(exclude))}", file=sys.stderr)
        if args.json:
            print(json.dumps(to_json(blotter), indent=2))
        elif args.markdown:
            print(to_markdown(blotter))
        elif args.cooldown:
            params = params_from_env(os.environ)
            today = datetime.now(timezone.utc).date()
            for symbol in sorted(cooldown_symbols(blotter, today, params.reentry_cooldown_sessions)):
                print(symbol)
        elif args.sector_streaks:
            print(json.dumps(sector_failure_streaks(blotter, load_sectors()), indent=2, sort_keys=True))
        else:
            issues = check_positions(blotter, adapter("positions"))
            print(json.dumps({"ok": not issues, "issues": issues, "open_lots": to_json(blotter)["open_lots"]}, indent=2))
            if issues:
                return EXIT_NO_STATE
    except (ValueError, TypeError, KeyError) as exc:
        print(f"blotter: {exc}", file=sys.stderr)
        return EXIT_NO_STATE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
