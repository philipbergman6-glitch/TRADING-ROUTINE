"""Value types for the risk engine.

Money is Decimal everywhere. Floats are refused at the boundary rather than
silently rounded -- a position-size check that is off by a cent is a bug you
find in production, not in review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum

__all__ = [
    "Rule",
    "Side",
    "Violation",
    "ValidationResult",
    "Position",
    "PortfolioState",
    "OrderProposal",
    "to_money",
]


class Rule(str, Enum):
    """Every mechanised rule in memory/TRADING-STRATEGY.md.

    The enum *is* the contract: a violation names the rule it broke, so a
    refusal is auditable rather than a bare False. Values are stable strings
    because they get written to the ledger.
    """

    PAPER_ACCOUNT_ONLY = "paper_account_only"
    STOCKS_ONLY = "stocks_only"
    MAX_POSITIONS = "max_positions"
    MAX_POSITION_PCT = "max_position_pct"
    MAX_TRADES_PER_WEEK = "max_trades_per_week"
    SUFFICIENT_CASH = "sufficient_cash"
    MAX_DEPLOYMENT_PCT = "max_deployment_pct"
    STOP_REQUIRED = "stop_required"
    STOP_NEVER_LOWERED = "stop_never_lowered"
    STOP_DISTANCE = "stop_distance"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


def to_money(value: object, field_name: str) -> Decimal:
    """Coerce to Decimal, hard-failing on anything lossy or nonsensical.

    Floats are rejected outright rather than converted: accepting 0.1 as
    Decimal('0.1000000000000000055511151231257827021181583404541015625') is
    exactly the silent failure this module exists to prevent.
    """
    if isinstance(value, float):
        raise TypeError(
            f"{field_name}: float is not accepted for money; pass str/int/Decimal"
        )
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, (int, str)):
        try:
            candidate = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name}: not a valid decimal: {value!r}") from exc
    else:
        raise TypeError(f"{field_name}: unsupported type {type(value).__name__}")
    if not candidate.is_finite():
        raise ValueError(f"{field_name}: must be finite, got {candidate}")
    return candidate


@dataclass(frozen=True)
class Violation:
    rule: Rule
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.rule.value}: {self.detail}"


@dataclass(frozen=True)
class ValidationResult:
    """The engine's verdict. Falsy when the order must not be sent."""

    violations: tuple[Violation, ...] = ()

    @property
    def approved(self) -> bool:
        return not self.violations

    def __bool__(self) -> bool:
        return self.approved

    def broke(self, rule: Rule) -> bool:
        return any(v.rule is rule for v in self.violations)

    def reasons(self) -> list[str]:
        return [str(v) for v in self.violations]


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: Decimal
    market_value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _clean_symbol(self.symbol))
        object.__setattr__(self, "qty", to_money(self.qty, "Position.qty"))
        object.__setattr__(
            self, "market_value", to_money(self.market_value, "Position.market_value")
        )


@dataclass(frozen=True)
class PortfolioState:
    """A snapshot of the account, as read from the broker.

    `is_paper` is not defaulted on purpose. A caller that forgets to say which
    account this is must fail loudly rather than inherit a convenient default.
    """

    equity: Decimal
    cash: Decimal
    is_paper: bool
    positions: tuple[Position, ...] = ()
    trades_this_week: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "equity", to_money(self.equity, "PortfolioState.equity"))
        object.__setattr__(self, "cash", to_money(self.cash, "PortfolioState.cash"))
        if not isinstance(self.is_paper, bool):
            raise TypeError("PortfolioState.is_paper must be an explicit bool")
        if self.equity <= 0:
            raise ValueError(f"PortfolioState.equity must be positive, got {self.equity}")
        if not isinstance(self.trades_this_week, int) or self.trades_this_week < 0:
            raise ValueError("PortfolioState.trades_this_week must be a non-negative int")
        object.__setattr__(self, "positions", tuple(self.positions))

    def position_for(self, symbol: str) -> Position | None:
        target = _clean_symbol(symbol)
        return next((p for p in self.positions if p.symbol == target), None)

    @property
    def deployed_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions), Decimal(0))


@dataclass(frozen=True)
class OrderProposal:
    """A trade the model wants to make. Untrusted input by definition."""

    symbol: str
    qty: Decimal
    side: Side
    price: Decimal
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None
    metadata: dict = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _clean_symbol(self.symbol))
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "qty", to_money(self.qty, "OrderProposal.qty"))
        object.__setattr__(self, "price", to_money(self.price, "OrderProposal.price"))
        if self.qty <= 0:
            raise ValueError(f"OrderProposal.qty must be positive, got {self.qty}")
        if self.qty != self.qty.to_integral_value():
            raise ValueError(f"OrderProposal.qty must be whole shares, got {self.qty}")
        if self.price <= 0:
            raise ValueError(f"OrderProposal.price must be positive, got {self.price}")
        if self.stop_price is not None:
            object.__setattr__(
                self, "stop_price", to_money(self.stop_price, "OrderProposal.stop_price")
            )
        if self.trail_percent is not None:
            object.__setattr__(
                self,
                "trail_percent",
                to_money(self.trail_percent, "OrderProposal.trail_percent"),
            )

    @property
    def notional(self) -> Decimal:
        return self.qty * self.price


def _clean_symbol(symbol: object) -> str:
    if not isinstance(symbol, str):
        raise TypeError(f"symbol must be a string, got {type(symbol).__name__}")
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise ValueError("symbol must not be empty")
    return cleaned
