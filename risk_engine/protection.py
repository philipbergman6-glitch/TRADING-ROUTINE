"""Buy protection payloads and ordered exit sequences (T3 / ADR 0002).

Alpaca offers atomicity *or* a trailing protective leg, not both
(docs/research/0001). ADR 0002 therefore submits every buy as an `oto` with a
**fixed** `stop_price` leg, then converts to a standalone trailing stop after
a complete fill.

This module is pure (no I/O): it makes the silent-downgrade request
unrepresentable, and it encodes cancel-then-act order so routines cannot
invert the sequence that left losers unprotected (#38).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal, Mapping

from .engine import BASE_TRAIL_PCT
from .models import to_money

__all__ = [
    "FixedStop",
    "TrailingStop",
    "Protection",
    "fixed_stop_at_distance",
    "build_oto_entry",
    "build_trailing_stop",
    "assert_leg_matches_fixed",
    "CUT_LOSER_STEPS",
    "TRAIL_TIGHTEN_STEPS",
    "CONVERT_FIXED_TO_TRAIL_STEPS",
]


@dataclass(frozen=True)
class FixedStop:
    """Protective leg for an OTO entry. Trail fields are intentionally absent."""

    stop_price: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stop_price", to_money(self.stop_price, "FixedStop.stop_price")
        )
        if self.stop_price <= 0:
            raise ValueError(f"FixedStop.stop_price must be positive, got {self.stop_price}")

    def stop_loss_body(self) -> dict[str, str]:
        """Alpaca `stop_loss` object — `stop_price` only (ADR 0002 silent-downgrade guard)."""
        return {"stop_price": _money_str(self.stop_price)}


@dataclass(frozen=True)
class TrailingStop:
    """Standalone trailing protective sell (never an OTO leg)."""

    trail_percent: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trail_percent",
            to_money(self.trail_percent, "TrailingStop.trail_percent"),
        )
        if self.trail_percent <= 0:
            raise ValueError(
                f"TrailingStop.trail_percent must be positive, got {self.trail_percent}"
            )


Protection = FixedStop | TrailingStop


def fixed_stop_at_distance(
    entry_price: object, distance_pct: object = BASE_TRAIL_PCT
) -> FixedStop:
    """Rule-4 distance fixed stop: entry * (1 - distance_pct/100)."""
    entry = to_money(entry_price, "entry_price")
    distance = to_money(distance_pct, "distance_pct")
    if entry <= 0:
        raise ValueError(f"entry_price must be positive, got {entry}")
    if distance <= 0 or distance >= 100:
        raise ValueError(f"distance_pct must be in (0, 100), got {distance}")
    stop = (entry * (Decimal(1) - distance / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return FixedStop(stop_price=stop)


def build_oto_entry(
    *,
    symbol: str,
    qty: object,
    protection: FixedStop,
    time_in_force: Literal["day", "gtc"] = "day",
) -> dict[str, Any]:
    """One POST body: market buy + fixed protective leg (`order_class=oto`).

    Rejects TrailingStop — Alpaca hard-rejects trailing OTO legs, and sending
    both stop_price and trail_percent silently drops the trail (0001).
    """
    if not isinstance(protection, FixedStop):
        raise TypeError(
            "OTO entry requires FixedStop; trailing cannot be an OTO leg "
            "(ADR 0002 / research 0001)"
        )
    qty_dec = to_money(qty, "qty")
    if qty_dec <= 0:
        raise ValueError(f"qty must be positive, got {qty_dec}")
    if qty_dec != qty_dec.to_integral_value():
        raise ValueError(f"OTO requires whole shares, got {qty_dec}")
    sym = _clean_symbol(symbol)
    body = {
        "symbol": sym,
        "qty": str(int(qty_dec)),
        "side": "buy",
        "type": "market",
        "time_in_force": time_in_force,
        "order_class": "oto",
        "stop_loss": protection.stop_loss_body(),
    }
    # Defence in depth: never allow a trail key onto the wire payload.
    assert "trail_percent" not in body["stop_loss"]
    assert "trail_price" not in body["stop_loss"]
    return body


def build_trailing_stop(
    *,
    symbol: str,
    qty: object,
    protection: TrailingStop,
    time_in_force: Literal["day", "gtc"] = "gtc",
) -> dict[str, Any]:
    """Standalone GTC trailing stop — the post-fill conversion target."""
    if not isinstance(protection, TrailingStop):
        raise TypeError("build_trailing_stop requires TrailingStop")
    qty_dec = to_money(qty, "qty")
    if qty_dec <= 0:
        raise ValueError(f"qty must be positive, got {qty_dec}")
    if qty_dec != qty_dec.to_integral_value():
        raise ValueError(f"qty must be whole shares, got {qty_dec}")
    return {
        "symbol": _clean_symbol(symbol),
        "qty": str(int(qty_dec)),
        "side": "sell",
        "type": "trailing_stop",
        "time_in_force": time_in_force,
        "trail_percent": _money_str(protection.trail_percent),
    }


def assert_leg_matches_fixed(leg: Mapping[str, Any], expected: FixedStop) -> None:
    """Post-submit readback: leg must be a fixed stop with no trail fields set.

    ADR 0002 detection half of the silent-downgrade guard.
    """
    leg_type = str(leg.get("type", "")).lower()
    if leg_type != "stop":
        raise AssertionError(
            f"OTO leg type must be 'stop' (fixed), got {leg.get('type')!r}"
        )
    raw_stop = leg.get("stop_price")
    if raw_stop is None:
        raise AssertionError("OTO leg missing stop_price")
    got = to_money(raw_stop, "leg.stop_price")
    if got != expected.stop_price:
        raise AssertionError(
            f"OTO leg stop_price {got} != expected {expected.stop_price}"
        )
    for trail_key in ("trail_percent", "trail_price"):
        val = leg.get(trail_key)
        if val is not None and str(val).strip() not in ("", "null", "None"):
            raise AssertionError(
                f"OTO leg has {trail_key}={val!r}; silent downgrade / wrong leg"
            )


# Ordered broker acts. Routines must follow these exactly — #38 was close-then-
# cancel, which 403s the close and strips protection. Trail tighten still has a
# naked window between cancel and place; collapsing it needs PATCH (#40 OPEN).
CUT_LOSER_STEPS: tuple[str, ...] = ("cancel", "close")
TRAIL_TIGHTEN_STEPS: tuple[str, ...] = ("cancel", "order")
CONVERT_FIXED_TO_TRAIL_STEPS: tuple[str, ...] = ("cancel", "order")


def _money_str(value: Decimal) -> str:
    # Alpaca accepts plain decimal strings; strip trailing zeros for trail %.
    normalized = value.normalize() if value == value.to_integral_value() else value
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _clean_symbol(symbol: object) -> str:
    if not isinstance(symbol, str):
        raise TypeError(f"symbol must be a string, got {type(symbol).__name__}")
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise ValueError("symbol must not be empty")
    return cleaned
