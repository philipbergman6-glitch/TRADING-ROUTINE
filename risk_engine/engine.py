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
from decimal import Decimal

from .models import (
    OrderProposal,
    PortfolioState,
    Rule,
    Side,
    ValidationResult,
    Violation,
    to_money,
)

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
    "required_trail_percent",
    "max_affordable_shares",
]

# --- Limits, straight from memory/TRADING-STRATEGY.md -----------------------

MAX_POSITIONS = 6  # rule 3: "5-6 positions at a time"
MAX_POSITION_PCT = Decimal("20")  # rule 3: "max 20% each"
MAX_TRADES_PER_WEEK = 3  # rule 8: "Max 3 new trades per week"
MAX_DEPLOYMENT_PCT = Decimal("85")  # rule 2: "75-85% deployed" (upper bound)
MIN_STOP_DISTANCE_PCT = Decimal("3")  # rule 7: "never within 3% of current price"
BASE_TRAIL_PCT = Decimal("10")  # rule 4: "10% trailing stop on every position"

# Rule 6 ladder: tighten trail to 7% at +15%, to 5% at +20%.
_TRAIL_LADDER: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("20"), Decimal("5")),
    (Decimal("15"), Decimal("7")),
)

# OCC option symbol, e.g. AAPL260116C00150000. Rule 1 is "NO OPTIONS -- ever",
# so this is a shape check on the symbol itself, not a lookup.
_OCC_OPTION = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

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
        "Rule 10 -- mechanisable in principle, blocked on data: TRADE-LOG "
        "records no sector field, so consecutive failures per sector cannot "
        "be computed. Add the field and this rule graduates into the engine."
    ),
    "patience_over_activity": (
        "Rule 11 -- a disposition, not a predicate. Deliberately left to the "
        "operator."
    ),
    "min_deployment_backstop": (
        "Rule 12 -- a mandate to ADD risk after 3 under-deployed sessions. "
        "The engine refuses orders; it never compels one. Enforcing this "
        "belongs in the routines, not the safety layer."
    ),
    "cut_losers_at_7pct": (
        "Rule 5 -- an exit trigger evaluated against live prices, not a "
        "property of a proposed order. See required_trail_percent for the "
        "mechanised half of stop management."
    ),
}


def validate_order(
    proposal: OrderProposal, portfolio: PortfolioState
) -> ValidationResult:
    """Judge a proposed order against every mechanised rule.

    Returns every violation, not just the first: a caller fixing one problem
    should not have to re-run to discover the next.
    """
    if not isinstance(proposal, OrderProposal):
        raise TypeError("proposal must be an OrderProposal")
    if not isinstance(portfolio, PortfolioState):
        raise TypeError("portfolio must be a PortfolioState")

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
    if _OCC_OPTION.match(proposal.symbol):
        violations.append(
            Violation(
                Rule.STOCKS_ONLY,
                f"{proposal.symbol} is an option contract symbol; stocks only",
            )
        )

    if proposal.side is Side.SELL:
        violations.extend(_validate_sell(proposal, portfolio))
        return ValidationResult(tuple(violations))

    violations.extend(_validate_buy(proposal, portfolio))
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
    proposal: OrderProposal, portfolio: PortfolioState
) -> list[Violation]:
    violations: list[Violation] = []
    notional = proposal.notional
    existing = portfolio.position_for(proposal.symbol)

    # Rule 3a: at most MAX_POSITIONS open. Adding to an existing position does
    # not open a new slot.
    if existing is None and len(portfolio.positions) + 1 > MAX_POSITIONS:
        violations.append(
            Violation(
                Rule.MAX_POSITIONS,
                f"would open position {len(portfolio.positions) + 1}, max is {MAX_POSITIONS}",
            )
        )

    # Rule 3b: no position may exceed MAX_POSITION_PCT of equity. Measured on
    # the resulting position, so topping up a large holding is caught too.
    resulting_value = notional + (existing.market_value if existing else Decimal(0))
    position_pct = _pct(resulting_value, portfolio.equity)
    if position_pct > MAX_POSITION_PCT:
        violations.append(
            Violation(
                Rule.MAX_POSITION_PCT,
                f"{proposal.symbol} would be {position_pct:.2f}% of equity, max is {MAX_POSITION_PCT}%",
            )
        )

    # Rule 8: at most MAX_TRADES_PER_WEEK new trades per week.
    if portfolio.trades_this_week + 1 > MAX_TRADES_PER_WEEK:
        violations.append(
            Violation(
                Rule.MAX_TRADES_PER_WEEK,
                f"would be trade {portfolio.trades_this_week + 1} this week, max is {MAX_TRADES_PER_WEEK}",
            )
        )

    # Rule 13: cash only, never margin. portfolio.cash is settled cash, not
    # buying_power -- the account is a margin account, so buying_power runs
    # several times equity and would silently permit a leveraged buy.
    if notional > portfolio.cash:
        violations.append(
            Violation(
                Rule.SUFFICIENT_CASH,
                f"costs {notional} but only {portfolio.cash} cash available",
            )
        )

    # Rule 2: deployment band upper bound. The lower bound is a mandate to add
    # risk, not a reason to refuse -- see UNMECHANISED.
    deployment_pct = _pct(portfolio.deployed_value + notional, portfolio.equity)
    if deployment_pct > MAX_DEPLOYMENT_PCT:
        violations.append(
            Violation(
                Rule.MAX_DEPLOYMENT_PCT,
                f"would deploy {deployment_pct:.2f}% of equity, max is {MAX_DEPLOYMENT_PCT}%",
            )
        )

    violations.extend(_validate_protection(proposal))
    return violations


def _validate_protection(proposal: OrderProposal) -> list[Violation]:
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
    if has_stop:
        # Rule 7: never within MIN_STOP_DISTANCE_PCT of current price.
        distance_pct = _pct(proposal.price - proposal.stop_price, proposal.price)
        if proposal.stop_price >= proposal.price:
            violations.append(
                Violation(
                    Rule.STOP_DISTANCE,
                    f"stop {proposal.stop_price} is not below entry {proposal.price}",
                )
            )
        elif distance_pct < MIN_STOP_DISTANCE_PCT:
            violations.append(
                Violation(
                    Rule.STOP_DISTANCE,
                    f"stop is {distance_pct:.2f}% below price, minimum is {MIN_STOP_DISTANCE_PCT}%",
                )
            )
    if has_trail and proposal.trail_percent < MIN_STOP_DISTANCE_PCT:
        violations.append(
            Violation(
                Rule.STOP_DISTANCE,
                f"trail of {proposal.trail_percent}% is inside the "
                f"{MIN_STOP_DISTANCE_PCT}% minimum distance",
            )
        )
    return violations


def validate_stop_change(
    current_stop: object, new_stop: object, current_price: object
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

    violations: list[Violation] = []
    if proposed < current:
        violations.append(
            Violation(
                Rule.STOP_NEVER_LOWERED,
                f"stop may never move down: {current} -> {proposed}",
            )
        )
    if proposed >= price:
        violations.append(
            Violation(
                Rule.STOP_DISTANCE,
                f"stop {proposed} is at or above current price {price}",
            )
        )
    else:
        distance_pct = _pct(price - proposed, price)
        if distance_pct < MIN_STOP_DISTANCE_PCT:
            violations.append(
                Violation(
                    Rule.STOP_DISTANCE,
                    f"stop is {distance_pct:.2f}% below price, minimum is {MIN_STOP_DISTANCE_PCT}%",
                )
            )
    return ValidationResult(tuple(violations))


def required_trail_percent(gain_pct: object) -> Decimal:
    """Rule 6: the trail ladder -- 10% base, 7% at +15%, 5% at +20%.

    Returns the widest trail still permitted at this gain. Never widens: once
    a threshold is crossed the tighter trail is required.
    """
    gain = to_money(gain_pct, "gain_pct")
    for threshold, trail in _TRAIL_LADDER:
        if gain >= threshold:
            return trail
    return BASE_TRAIL_PCT


def max_affordable_shares(
    portfolio: PortfolioState, price: object, symbol: str | None = None
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

    position_headroom = (portfolio.equity * MAX_POSITION_PCT / 100) - held_value
    deployment_headroom = (
        portfolio.equity * MAX_DEPLOYMENT_PCT / 100
    ) - portfolio.deployed_value
    budget = min(position_headroom, deployment_headroom, portfolio.cash)
    if budget <= 0:
        return 0
    return int(budget / unit)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    return (part / whole) * 100
