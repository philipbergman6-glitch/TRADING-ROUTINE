"""Deterministic risk engine for the paper trading bot.

The model may propose a trade. It may not bypass this module.

    from risk_engine import OrderProposal, PortfolioState, validate_order

    result = validate_order(proposal, portfolio)
    if not result:
        print(result.reasons())   # every rule broken, not just the first
"""

from .engine import (
    BASE_TRAIL_PCT,
    MAX_DEPLOYMENT_PCT,
    MAX_POSITION_PCT,
    MAX_POSITIONS,
    MAX_TRADES_PER_WEEK,
    MIN_STOP_DISTANCE_PCT,
    UNMECHANISED,
    max_affordable_shares,
    required_trail_percent,
    validate_order,
    validate_stop_change,
)
from .models import (
    OrderProposal,
    PortfolioState,
    Position,
    Rule,
    Side,
    ValidationResult,
    Violation,
)

__all__ = [
    "BASE_TRAIL_PCT",
    "MAX_DEPLOYMENT_PCT",
    "MAX_POSITIONS",
    "MAX_POSITION_PCT",
    "MAX_TRADES_PER_WEEK",
    "MIN_STOP_DISTANCE_PCT",
    "UNMECHANISED",
    "OrderProposal",
    "PortfolioState",
    "Position",
    "Rule",
    "Side",
    "ValidationResult",
    "Violation",
    "max_affordable_shares",
    "required_trail_percent",
    "validate_order",
    "validate_stop_change",
]
