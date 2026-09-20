"""Protection monitor planning, without I/O.

Given the broker's positions and open orders, decide what protection work is
due under the active strategy version: renew expiring stops, convert leftover
fixed OTO legs to the trailing stop (v1 immediately, v2 once the position is
up `trail_convert_gain_pct`), tighten trails per the ladder, and report
standing conditions the rulebook says to leave alone. Every action is a
`replace_stop` call; nothing here invents a cancel/place pair.

The monitor exists so protection does not depend on a Claude session or the
ledger (spec section 6). This module is pure so its decisions are provable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from .engine import required_trail_percent, validate_stop_change
from .models import to_money
from .protection import RENEWAL_WINDOW_DAYS, expiring_protective_stops, is_leftover_fixed_stop
from .reconciliation import reconcile_protection
from .versions import V1, StrategyParams

__all__ = ["Action", "Plan", "plan_protection"]

_OPEN = ("new", "accepted", "held", "pending_new", "partially_filled")


@dataclass(frozen=True)
class Action:
    kind: str  # renew | convert | tighten
    symbol: str
    order_id: str
    trail_percent: Decimal | None = None
    stop_price: Decimal | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "symbol": self.symbol, "order_id": self.order_id,
                "trail_percent": None if self.trail_percent is None else str(self.trail_percent),
                "stop_price": None if self.stop_price is None else str(self.stop_price),
                "reason": self.reason}


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    standing: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def issues(self) -> list[str]:
        return list(self.coverage.get("issues", []))

    def as_dict(self) -> dict[str, Any]:
        return {"actions": [a.as_dict() for a in self.actions], "holds": self.holds,
                "standing": self.standing, "coverage": self.coverage}


def _position_fields(position: Mapping[str, Any]) -> tuple[str, Decimal, Decimal, Decimal]:
    missing = [k for k in ("symbol", "qty", "avg_entry_price", "current_price") if position.get(k) in (None, "")]
    if missing:
        raise ValueError(f"position {position.get('symbol')!r} missing {missing}")
    price = to_money(str(position["current_price"]), "current_price")
    entry = to_money(str(position["avg_entry_price"]), "avg_entry_price")
    if price <= 0 or entry <= 0:
        raise ValueError(f"{position['symbol']}: prices must be positive")
    gain = ((price - entry) / entry * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(position["symbol"]).upper(), price, entry, gain


def plan_protection(
    positions: list, orders: list, now: datetime, params: StrategyParams = V1,
    renewal_window_days: int = RENEWAL_WINDOW_DAYS,
) -> Plan:
    plan = Plan(coverage=reconcile_protection(positions, orders, now))
    renewing = {d["order_id"] for d in expiring_protective_stops(orders, now, renewal_window_days)}
    for due in expiring_protective_stops(orders, now, renewal_window_days):
        plan.actions.append(Action("renew", due["symbol"], due["order_id"],
                                   stop_price=to_money(due["renew_stop_price"], "renew_stop_price"),
                                   reason=f"GTC expires {due['expires_at']}"))

    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        if order.get("side") == "sell" and order.get("type") in ("stop", "trailing_stop") \
                and order.get("status") in _OPEN:
            by_symbol.setdefault(str(order.get("symbol", "")).upper(), []).append(order)

    for position in positions:
        symbol, price, entry, gain = _position_fields(position)
        for order in by_symbol.get(symbol, []):
            oid = str(order["id"])
            if oid in renewing:
                continue  # renewal first; conversion/tightening is re-planned next run
            stop = to_money(str(order.get("stop_price")), "stop_price") if order.get("stop_price") else None
            if stop is None:
                plan.holds.append(f"{symbol}: order {oid} has no stop_price; cannot evaluate")
                continue
            distance = (price - stop) / price * 100
            if is_leftover_fixed_stop(order):
                if distance < params.min_stop_distance_pct:
                    plan.standing.append(
                        f"{symbol}: fixed stop {stop} is {distance:.2f}% below {price}, inside the "
                        f"{params.min_stop_distance_pct}% minimum; rule 7 says leave it")
                if params.trail_convert_gain_pct is not None and gain < params.trail_convert_gain_pct:
                    plan.holds.append(
                        f"{symbol}: fixed stop held; gain {gain}% below {params.name} conversion "
                        f"threshold {params.trail_convert_gain_pct}%")
                    continue
                new_stop = price * (1 - params.base_trail_pct / 100)
                verdict = validate_stop_change(stop, new_stop, price, params)
                if verdict.approved:
                    plan.actions.append(Action("convert", symbol, oid, trail_percent=params.base_trail_pct,
                                               reason=f"fixed {stop} -> {params.base_trail_pct}% trail at {price}"))
                else:
                    plan.holds.append(f"{symbol}: HOLD fixed {stop}: " + "; ".join(verdict.reasons()))
                continue
            if order.get("type") != "trailing_stop":
                continue
            current_trail = to_money(str(order.get("trail_percent")), "trail_percent") \
                if order.get("trail_percent") else None
            if current_trail is None:
                plan.holds.append(f"{symbol}: trailing order {oid} has no trail_percent")
                continue
            required = required_trail_percent(gain, params)
            if current_trail <= required:
                continue
            new_stop = price * (1 - required / 100)
            verdict = validate_stop_change(stop, new_stop, price, params)
            if verdict.approved:
                plan.actions.append(Action("tighten", symbol, oid, trail_percent=required,
                                           reason=f"gain {gain}% requires {required}% (was {current_trail}%)"))
            else:
                plan.holds.append(f"{symbol}: tighten to {required}% refused: " + "; ".join(verdict.reasons()))
    return plan
