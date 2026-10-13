"""The validation layer.

Every rule here is mechanised from memory/TRADING-STRATEGY.md. The module is
pure: no network, no database, no clock. That is deliberate -- it means the
rules are exhaustively testable, and it keeps the broker adapter
(scripts/alpaca.sh) *behind* the safety boundary rather than being it.

Rules that are NOT mechanised, and why, are documented in UNMECHANISED below.
Knowing what was deliberately left to human judgment matters as much as what
was automated.
"""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, Decimal

from .models import (
    OrderProposal,
    PortfolioState,
    Reservation,
    Rule,
    Side,
    ValidationResult,
    Violation,
    to_money,
)
from .versions import SECTOR_ETFS, V1, StrategyParams

__all__ = [
    "MAX_POSITIONS",
    "MAX_POSITION_PCT",
    "MAX_TRADES_PER_WEEK",
    "MAX_DEPLOYMENT_PCT",
    "MIN_STOP_DISTANCE_PCT",
    "BASE_TRAIL_PCT",
    "UNMECHANISED",
    "validate_order",
    "validate_stop_change",
    "validate_stop_renewal",
    "validate_stop_placement",
    "required_trail_percent",
    "max_affordable_shares",
]

# --- Limits ------------------------------------------------------------------
# The numbers live in risk_engine/versions.py, one record per strategy
# version. These module constants are the v1 baseline, kept so existing
# callers and tests read unchanged; every function below takes `params`.

MAX_POSITIONS = V1.max_positions  # rule 3: "5-6 positions at a time"
MAX_POSITION_PCT = V1.max_position_pct  # rule 3: "max 20% each"
MAX_TRADES_PER_WEEK = V1.max_trades_per_week  # rule 8: "Max 3 new trades per week"
MAX_DEPLOYMENT_PCT = V1.max_deployment_pct  # rule 2: "75-85% deployed" (upper bound)
MIN_STOP_DISTANCE_PCT = V1.min_stop_distance_pct  # rule 7: "never within 3% of current price"
BASE_TRAIL_PCT = V1.base_trail_pct  # rule 4: "10% trailing stop on every position"

# OCC option symbol, e.g. AAPL260116C00150000. Rule 1 is "NO OPTIONS -- ever",
# so this is a shape check on the symbol itself, not a lookup.
_OCC_OPTION = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
_EQUITY_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")

UNMECHANISED: dict[str, str] = {
    "sector_momentum": (
        "Rule 9 'follow sector momentum' -- requires a judgment about which "
        "sectors are leading. No sector data is recorded structurally."
    ),
    "documented_catalyst": (
        "Entry checklist 'specific catalyst?' -- presence in RESEARCH-LOG is "
        "checkable, but whether a catalyst is real is not."
    ),
    "sector_exit_after_two_failures": (
        "Rule 10 -- Script class in v1: scripts/blotter.py --sector-streaks "
        "computes consecutive closed losers per sector from broker fills "
        "(sectors from memory/SECTORS.json) and the routines act on it. The "
        "engine refuses nothing for it; v2 plans engine enforcement."
    ),
    "composition_mandate": (
        "Rule 14 -- the next new position must be a single name while the "
        "book holds none. Decided as an engine check (issue #105), not built "
        "yet (issue #136); until then the routines carry it."
    ),
    "patience_over_activity": (
        "Rule 11 -- a disposition, not a predicate. Deliberately left to the "
        "operator."
    ),
    "min_deployment_backstop": (
        "Rule 12 -- a mandate to ADD risk after 3 under-deployed sessions. "
        "The engine refuses orders; it never compels one. Enforcing this "
        "belongs in the routines, not the safety layer: see "
        "scripts/deployment_status.py (pre-market / market-open STEP 2c)."
    ),
    "cut_losers_at_7pct": (
        "Rule 5 -- an exit trigger evaluated against live prices, not a "
        "property of a proposed order. See required_trail_percent for the "
        "mechanised half of stop management."
    ),
}


def validate_order(
    proposal: OrderProposal, portfolio: PortfolioState, params: StrategyParams = V1
) -> ValidationResult:
    """Judge a proposed order against every mechanised rule of one version.

    Returns every violation, not just the first: a caller fixing one problem
    should not have to re-run to discover the next.
    """
    if not isinstance(proposal, OrderProposal):
        raise TypeError("proposal must be an OrderProposal")
    if not isinstance(portfolio, PortfolioState):
        raise TypeError("portfolio must be a PortfolioState")
    if not isinstance(params, StrategyParams):
        raise TypeError("params must be a StrategyParams")

    violations: list[Violation] = []

    # Rule: paper account only. Checked for buys and sells alike -- this is the
    # account-mode boundary, not a position-sizing concern.
    if not portfolio.is_paper:
        violations.append(
            Violation(
                Rule.PAPER_ACCOUNT_ONLY,
                "account is not a paper account; this system is paper-only",
            )
        )

    # Rule 1: NO OPTIONS -- ever.
    if _OCC_OPTION.match(proposal.symbol) or not _EQUITY_SYMBOL.fullmatch(proposal.symbol):
        violations.append(
            Violation(
                Rule.STOCKS_ONLY,
                f"{proposal.symbol} is not an equity symbol; broker asset verification is also required",
            )
        )

    if proposal.side is Side.SELL:
        violations.extend(_validate_sell(proposal, portfolio))
        return ValidationResult(tuple(violations))

    violations.extend(_validate_buy(proposal, portfolio, params))
    return ValidationResult(tuple(violations))


def _validate_sell(
    proposal: OrderProposal, portfolio: PortfolioState
) -> list[Violation]:
    """Sells reduce risk, so only coherence is checked, never sizing."""
    held = portfolio.position_for(proposal.symbol)
    if held is None:
        return [
            Violation(
                Rule.STOCKS_ONLY,
                f"cannot sell {proposal.symbol}: no such position",
            )
        ]
    if proposal.qty > held.qty:
        return [
            Violation(
                Rule.STOCKS_ONLY,
                f"cannot sell {proposal.qty} of {proposal.symbol}: only {held.qty} held",
            )
        ]
    return []


def _validate_buy(
    proposal: OrderProposal, portfolio: PortfolioState, params: StrategyParams
) -> list[Violation]:
    violations: list[Violation] = []
    notional = proposal.notional
    existing = portfolio.position_for(proposal.symbol)
    fallback = params.is_fallback(proposal.symbol)
    # The fallback (v2 rule 12) is not an active position: it is exempt from
    # the slot count, the sector cap and the weekly count, never from sizing.
    active = [p for p in portfolio.positions if not params.is_fallback(p.symbol)]
    # Reserved symbols not held and not the fallback are positions in waiting:
    # each takes a slot, however many intents reserve it (ADR 0010 §6).
    pending = _pending_symbols(portfolio, params)

    # Rule 3a: at most max_positions open. Adding to an existing or reserved
    # position does not open a new slot.
    opens_slot = not fallback and existing is None and proposal.symbol not in pending
    open_count = len(active) + len(pending) + 1
    if opens_slot and open_count > params.max_positions:
        violations.append(
            Violation(
                Rule.MAX_POSITIONS,
                f"would open position {open_count}, max is {params.max_positions}"
                + _reserved_by([r for rs in pending.values() for r in rs]),
            )
        )

    # Rule 3b: no position may exceed max_position_pct of equity. Measured on
    # the resulting position -- held, reserved and proposed -- so topping up a
    # large holding is caught too.
    same_symbol = [r for r in portfolio.reservations if r.symbol == proposal.symbol]
    resulting_value = (
        notional
        + (existing.market_value if existing else Decimal(0))
        + _notional(same_symbol)
    )
    position_pct = _pct(resulting_value, portfolio.equity)
    if not fallback and position_pct > params.max_position_pct:
        violations.append(
            Violation(
                Rule.MAX_POSITION_PCT,
                f"{proposal.symbol} would be {position_pct:.2f}% of equity, max is {params.max_position_pct}%"
                + _reserved_by(same_symbol),
            )
        )

    # v2 rule 3: sector concentration cap. Counting requires every active
    # position to carry a sector; an unknown sector is refused, not skipped.
    if params.max_sector_positions is not None and opens_slot:
        violations.extend(_validate_sector_cap(proposal, active, pending, params))

    # v2 rule 9: sector ETFs are not active positions.
    if not params.sector_etfs_allowed and proposal.symbol in SECTOR_ETFS:
        violations.append(
            Violation(
                Rule.UNIVERSE,
                f"{proposal.symbol} is a sector ETF; not eligible as an active position under {params.name}",
            )
        )

    # v2 rule 14: re-entry cooldown after a stop-out in the same name.
    if (params.reentry_cooldown_sessions > 0 and not fallback
            and proposal.symbol in portfolio.cooldown_symbols):
        violations.append(
            Violation(
                Rule.REENTRY_COOLDOWN,
                f"{proposal.symbol} exited within the last {params.reentry_cooldown_sessions} sessions",
            )
        )

    # Rule 8: at most max_trades_per_week new trades per week. trades_this_week
    # counts filled buys, so every non-fallback reservation -- an add to a held
    # name included -- is a trade that will be counted once it fills.
    weekly = [r for r in portfolio.reservations if not params.is_fallback(r.symbol)]
    trade_number = portfolio.trades_this_week + len(weekly) + 1
    if not fallback and trade_number > params.max_trades_per_week:
        violations.append(
            Violation(
                Rule.MAX_TRADES_PER_WEEK,
                f"would be trade {trade_number} this week, max is {params.max_trades_per_week}"
                + _reserved_by(weekly),
            )
        )

    # Rule 13: cash only, never margin. portfolio.cash is settled cash, not
    # buying_power -- the account is a margin account, so buying_power runs
    # several times equity and would silently permit a leveraged buy. Cash
    # already promised to a reservation, the fallback's included, is not free.
    reserved = list(portfolio.reservations)
    available = portfolio.cash - _notional(reserved)
    if notional > available:
        violations.append(
            Violation(
                Rule.SUFFICIENT_CASH,
                f"costs {notional} but only {available} cash available"
                + _reserved_by(reserved),
            )
        )

    # Rule 2: deployment band upper bound. The lower bound is a mandate to add
    # risk, not a reason to refuse -- see UNMECHANISED.
    deployment_pct = _pct(
        portfolio.deployed_value + _notional(reserved) + notional, portfolio.equity
    )
    if deployment_pct > params.max_deployment_pct:
        violations.append(
            Violation(
                Rule.MAX_DEPLOYMENT_PCT,
                f"would deploy {deployment_pct:.2f}% of equity, max is {params.max_deployment_pct}%"
                + _reserved_by(reserved),
            )
        )

    violations.extend(_validate_protection(proposal, params))
    return violations


def _pending_symbols(
    portfolio: PortfolioState, params: StrategyParams
) -> dict[str, list[Reservation]]:
    """Reserved symbols that will open a new active position, with their reservations."""
    held = {p.symbol for p in portfolio.positions}
    pending: dict[str, list[Reservation]] = {}
    for r in portfolio.reservations:
        if r.symbol not in held and not params.is_fallback(r.symbol):
            pending.setdefault(r.symbol, []).append(r)
    return pending


def _notional(reservations: list[Reservation]) -> Decimal:
    return sum((r.notional for r in reservations), Decimal(0))


def _reserved_by(reservations: list[Reservation]) -> str:
    """Name the intents behind a refusal, so it can be explained."""
    if not reservations:
        return ""
    return f" (reserved by intent {', '.join(r.intent_id for r in reservations)})"


def _validate_sector_cap(
    proposal: OrderProposal, active: list, pending: dict[str, list[Reservation]],
    params: StrategyParams,
) -> list[Violation]:
    if proposal.sector is None:
        return [
            Violation(
                Rule.MAX_SECTOR_POSITIONS,
                f"{params.name} caps positions per sector; the proposal must state its sector",
            )
        ]
    unknown = [p.symbol for p in active if p.sector is None]
    unknown_reserved = [r for rs in pending.values() for r in rs if r.sector is None]
    if unknown or unknown_reserved:
        names = unknown + sorted({r.symbol for r in unknown_reserved})
        return [
            Violation(
                Rule.MAX_SECTOR_POSITIONS,
                f"cannot count sector exposure: no sector recorded for {', '.join(names)}"
                + _reserved_by(unknown_reserved),
            )
        ]
    same = [p.symbol for p in active if p.sector == proposal.sector]
    same_reserved = {
        symbol: rs for symbol, rs in pending.items()
        if any(r.sector == proposal.sector for r in rs)
    }
    if len(same) + len(same_reserved) + 1 > params.max_sector_positions:
        return [
            Violation(
                Rule.MAX_SECTOR_POSITIONS,
                f"{proposal.sector} already holds {', '.join(same + sorted(same_reserved))}; "
                f"max {params.max_sector_positions} per sector"
                + _reserved_by([r for rs in same_reserved.values() for r in rs]),
            )
        ]
    return []


def _validate_protection(proposal: OrderProposal, params: StrategyParams) -> list[Violation]:
    """Rule 4: every buy must carry its protective stop.

    The engine refuses to approve an unprotected buy at all, which is the
    structural answer to the buy-then-hope-the-stop-lands flow: protection is
    part of the order's definition, not a follow-up call that might fail.
    """
    has_stop = proposal.stop_price is not None
    has_trail = proposal.trail_percent is not None
    if not has_stop and not has_trail:
        return [
            Violation(
                Rule.STOP_REQUIRED,
                "buy has no stop_price and no trail_percent; every position "
                "requires a stop",
            )
        ]

    violations: list[Violation] = []
    if has_stop and has_trail:
        violations.append(Violation(Rule.STOP_REQUIRED, "specify exactly one protection type"))
    low, high = params.entry_stop_band
    if has_stop:
        # Rule 7: never within min_stop_distance_pct of current price.
        distance_pct = _pct(proposal.price - proposal.stop_price, proposal.price)
        if proposal.stop_price >= proposal.price:
            violations.append(
                Violation(
                    Rule.STOP_DISTANCE,
                    f"stop {proposal.stop_price} is not below entry {proposal.price}",
                )
            )
        elif distance_pct < params.min_stop_distance_pct:
            violations.append(
                Violation(
                    Rule.STOP_DISTANCE,
                    f"stop is {distance_pct:.2f}% below price, minimum is {params.min_stop_distance_pct}%",
                )
            )
        if not low <= distance_pct <= high:
            violations.append(Violation(
                Rule.STOP_DISTANCE,
                f"entry fixed stop must be {low}–{high}% below entry, got {distance_pct:.2f}%",
            ))
    if has_trail and proposal.trail_percent < params.min_stop_distance_pct:
        violations.append(
            Violation(
                Rule.STOP_DISTANCE,
                f"trail of {proposal.trail_percent}% is inside the "
                f"{params.min_stop_distance_pct}% minimum distance",
            )
        )
    if has_trail and proposal.trail_percent != params.base_trail_pct:
        violations.append(Violation(
            Rule.STOP_DISTANCE, f"entry trail must be {params.base_trail_pct}%",
        ))
    return violations


def validate_stop_change(
    current_stop: object, new_stop: object, current_price: object,
    params: StrategyParams = V1,
) -> ValidationResult:
    """Rule 7: a stop may be raised or held, never lowered, never too close.

    Separate from validate_order because moving a stop is a different act from
    opening a position, with a different rule set.
    """
    current = to_money(current_stop, "current_stop")
    proposed = to_money(new_stop, "new_stop")
    price = to_money(current_price, "current_price")
    if price <= 0:
        raise ValueError(f"current_price must be positive, got {price}")
    if current <= 0 or proposed <= 0:
        raise ValueError("current_stop and new_stop must be positive")

    violations: list[Violation] = []
    if proposed < current:
        violations.append(
            Violation(
                Rule.STOP_NEVER_LOWERED,
                f"stop may never move down: {current} -> {proposed}",
            )
        )
    violations.extend(validate_stop_placement(proposed, price, params).violations)
    return ValidationResult(tuple(violations))


def validate_stop_placement(
    new_stop: object, current_price: object, params: StrategyParams = V1,
) -> ValidationResult:
    """Rule 7's distance clause: never place or move a stop to within the
    minimum distance of current price (3% in v1)."""
    proposed = to_money(new_stop, "new_stop")
    price = to_money(current_price, "current_price")
    if price <= 0:
        raise ValueError(f"current_price must be positive, got {price}")
    if proposed <= 0:
        raise ValueError(f"new_stop must be positive, got {proposed}")
    if proposed >= price:
        return ValidationResult((Violation(
            Rule.STOP_DISTANCE, f"stop {proposed} is at or above current price {price}"),))
    distance_pct = _pct(price - proposed, price)
    if distance_pct < params.min_stop_distance_pct:
        return ValidationResult((Violation(
            Rule.STOP_DISTANCE,
            f"stop is {distance_pct:.2f}% below price, minimum is {params.min_stop_distance_pct}%"),))
    return ValidationResult(())


def is_renewal_level(current_stop: object, new_stop: object) -> bool:
    """True when new_stop is current_stop rounded up to the cent: the level a
    renewal places (risk_engine.protection.expiring_protective_stops)."""
    current = to_money(current_stop, "current_stop")
    proposed = to_money(new_stop, "new_stop")
    return current <= proposed <= current.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def validate_stop_renewal(
    current_stop: object, new_stop: object, current_price: object,
    params: StrategyParams = V1,
) -> ValidationResult:
    """Rule 7 (v1.2): renewing a stop at its current level is never a violation.

    A renewal re-places the floor as a fixed stop (rounded up to the cent), so
    it neither lowers nor moves the stop, and the 3% minimum -- which governs
    placing or moving a stop -- does not apply: price drifting within 3% of a
    standing stop is a hold, and renewal keeps that hold in place. Any other
    level is a change and gets the full rule 7 check (validate_stop_change).
    """
    if not is_renewal_level(current_stop, new_stop):
        return validate_stop_change(current_stop, new_stop, current_price, params)
    proposed = to_money(new_stop, "new_stop")
    price = to_money(current_price, "current_price")
    if price <= 0:
        raise ValueError(f"current_price must be positive, got {price}")
    if proposed <= 0:
        raise ValueError("current_stop and new_stop must be positive")
    if proposed >= price:
        return ValidationResult((Violation(
            Rule.STOP_DISTANCE, f"stop {proposed} is at or above current price {price}"),))
    return ValidationResult(())


def required_trail_percent(gain_pct: object, params: StrategyParams = V1) -> Decimal:
    """Rule 6: the trail ladder (v1: 10% base, 7% at +15%, 5% at +20%).

    Returns the tightest trail the ladder requires at this gain. Never widens:
    once a threshold is crossed the tighter trail is required.
    """
    gain = to_money(gain_pct, "gain_pct")
    required = params.base_trail_pct
    for threshold, trail in params.trail_ladder:
        if gain >= threshold and trail < required:
            required = trail
    return required


def max_affordable_shares(
    portfolio: PortfolioState, price: object, symbol: str | None = None,
    params: StrategyParams = V1,
) -> int:
    """Largest whole-share buy that violates no sizing rule.

    Sizing is derived from the limits rather than chosen and then checked, so
    the caller cannot arrive at a number the engine would refuse.
    """
    unit = to_money(price, "price")
    if unit <= 0:
        raise ValueError(f"price must be positive, got {unit}")

    existing = portfolio.position_for(symbol) if symbol else None
    held_value = existing.market_value if existing else Decimal(0)
    # Reservations count exactly as validate_order counts them: in the same
    # name toward its size, all of them toward deployment and against cash.
    reserved = list(portfolio.reservations)
    target = symbol.strip().upper() if symbol else None
    held_value += _notional([r for r in reserved if r.symbol == target])

    position_headroom = (portfolio.equity * params.max_position_pct / 100) - held_value
    deployment_headroom = (
        portfolio.equity * params.max_deployment_pct / 100
    ) - (portfolio.deployed_value + _notional(reserved))
    budget = min(position_headroom, deployment_headroom, portfolio.cash - _notional(reserved))
    if budget <= 0:
        return 0
    return int(budget / unit)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    return (part / whole) * 100
