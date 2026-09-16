#!/usr/bin/env python3
"""Validate the exact adapter mutation immediately before transport.

No submission, tokens or flag-based approval here. The wrapper passes the same
body it sends to the broker. Account-wide bulk mutations are intentionally
unsupported. This closes payload/approval drift, not cross-process races or
cancel/replacement recovery; those require the execution coordinator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import OrderProposal, Side, validate_order, validate_stop_change
from risk_engine.models import to_money
from scripts.validate_order import adapter, read_portfolio


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_mutation(command, argument, *, read=adapter, portfolio=None, now=None):
    """Raise on unsafe/unsupported input; injectable reads keep tests offline."""
    require(command in ("order", "close", "cancel"), "bulk mutations are disabled")
    if command == "order":
        body = json.loads(argument, parse_float=str)
        require(isinstance(body, dict), "order body must be an object")
        allowed = {"symbol", "qty", "side", "type", "time_in_force", "order_class",
                   "stop_loss", "stop_price", "trail_percent", "client_order_id"}
        require(not set(body) - allowed, "unsupported order fields")
        symbol = body.get("symbol", "")
    elif command == "cancel":
        require(re.fullmatch(r"[A-Za-z0-9-]+", argument) is not None, "invalid order id")
        body = read("order-info", argument)
        require(isinstance(body, dict) and body.get("id") == argument, "order identity mismatch")
        require(body.get("status") in ("new", "accepted", "held", "pending_new", "partially_filled"),
                "order is not cancelable; reconcile broker state")
        symbol = body.get("symbol", "")
    else:
        body = {}
        symbol = argument
    require(isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?", symbol),
            "invalid equity symbol")
    asset = read("asset", symbol)
    require(isinstance(asset, dict) and asset.get("symbol") == symbol
            and asset.get("class") == "us_equity", "broker asset must be a US equity")

    # Fetching account data through read_portfolio is deliberately not optional
    # on the CLI. Tests inject the snapshot to avoid network access.
    state = portfolio if portfolio is not None else read_portfolio(now or datetime.now(timezone.utc), None)
    require(state.is_paper, "paper account required")
    if command == "cancel":
        if body.get("side") == "sell":
            require(state.position_for(symbol) is not None, "cancel target has no held position")
        return

    if command == "close":
        held = state.position_for(symbol)
        require(held is not None and held.qty > 0, "no long position to close")
        proposal = OrderProposal(symbol=symbol, qty=held.qty, side="sell",
                                 price=held.market_value / held.qty)
    else:
        require(body.get("time_in_force") == "gtc", "execution requires GTC protection/orders")
        side = Side(body.get("side"))
        if side is Side.BUY:
            require(asset.get("tradable") is True and asset.get("status") == "active",
                    "asset is not active and tradable")
            require(body.get("type") == "market" and body.get("order_class") == "oto",
                    "buy must be a market OTO with a fixed protective leg")
            stop = body.get("stop_loss")
            require(isinstance(stop, dict) and set(stop) == {"stop_price"}, "fixed stop_loss required")
            require(not (set(body) & {"stop_price", "trail_percent"}), "ambiguous protection fields")
            opens = read("orders", "open")
            require(isinstance(opens, list) and len(opens) < 500, "open-order snapshot incomplete")
            require(not any(o.get("side") == "buy" for o in opens),
                    "pending buy exists; wait for reconciliation before adding risk")
            payload = read("quote", symbol)
            quote = payload.get("quote", {}) if isinstance(payload, dict) else {}
            stamped = datetime.fromisoformat(str(quote.get("t", "")).replace("Z", "+00:00"))
            require(stamped.tzinfo is not None and 0 <= ((now or datetime.now(timezone.utc)) - stamped).total_seconds() <= 60,
                    "quote must be no more than 60 seconds old")
            price = to_money(quote.get("ap"), "ask")
            proposal = OrderProposal(symbol=symbol, qty=body.get("qty"), side=side,
                                     price=price, stop_price=stop["stop_price"])
        else:
            require(body.get("order_class", "simple") == "simple", "unsupported sell order class")
            require(body.get("type") in ("market", "stop", "trailing_stop"), "unsupported sell type")
            require("stop_loss" not in body, "sell must not contain stop_loss")
            held = state.position_for(symbol)
            require(held is not None and held.qty > 0, "no long position to protect/sell")
            price = held.market_value / held.qty
            proposal = OrderProposal(symbol=symbol, qty=body.get("qty"), side=side, price=price)
            if body["type"] == "stop":
                require("trail_percent" not in body, "ambiguous stop fields")
                level = to_money(body.get("stop_price"), "stop_price")
                require(0 < level < price, "fixed stop must be positive and below market")
            elif body["type"] == "trailing_stop":
                require("stop_price" not in body, "ambiguous stop fields")
                trail = to_money(body.get("trail_percent"), "trail_percent")
                require(Decimal("3") <= trail <= Decimal("10"), "protective trail must be 3–10%")
                level = price * (1 - trail / 100)
            else:
                require(not (set(body) & {"stop_price", "trail_percent"}), "market sell has stop fields")
                level = None
            if level is not None:
                opens = read("orders", "open")
                require(isinstance(opens, list) and len(opens) < 500, "open-order snapshot incomplete")
                for order in opens:
                    if order.get("symbol") == symbol and order.get("side") == "sell" and order.get("stop_price"):
                        result = validate_stop_change(order["stop_price"], level, price)
                        require(result.approved, "; ".join(result.reasons()))
    result = validate_order(proposal, state)
    require(result.approved, "; ".join(result.reasons()))


def main():
    if len(sys.argv) != 3:
        print("usage: validate_mutation.py order|close|cancel ARG", file=sys.stderr)
        return 2
    try:
        validate_mutation(sys.argv[1], sys.argv[2])
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        print(f"REFUSED mutation: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
