#!/usr/bin/env python3
"""Gate a stop or trail change against the risk engine (issue #32 / T2).

Two paths — both call existing engine functions (no broker I/O):

  Trail (midday tighten):
    python3 scripts/validate_stop_change.py --gain-pct 16 --print-required
    python3 scripts/validate_stop_change.py \\
        --gain-pct 16 --proposed-trail 7 --current-trail 10 \\
        --current-price 116 --json

  Fixed stop price:
    python3 scripts/validate_stop_change.py \\
        --current-stop 90 --new-stop 95 --current-price 110 --json

Trail path composition:
  1. required_trail_percent(gain) — ladder floor (widest still permitted)
  2. refuse if proposed > required (too wide) or proposed < MIN_STOP_DISTANCE
  3. refuse if proposed > current_trail (widening = effective stop down)
  4. validate_stop_change on implied stops at current_price
     (price * (1 - trail/100)) so Rule 7 price checks still run

Exit codes:
    0  approved (or --print-required succeeded)
    3  refused — one or more rules broken (reasons on stderr / --json)
    2  usage error

Nothing here submits or cancels an order. #40 PATCH remains OPEN; callers
still use TRAIL_TIGHTEN_STEPS = cancel then order after approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import (  # noqa: E402
    MIN_STOP_DISTANCE_PCT,
    Rule,
    ValidationResult,
    Violation,
    required_trail_percent,
    validate_stop_change,
)
from risk_engine.models import to_money  # noqa: E402

EXIT_REFUSED = 3
EXIT_USAGE = 2


def _implied_stop(price: Decimal, trail_percent: Decimal) -> Decimal:
    """Stop price implied by a trail % if the high-water mark is current price.

    Trailing resting prices move with the HWM; this is the tightest the trail
    can sit relative to *current* price, which is what Rule 7's 3% floor cares
    about for a proposed trail change.
    """
    return (price * (Decimal(100) - trail_percent) / Decimal(100)).quantize(
        Decimal("0.0001")
    )


def validate_trail_path(
    *,
    gain_pct: object,
    proposed_trail: object,
    current_trail: object | None,
    current_price: object,
) -> tuple[ValidationResult, Decimal, list[str]]:
    """Compose required_trail_percent + validate_stop_change for a trail change."""
    gain = to_money(gain_pct, "gain_pct")
    proposed = to_money(proposed_trail, "proposed_trail")
    price = to_money(current_price, "current_price")
    if price <= 0:
        raise ValueError(f"current_price must be positive, got {price}")
    if proposed <= 0:
        raise ValueError(f"proposed_trail must be positive, got {proposed}")

    engine_calls = ["required_trail_percent"]
    required = required_trail_percent(gain)
    violations: list[Violation] = []

    if proposed > required:
        violations.append(
            Violation(
                Rule.STOP_DISTANCE,
                f"trail {proposed}% is wider than required {required}% "
                f"at gain {gain}% (ladder floor)",
            )
        )
    if proposed < MIN_STOP_DISTANCE_PCT:
        violations.append(
            Violation(
                Rule.STOP_DISTANCE,
                f"trail of {proposed}% is inside the "
                f"{MIN_STOP_DISTANCE_PCT}% minimum distance",
            )
        )

    current: Decimal | None = None
    if current_trail is not None:
        current = to_money(current_trail, "current_trail")
        if current <= 0:
            raise ValueError(f"current_trail must be positive, got {current}")
        if proposed > current:
            violations.append(
                Violation(
                    Rule.STOP_NEVER_LOWERED,
                    f"trail may never widen (effective stop down): "
                    f"{current}% -> {proposed}%",
                )
            )

    # Price-level Rule 7 via implied stops at current mark. Missing current
    # trail → distance-check only (hold current_stop == new_stop) so
    # validate_stop_change still runs on this path.
    new_stop = _implied_stop(price, proposed)
    if current is None:
        old_stop = new_stop
    else:
        old_stop = _implied_stop(price, current)
    engine_calls.append("validate_stop_change")
    price_result = validate_stop_change(old_stop, new_stop, price)
    violations.extend(price_result.violations)

    return ValidationResult(tuple(violations)), required, engine_calls


def _emit(
    *,
    approved: bool,
    violations: tuple[Violation, ...],
    as_json: bool,
    extra: dict,
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "approved": approved,
                    "violations": [
                        {"rule": v.rule.value, "detail": v.detail} for v in violations
                    ],
                    **extra,
                },
                indent=2,
            )
        )
    elif approved:
        print("APPROVED  stop/trail change")
        if "required_trail_percent" in extra:
            print(f"  required_trail_percent: {extra['required_trail_percent']}")
    else:
        print("REFUSED   stop/trail change", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
    return 0 if approved else EXIT_REFUSED


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gain-pct",
        help="unrealized gain percent (e.g. 15 for +15%); trail path",
    )
    parser.add_argument("--proposed-trail", help="proposed trail_percent")
    parser.add_argument(
        "--current-trail",
        help="current trail_percent on the resting order (trail path)",
    )
    parser.add_argument("--current-stop", help="current stop price (price path)")
    parser.add_argument("--new-stop", help="proposed stop price (price path)")
    parser.add_argument(
        "--current-price",
        help="mark price; required for validate paths",
    )
    parser.add_argument(
        "--print-required",
        action="store_true",
        help="print required_trail_percent(gain) and exit 0 (no validation)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = parser.parse_args()

    trail_intent = any(
        [
            args.gain_pct is not None,
            args.proposed_trail is not None,
            args.current_trail is not None,
            args.print_required,
        ]
    )
    price_intent = args.current_stop is not None or args.new_stop is not None

    if trail_intent and price_intent:
        print(
            "usage: choose trail path (--gain-pct / --proposed-trail) OR "
            "price path (--current-stop / --new-stop), not both",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.print_required:
        if args.gain_pct is None:
            print("--print-required requires --gain-pct", file=sys.stderr)
            return EXIT_USAGE
        try:
            required = required_trail_percent(args.gain_pct)
        except (TypeError, ValueError) as exc:
            print(f"usage: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if args.json:
            print(
                json.dumps(
                    {
                        "gain_pct": str(to_money(args.gain_pct, "gain_pct")),
                        "required_trail_percent": str(required),
                        "engine_calls": ["required_trail_percent"],
                    },
                    indent=2,
                )
            )
        else:
            print(required)
        return 0

    if price_intent:
        if not all([args.current_stop, args.new_stop, args.current_price]):
            print(
                "price path requires --current-stop --new-stop --current-price",
                file=sys.stderr,
            )
            return EXIT_USAGE
        try:
            result = validate_stop_change(
                args.current_stop, args.new_stop, args.current_price
            )
        except (TypeError, ValueError) as exc:
            print(f"usage: {exc}", file=sys.stderr)
            return EXIT_USAGE
        return _emit(
            approved=result.approved,
            violations=result.violations,
            as_json=args.json,
            extra={
                "engine_calls": ["validate_stop_change"],
                "current_stop": str(to_money(args.current_stop, "current_stop")),
                "new_stop": str(to_money(args.new_stop, "new_stop")),
                "current_price": str(to_money(args.current_price, "current_price")),
            },
        )

    if args.gain_pct is None or args.proposed_trail is None or args.current_price is None:
        print(
            "trail path requires --gain-pct --proposed-trail --current-price "
            "(optional --current-trail); or use --print-required",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        result, required, engine_calls = validate_trail_path(
            gain_pct=args.gain_pct,
            proposed_trail=args.proposed_trail,
            current_trail=args.current_trail,
            current_price=args.current_price,
        )
    except (TypeError, ValueError) as exc:
        print(f"usage: {exc}", file=sys.stderr)
        return EXIT_USAGE

    return _emit(
        approved=result.approved,
        violations=result.violations,
        as_json=args.json,
        extra={
            "engine_calls": engine_calls,
            "required_trail_percent": str(required),
            "gain_pct": str(to_money(args.gain_pct, "gain_pct")),
            "proposed_trail": str(to_money(args.proposed_trail, "proposed_trail")),
            "current_trail": (
                str(to_money(args.current_trail, "current_trail"))
                if args.current_trail is not None
                else None
            ),
            "current_price": str(to_money(args.current_price, "current_price")),
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
