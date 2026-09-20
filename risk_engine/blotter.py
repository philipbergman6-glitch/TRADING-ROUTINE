"""Trade blotter rebuilt from broker fills, without I/O.

Research 0006 reconciled the paper account by pairing fills FIFO; this module
is that computation as code so rules 10 (sector failures) and 14 (re-entry
cooldown) are computed from what actually executed, never from markdown.
Fills are the Alpaca `/account/activities/FILL` rows; the script that fetches
them is `scripts/blotter.py`.

Money is Decimal; fills missing a field the blotter depends on are an error,
not a skipped row, because a silently dropped fill mis-states a position.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping

from .models import to_money

__all__ = [
    "Fill",
    "RoundTrip",
    "OpenLot",
    "Blotter",
    "parse_fills",
    "build_blotter",
    "cooldown_symbols",
    "sector_failure_streaks",
    "sessions_between",
]

_REQUIRED = ("id", "transaction_time", "symbol", "side", "qty", "price", "order_id")


@dataclass(frozen=True)
class Fill:
    id: str
    at: datetime
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    order_id: str


@dataclass(frozen=True)
class RoundTrip:
    symbol: str
    entered: datetime
    exited: datetime
    qty: Decimal
    avg_in: Decimal
    avg_out: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    entry_order_ids: tuple[str, ...]
    exit_order_ids: tuple[str, ...]

    @property
    def won(self) -> bool:
        return self.pnl > 0


@dataclass(frozen=True)
class OpenLot:
    symbol: str
    entered: datetime
    qty: Decimal
    avg_in: Decimal
    entry_order_ids: tuple[str, ...]


@dataclass(frozen=True)
class Blotter:
    round_trips: tuple[RoundTrip, ...]
    open_lots: tuple[OpenLot, ...]

    def open_qty(self) -> dict[str, Decimal]:
        return {lot.symbol: lot.qty for lot in self.open_lots}


def parse_fills(rows: Iterable[Mapping[str, Any]]) -> list[Fill]:
    """Activity rows -> Fills sorted by time. Non-FILL rows are rejected."""
    fills: list[Fill] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("fill row must be an object")
        if row.get("activity_type") not in (None, "FILL"):
            raise ValueError(f"not a FILL activity: {row.get('activity_type')!r}")
        missing = [k for k in _REQUIRED if row.get(k) in (None, "")]
        if missing:
            raise ValueError(f"fill {row.get('id')!r} missing {missing}")
        side = str(row["side"]).lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"fill {row['id']}: unsupported side {side!r}")
        at = datetime.fromisoformat(str(row["transaction_time"]).replace("Z", "+00:00"))
        if at.tzinfo is None:
            raise ValueError(f"fill {row['id']}: naive timestamp")
        qty = to_money(str(row["qty"]), "fill qty")
        price = to_money(str(row["price"]), "fill price")
        if qty <= 0 or price <= 0:
            raise ValueError(f"fill {row['id']}: qty and price must be positive")
        fills.append(Fill(str(row["id"]), at, str(row["symbol"]).upper(), side, qty, price,
                          str(row["order_id"])))
    fills.sort(key=lambda f: (f.at, f.id))
    return fills


def build_blotter(fills: Iterable[Fill], exclude_symbols: frozenset[str] = frozenset()) -> Blotter:
    """Pair sells against buys FIFO per symbol. A sell with no open lot is an error."""
    # Per symbol: list of [remaining_qty, price, entered, order_id]
    lots: dict[str, list[list[Any]]] = {}
    # Per symbol: accumulating round trip: entries consumed by current sells
    trips: list[RoundTrip] = []
    pending: dict[str, dict[str, Any]] = {}

    def flush(symbol: str) -> None:
        acc = pending.pop(symbol, None)
        if acc is None:
            return
        qty = acc["qty"]
        avg_in = (acc["cost"] / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        avg_out = (acc["proceeds"] / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        pnl = (acc["proceeds"] - acc["cost"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pnl_pct = (pnl / acc["cost"] * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        trips.append(RoundTrip(symbol, acc["entered"], acc["exited"], qty, avg_in, avg_out, pnl,
                               pnl_pct, tuple(dict.fromkeys(acc["entry_ids"])),
                               tuple(dict.fromkeys(acc["exit_ids"]))))

    for fill in fills:
        if fill.symbol in exclude_symbols:
            continue
        book = lots.setdefault(fill.symbol, [])
        if fill.side == "buy":
            # A buy after sells closes the previous round trip (position went
            # flat or is being rebuilt); a buy on top of open lots just adds.
            if fill.symbol in pending and not book:
                flush(fill.symbol)
            book.append([fill.qty, fill.price, fill.at, fill.order_id])
            continue
        remaining = fill.qty
        acc = pending.setdefault(fill.symbol, {"qty": Decimal(0), "cost": Decimal(0),
                                               "proceeds": Decimal(0), "entered": None,
                                               "exited": None, "entry_ids": [], "exit_ids": []})
        while remaining > 0:
            if not book:
                raise ValueError(f"{fill.symbol}: sell {fill.id} of {remaining} exceeds open lots")
            lot = book[0]
            take = min(lot[0], remaining)
            acc["qty"] += take
            acc["cost"] += take * lot[1]
            acc["proceeds"] += take * fill.price
            acc["entered"] = lot[2] if acc["entered"] is None else min(acc["entered"], lot[2])
            acc["exited"] = fill.at
            acc["entry_ids"].append(lot[3])
            acc["exit_ids"].append(fill.order_id)
            lot[0] -= take
            remaining -= take
            if lot[0] == 0:
                book.pop(0)
        if not book:
            flush(fill.symbol)

    opens: list[OpenLot] = []
    for symbol, book in lots.items():
        if not book:
            continue
        qty = sum((lot[0] for lot in book), Decimal(0))
        cost = sum((lot[0] * lot[1] for lot in book), Decimal(0))
        opens.append(OpenLot(symbol, min(lot[2] for lot in book), qty,
                             (cost / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                             tuple(dict.fromkeys(lot[3] for lot in book))))
    # Partially closed positions keep their pending accumulator; report the
    # closed part as a trip so realized P&L is not hidden.
    for symbol in list(pending):
        flush(symbol)
    trips.sort(key=lambda t: (t.exited, t.symbol))
    opens.sort(key=lambda o: (o.entered, o.symbol))
    return Blotter(tuple(trips), tuple(opens))


def sessions_between(start: date, end: date) -> int:
    """Weekday count in (start, end]. Holidays are not subtracted, which makes a
    cooldown expire no earlier than the true session count would."""
    if end < start:
        raise ValueError("end must not precede start")
    count, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count += 1
    return count


def cooldown_symbols(blotter: Blotter, today: date, sessions: int) -> frozenset[str]:
    """Rule 14: names whose latest exit is within `sessions` weekdays of today."""
    if sessions <= 0:
        return frozenset()
    latest: dict[str, date] = {}
    for trip in blotter.round_trips:
        day = trip.exited.date()
        if trip.symbol not in latest or day > latest[trip.symbol]:
            latest[trip.symbol] = day
    # An exit dated after `today` (clock skew) is inside the window, not an error.
    return frozenset(s for s, d in latest.items() if d > today or sessions_between(d, today) < sessions)


def sector_failure_streaks(blotter: Blotter, sectors: Mapping[str, str]) -> dict[str, int]:
    """Rule 10 input: consecutive closed losers per sector, latest-first.

    A symbol without a sector mapping is an error: the rule cannot be computed
    with a gap, and skipping would hide exactly the failure it exists to catch.
    """
    streak: dict[str, int] = {}
    for trip in sorted(blotter.round_trips, key=lambda t: t.exited):
        sector = sectors.get(trip.symbol)
        if sector is None:
            raise ValueError(f"no sector recorded for {trip.symbol}")
        streak[sector] = 0 if trip.won else streak.get(sector, 0) + 1
    return streak
