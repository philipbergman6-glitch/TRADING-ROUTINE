"""Conservative coverage check over current broker snapshots, without I/O.

This reports coverage at observation time, not guaranteed execution prices or
continuous protection. Conditional/held/pending orders do not certify coverage.
"""
from datetime import datetime
from decimal import Decimal

from .models import to_money


def reconcile_protection(positions: list, orders: list, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(positions, list) or not isinstance(orders, list):
        raise ValueError("positions and orders must be arrays")
    issues = []
    if len(orders) >= 500:
        issues.append("order response may be truncated; coverage cannot be certified")
    flat = {}

    def visit(order):
        if not isinstance(order, dict):
            issues.append("malformed broker order")
            return
        if order.get("id"):
            old = flat.get(order["id"])
            if old is not None and old != order:
                issues.append(f"conflicting observations for order {order['id']}")
            flat[order["id"]] = order
        elif order.get("side") == "sell":
            issues.append("sell order without broker id")
        for child in order.get("legs") or []:
            visit(child)

    for order in orders:
        visit(order)
    rows = []
    seen_symbols = set()
    for position in positions:
        symbol = position["symbol"]
        qty = to_money(position["qty"], "position qty")
        if symbol in seen_symbols:
            issues.append(f"{symbol}: duplicate position")
        seen_symbols.add(symbol)
        covered = Decimal(0)
        covering = []
        if qty <= 0:
            issues.append(f"{symbol}: expected a positive long position")
        for order in flat.values():
            if order.get("symbol") != symbol or order.get("side") != "sell":
                continue
            if order.get("type") not in ("stop", "trailing_stop"):
                continue
            if order.get("status") != "new" or order.get("time_in_force") != "gtc":
                continue
            try:
                expiry = datetime.fromisoformat(str(order["expires_at"]).replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry <= now:
                    raise ValueError("expired or ambiguous expiry")
                level = to_money(order["stop_price"], "stop_price")
                remaining = to_money(order["qty"], "qty") - to_money(order["filled_qty"], "filled_qty")
                if level <= 0 or remaining <= 0:
                    raise ValueError("invalid stop price/remaining quantity")
            except (KeyError, ValueError, TypeError) as exc:
                issues.append(f"{symbol}: cannot verify protective order {order['id']}: {exc}")
                continue
            covered += remaining
            covering.append(order["id"])
        if covered != qty:
            issues.append(f"{symbol}: held {qty}, verified protective quantity {covered}")
        rows.append({"symbol": symbol, "held_qty": str(qty), "covered_qty": str(covered), "order_ids": covering})
    return {"ok": not issues, "observed_at": now.isoformat(), "issues": issues, "positions": rows}
