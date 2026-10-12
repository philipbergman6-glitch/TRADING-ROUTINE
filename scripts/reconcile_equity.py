#!/usr/bin/env python3
"""Reconcile broker equity against a rebuild from activities (read-only).

    python3 scripts/reconcile_equity.py            # verdict + every non-ok day; exit 4 if unexplained
    python3 scripts/reconcile_equity.py --all      # every session
    python3 scripts/reconcile_equity.py --json

What reconciles to what:

* cash today:     sum of every cash-moving activity  ==  /account cash, to the cent
* holdings today: signed sum of fill quantities      ==  /positions, share for share
* each past session: cash + held lots x SIP close    ==  portfolio-history equity,
                     within --tolerance (default $1, fractional-cent price rounding)

A past-session difference beyond tolerance is UNEXPLAINED unless
memory/RECONCILIATION-EXCEPTIONS.json records that date with the same diff and
a reason (broker snapshot artefacts; see docs/adr/0006). Today's session is
checked through cash and holdings only: SIP closes are not available until the
session is over. Research 0006 is the hand-made original of this check.

Exit codes: 0 reconciled · 2 usage · 4 unexplained difference or broker state unavailable
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.accounting import (  # noqa: E402
    EASTERN, DayRow, cash_after, holdings_after, parse_activities, rebuild_days, session_equity,
    session_of, unexplained,
)
from risk_engine.models import to_money  # noqa: E402
from scripts.validate_order import EXIT_NO_STATE, adapter  # noqa: E402

EXIT_USAGE = 2
EXCEPTIONS_FILE = Path(__file__).resolve().parent.parent / "memory" / "RECONCILIATION-EXCEPTIONS.json"
DEFAULT_TOLERANCE = Decimal("1.00")
MAX_PAGES = 200


def today_eastern() -> date:
    return datetime.now(EASTERN).date()


def fetch_activities(read=adapter) -> list[dict]:
    rows: list[dict] = []
    token = None
    for _ in range(MAX_PAGES):
        args = ["activities-all", ""] + ([token] if token else [])
        page = read(*args)
        if not isinstance(page, list):
            raise ValueError("activities-all response is not a list")
        rows.extend(page)
        if len(page) < 100:
            return rows
        token = str(page[-1]["id"])
    raise ValueError(f"more than {MAX_PAGES} activity pages; refusing an unbounded read")


def fetch_closes(read, symbols: list[str], start: date, end: date) -> dict[tuple[str, date], Decimal]:
    closes: dict[tuple[str, date], Decimal] = {}
    if not symbols:
        return closes
    token = None
    for _ in range(MAX_PAGES):
        args = ["bars", ",".join(sorted(symbols)), start.isoformat(), end.isoformat()] + ([token] if token else [])
        page = read(*args)
        if not isinstance(page, dict) or not isinstance(page.get("bars"), dict):
            raise ValueError("bars response has no 'bars' object")
        for symbol, bars in page["bars"].items():
            for bar in bars:
                closes[(symbol, date.fromisoformat(str(bar["t"])[:10]))] = to_money(bar["c"], f"{symbol} close")
        token = page.get("next_page_token")
        if not token:
            return closes
    raise ValueError(f"more than {MAX_PAGES} bar pages; refusing an unbounded read")


def load_exceptions(path: Path = EXCEPTIONS_FILE) -> dict[date, tuple[str, Decimal]]:
    """{session: (reason, recorded diff)}; a missing file means no exceptions."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(), parse_float=str)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object keyed by session date")
    out: dict[date, tuple[str, Decimal]] = {}
    for key, entry in data.items():
        if key.startswith("_"):
            continue
        if not isinstance(entry, dict) or not entry.get("reason") or entry.get("diff") in (None, ""):
            raise ValueError(f"{path}: {key} needs a 'reason' and the recorded 'diff'")
        out[date.fromisoformat(key)] = (str(entry["reason"]), to_money(entry["diff"], f"{key} diff"))
    return out


def reconcile(read=adapter, *, today: date, tolerance: Decimal, exceptions: dict[date, tuple[str, Decimal]],
              period: str = "1A") -> dict:
    fills, flows = parse_activities(fetch_activities(read))
    history = read("portfolio-history", period)
    broker = session_equity(history["timestamp"], history["equity"])
    if not flows:
        raise ValueError("no cash flows: the account has never been funded, nothing to reconcile")
    if broker and min(broker) > flows[0].on:
        raise ValueError(f"portfolio history ({period}) does not reach back to the first cash flow {flows[0].on}; "
                         "pass a longer --period")
    past = {d: e for d, e in broker.items() if d < today}
    closes: dict[tuple[str, date], Decimal] = {}
    if fills and past:
        closes = fetch_closes(read, sorted({f.symbol for f in fills}), session_of(fills[0].at), max(past))
    days = rebuild_days(fills, flows, closes, past, tolerance, exceptions)
    problems = unexplained(days)

    account = read("account")
    broker_cash = to_money(account["cash"], "account cash")
    rebuilt_cash = cash_after(fills, flows)
    cash_ok = rebuilt_cash == broker_cash
    if not cash_ok:
        problems.append(f"cash: rebuilt {rebuilt_cash} vs broker {broker_cash} (diff {rebuilt_cash - broker_cash})")

    held = {p["symbol"]: to_money(p["qty"], "position qty") for p in read("positions")}
    implied = holdings_after(fills)
    holdings_issues = []
    for symbol in sorted(set(held) | set(implied)):
        if held.get(symbol, Decimal(0)) != implied.get(symbol, Decimal(0)):
            holdings_issues.append(f"holdings {symbol}: fills imply {implied.get(symbol, 0)}, broker holds {held.get(symbol, 0)}")
    problems.extend(holdings_issues)

    return {
        "ok": not problems,
        "today": today.isoformat(),
        "tolerance": str(tolerance),
        "cash": {"rebuilt": str(rebuilt_cash), "broker": str(broker_cash), "ok": cash_ok},
        "holdings": {"ok": not holdings_issues, "issues": holdings_issues,
                     "implied": {s: str(q) for s, q in sorted(implied.items())}},
        "flows": {kind: str(sum(c.amount for c in flows if c.kind == kind))
                  for kind in sorted({c.kind for c in flows})},
        "days": [_day_json(r) for r in days],
        "skipped_sessions": [d.isoformat() for d in sorted(broker) if d >= today],
        "unexplained": problems,
    }


def _day_json(r: DayRow) -> dict:
    return {"session": r.session.isoformat(), "cash": f"{r.cash:.2f}", "market_value": f"{r.market_value:.2f}",
            "rebuilt": f"{r.rebuilt:.2f}", "broker": f"{r.broker:.2f}", "diff": f"{r.diff:.2f}", "status": r.status}


def render(report: dict, show_all: bool = False) -> str:
    lines = ["RECONCILED" if report["ok"] else "NOT RECONCILED", ""]
    cash = report["cash"]
    lines.append(f"cash {cash['rebuilt']} {'=' if cash['ok'] else '!='} broker {cash['broker']}")
    lines.append("holdings " + ("match broker positions" if report["holdings"]["ok"] else "; ".join(report["holdings"]["issues"])))
    lines.append("flows " + ", ".join(f"{k} {v}" for k, v in report["flows"].items()))
    days = report["days"]
    ok_days = sum(1 for d in days if d["status"] == "ok")
    lines.append(f"sessions {len(days)} checked, {ok_days} within tolerance {report['tolerance']}"
                 + (f", today {report['today']} via cash/holdings only" if report["skipped_sessions"] else ""))
    if days:
        last = days[-1]
        lines.append(f"last session {last['session']}: rebuilt {last['rebuilt']} vs broker {last['broker']} "
                     f"(diff {last['diff']}, {last['status']})")
    shown = days if show_all else [d for d in days if d["status"] != "ok"]
    if shown:
        lines += ["", "| session | cash | market value | rebuilt | broker | diff | status |", "|---|---|---|---|---|---|---|"]
        for d in shown:
            lines.append(f"| {d['session']} | {d['cash']} | {d['market_value']} | {d['rebuilt']} | {d['broker']} | {d['diff']} | {d['status']} |")
    if report["unexplained"]:
        lines += ["", "UNEXPLAINED:"] + [f"  {p}" for p in report["unexplained"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all", action="store_true", help="print every session, not only the non-ok ones")
    parser.add_argument("--tolerance", default=str(DEFAULT_TOLERANCE), help="per-session equity tolerance in dollars")
    parser.add_argument("--period", default="1A", help="portfolio-history window, e.g. 3M or 1A")
    parser.add_argument("--exceptions", type=Path, default=None, help=f"explained-difference file (default {EXCEPTIONS_FILE.name})")
    args = parser.parse_args(argv)
    try:
        tolerance = Decimal(args.tolerance)
        if not tolerance.is_finite() or tolerance < 0:
            raise InvalidOperation
    except InvalidOperation:
        print("reconcile_equity: --tolerance must be a non-negative dollar amount", file=sys.stderr)
        return EXIT_USAGE
    try:
        exceptions = load_exceptions(args.exceptions or EXCEPTIONS_FILE)
        report = reconcile(adapter, today=today_eastern(), tolerance=tolerance, exceptions=exceptions, period=args.period)
    except (ValueError, TypeError, KeyError) as exc:
        print(f"reconcile_equity: {exc}", file=sys.stderr)
        return EXIT_NO_STATE
    print(json.dumps(report, indent=2) if args.json else render(report, args.all))
    return 0 if report["ok"] else EXIT_NO_STATE


if __name__ == "__main__":
    raise SystemExit(main())
