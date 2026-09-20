#!/usr/bin/env python3
"""Validate the exact adapter mutation immediately before transport.

No submission, tokens or flag-based approval here. The wrapper passes the same
body it sends to the broker. Account-wide bulk mutations are intentionally
unsupported. This closes payload/approval drift, not cross-process races or
cancel/replacement recovery; those require the execution coordinator.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import OrderProposal, Side, params_from_env, validate_order, validate_stop_change
from risk_engine.models import to_money
from scripts.validate_order import adapter, load_sectors, read_portfolio


def require(condition, message):
    if not condition:
        raise ValueError(message)


REPLACE_PREFIX = "rs-"   # replacement of a canceled stop: client_order_id = rs-<old broker id>
RESTORE_PREFIX = "rr-"   # re-placement of the canceled stop's exact level after a failed replacement
RECENT_CANCEL_WINDOW = timedelta(minutes=15)
_STOP_TYPES = ("stop", "trailing_stop")


def _check_stop_floor(body, symbol, level, price, read, now, params):
    """A new protective level may never sit below the stop it replaces.

    The replaced stop may already be canceled (cancel precedes replacement to
    release reserved shares), so its floor is read from the broker order named
    in client_order_id, and any same-symbol stop canceled in the last 15
    minutes also counts. Resting stops always count.
    """
    opens = read("orders", "open")
    require(isinstance(opens, list) and len(opens) < 500, "open-order snapshot incomplete")
    live = [o for o in opens if o.get("symbol") == symbol and o.get("side") == "sell"
            and (o.get("type") in _STOP_TYPES or o.get("stop_price") is not None)]
    cid = str(body.get("client_order_id", ""))
    if cid.startswith((REPLACE_PREFIX, RESTORE_PREFIX)):
        old_id = cid[len(REPLACE_PREFIX):]
        old = read("order-info", old_id)
        require(isinstance(old, dict) and old.get("id") == old_id and old.get("symbol") == symbol
                and old.get("side") == "sell" and old.get("type") in _STOP_TYPES,
                "client_order_id does not name this symbol's protective stop")
        require(old.get("status") == "canceled", "replaced stop must be confirmed canceled first")
        require(not live, "another protective stop is still resting; reconcile before replacing")
        floor = to_money(old.get("stop_price"), "replaced stop_price")
        if cid.startswith(RESTORE_PREFIX):
            # Restoring the exact prior level is not a stop change; the 3%
            # distance rule would otherwise leave the position naked.
            require(body.get("type") == "stop" and level == floor,
                    "restore must be a fixed stop at the canceled stop's exact level")
            return
        floors = [floor]
    else:
        start = (now - RECENT_CANCEL_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
        closed = read("orders", "closed", start)
        require(isinstance(closed, list) and len(closed) < 500, "recent closed-order snapshot incomplete")
        recent = [o for o in closed if o.get("symbol") == symbol and o.get("side") == "sell"
                  and o.get("type") in _STOP_TYPES and o.get("status") == "canceled"]
        floors = [o.get("stop_price") for o in live + recent]
        require(all(f is not None for f in floors), "protective stop without stop_price; cannot verify floor")
    for floor in floors:
        result = validate_stop_change(floor, level, price, params)
        require(result.approved, "; ".join(result.reasons()))


def validate_mutation(command, argument, *, read=adapter, portfolio=None, now=None, params=None):
    """Raise on unsafe/unsupported input; injectable reads keep tests offline."""
    params = params or params_from_env(os.environ)
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
    state = portfolio if portfolio is not None else read_portfolio(now or datetime.now(timezone.utc), None, params)
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
                                     price=price, stop_price=stop["stop_price"],
                                     sector=load_sectors().get(symbol))
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
                require(params.min_stop_distance_pct <= trail <= params.base_trail_pct,
                        f"protective trail must be {params.min_stop_distance_pct}–{params.base_trail_pct}%")
                level = price * (1 - trail / 100)
            else:
                require(not (set(body) & {"stop_price", "trail_percent"}), "market sell has stop fields")
                level = None
            if level is not None:
                _check_stop_floor(body, symbol, level, price, read, now or datetime.now(timezone.utc), params)
    result = validate_order(proposal, state, params)
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
