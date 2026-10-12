"""Rebuild daily equity from broker activities and closes (pure; no I/O).

Equity on a session close is cash plus every held lot priced at that session's
close. Cash is the sum of every cash-moving activity: a FILL moves -qty*price
(buy) or +qty*price (sell); a non-trade activity moves `net_amount`. Holdings
are the signed sum of fill quantities. Research 0006 reconciled this to the
cent by hand; `scripts/reconcile_equity.py` repeats it every day.

Alpaca's 1D portfolio history stamps each point at 00:00 UTC on the day *after*
the session it describes (the 2026-09-19T00:00Z point holds the 2026-09-18
close), so `session_equity` shifts every point back one day.

Activity types that move only quantity (JNLS, splits, reorganisations) or that
this module has not seen are rejected rather than ignored: an unknown row is
an unexplained difference waiting to happen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .blotter import Fill, parse_fills
from .models import to_money

EASTERN = ZoneInfo("America/New_York")

# Non-trade activity types whose `net_amount` is a cash movement.
CASH_ACTIVITY_TYPES = frozenset({
    "JNLC", "FEE", "CFEE", "INT", "INTNRA", "CSD", "CSW", "PTC", "PTR",
    "DIV", "DIVCGL", "DIVCGS", "DIVFEE", "DIVNRA", "DIVROC", "DIVTXEX",
})


@dataclass(frozen=True)
class CashFlow:
    id: str
    kind: str
    on: date
    amount: Decimal


@dataclass(frozen=True)
class DayRow:
    session: date
    cash: Decimal
    holdings: dict[str, Decimal]
    market_value: Decimal
    rebuilt: Decimal
    broker: Decimal
    diff: Decimal
    status: str  # "ok" | "explained: <reason>" | "UNEXPLAINED"


def session_of(at: datetime) -> date:
    """The trading session a fill belongs to: its Eastern-time calendar date."""
    if at.tzinfo is None:
        raise ValueError("naive timestamp")
    return at.astimezone(EASTERN).date()


def parse_activities(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Fill], list[CashFlow]]:
    """Split raw activity rows into fills and cash flows. Anything else is an error."""
    fill_rows: list[Mapping[str, Any]] = []
    flows: list[CashFlow] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("activity row must be an object")
        kind = row.get("activity_type")
        if kind == "FILL":
            fill_rows.append(row)
            continue
        if kind not in CASH_ACTIVITY_TYPES:
            raise ValueError(f"activity {row.get('id')!r}: unsupported activity type {kind!r}; "
                             "add it to CASH_ACTIVITY_TYPES only if it moves cash")
        missing = [k for k in ("id", "date", "net_amount") if row.get(k) in (None, "")]
        if missing:
            raise ValueError(f"activity {row.get('id')!r} missing {missing}")
        flows.append(CashFlow(str(row["id"]), str(kind), date.fromisoformat(str(row["date"])),
                              to_money(row["net_amount"], f"{kind} net_amount")))
    flows.sort(key=lambda c: (c.on, c.id))
    return parse_fills(fill_rows), flows


def fill_cash(fill: Fill) -> Decimal:
    return fill.qty * fill.price * (-1 if fill.side == "buy" else 1)


def cash_after(fills: Iterable[Fill], flows: Iterable[CashFlow]) -> Decimal:
    return sum((fill_cash(f) for f in fills), Decimal(0)) + sum((c.amount for c in flows), Decimal(0))


def holdings_after(fills: Iterable[Fill]) -> dict[str, Decimal]:
    held: dict[str, Decimal] = {}
    for f in fills:
        held[f.symbol] = held.get(f.symbol, Decimal(0)) + (f.qty if f.side == "buy" else -f.qty)
    return {s: q for s, q in held.items() if q != 0}


def session_equity(timestamps: Iterable[int], equity: Iterable[Any]) -> dict[date, Decimal]:
    """Portfolio-history arrays -> {session: equity}. Zero points (pre-funding) are dropped."""
    ts, eq = list(timestamps), list(equity)
    if len(ts) != len(eq):
        raise ValueError(f"portfolio history length mismatch: {len(ts)} timestamps, {len(eq)} equity")
    out: dict[date, Decimal] = {}
    for t, e in zip(ts, eq):
        if isinstance(e, float):
            e = str(e)  # broker JSON floats are decoded as str at the boundary; be lenient here
        value = to_money(e, "portfolio history equity")
        if value == 0:
            continue
        stamped = datetime.fromtimestamp(int(t), timezone.utc).date()
        out[stamped - timedelta(days=1)] = value
    return out


def rebuild_days(fills: list[Fill], flows: list[CashFlow], closes: Mapping[tuple[str, date], Decimal],
                 broker: Mapping[date, Decimal], tolerance: Decimal,
                 exceptions: Mapping[date, tuple[str, Decimal]]) -> list[DayRow]:
    """One row per broker session from the first cash flow on.

    A difference within `tolerance` is ok. Beyond it, the session must appear in
    `exceptions` with a recorded diff within `tolerance` of the one observed;
    otherwise it is UNEXPLAINED. A held symbol with no close is an error.
    """
    if not flows:
        raise ValueError("no cash flows: the account has never been funded, nothing to reconcile")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    events: list[tuple[date, int, Any]] = [(c.on, 0, c) for c in flows] + [(session_of(f.at), 1, f) for f in fills]
    events.sort(key=lambda e: (e[0], e[1]))
    first = flows[0].on
    cash = Decimal(0)
    held: dict[str, Decimal] = {}
    rows: list[DayRow] = []
    i = 0
    for session in sorted(d for d in broker if d >= first):
        while i < len(events) and events[i][0] <= session:
            _, _, item = events[i]
            if isinstance(item, Fill):
                cash += fill_cash(item)
                held[item.symbol] = held.get(item.symbol, Decimal(0)) + (item.qty if item.side == "buy" else -item.qty)
            else:
                cash += item.amount
            i += 1
        holdings = {s: q for s, q in held.items() if q != 0}
        market_value = Decimal(0)
        for symbol, qty in sorted(holdings.items()):
            close = closes.get((symbol, session))
            if close is None:
                raise ValueError(f"no close for {symbol} on {session.isoformat()}; cannot price {qty} held shares")
            market_value += qty * close
        rebuilt = cash + market_value
        diff = rebuilt - broker[session]
        if abs(diff) <= tolerance:
            status = "ok"
        elif session in exceptions and abs(diff - exceptions[session][1]) <= tolerance:
            status = f"explained: {exceptions[session][0]}"
        else:
            status = "UNEXPLAINED"
        rows.append(DayRow(session, cash, holdings, market_value, rebuilt, broker[session], diff, status))
    return rows


def unexplained(rows: Iterable[DayRow]) -> list[str]:
    return [f"{r.session.isoformat()}: rebuilt {r.rebuilt:.2f} vs broker {r.broker:.2f} (diff {r.diff:.2f})"
            for r in rows if r.status == "UNEXPLAINED"]
