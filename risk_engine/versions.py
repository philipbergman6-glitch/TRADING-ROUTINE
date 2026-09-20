"""Strategy versions as data (docs/STRATEGY-SPEC.md).

Every numeric limit the engine enforces lives in one frozen `StrategyParams`
record per version, so v1 (the frozen baseline) and v2 (the proposed
successor) are validated by the same code under different parameters. Nothing
here reads the environment or the clock; `params_from_env` takes a mapping so
the CLI boundary decides which version is active and the engine stays pure.

The default everywhere is V1. Switching a routine to v2 is a deliberate
segment start (spec section 5), done by setting STRATEGY_VERSION=v2 in the
routine's environment, not by editing this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

__all__ = [
    "StrategyParams",
    "V1",
    "V2",
    "VERSIONS",
    "SECTOR_ETFS",
    "STRATEGY_VERSION_ENV",
    "params_for",
    "params_from_env",
]

STRATEGY_VERSION_ENV = "STRATEGY_VERSION"

# SPDR Select Sector funds. Under v2 these are ineligible as active positions
# (spec rule 9); the fallback instrument is SPY, which is not in this set.
SECTOR_ETFS: frozenset[str] = frozenset(
    {"XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"}
)


@dataclass(frozen=True)
class StrategyParams:
    """Every limit the engine mechanises, for one strategy version."""

    name: str
    max_positions: int
    max_position_pct: Decimal
    max_trades_per_week: int
    max_deployment_pct: Decimal
    min_stop_distance_pct: Decimal
    base_trail_pct: Decimal
    # Distance of the fixed OTO protective leg below entry (ADR 0002): the
    # derived default and the band the engine accepts.
    entry_stop_pct: Decimal
    entry_stop_band: tuple[Decimal, Decimal]
    # Rule 6 ladder, widest-first is NOT assumed: (gain threshold, trail).
    trail_ladder: tuple[tuple[Decimal, Decimal], ...]
    # v2 rule 5: the fixed leg converts to the base trail only once the
    # position is at least this far above entry. None = convert immediately (v1).
    trail_convert_gain_pct: Decimal | None
    # v2 rule 3: at most this many active positions per sector. None = no cap.
    max_sector_positions: int | None
    # v2 rule 14: sessions after a stop-out before the same name may re-enter.
    reentry_cooldown_sessions: int
    # v2 rule 12: symbol exempt from position, sector and weekly counts.
    fallback_symbol: str | None
    # v2 rule 9: sector ETFs may not be active positions.
    sector_etfs_allowed: bool

    def __post_init__(self) -> None:
        if self.max_positions <= 0 or self.max_trades_per_week <= 0:
            raise ValueError("position and trade limits must be positive")
        low, high = self.entry_stop_band
        if not (0 < low <= self.entry_stop_pct <= high < 100):
            raise ValueError("entry_stop_pct must sit inside entry_stop_band")
        if low < self.min_stop_distance_pct:
            raise ValueError("entry stop band must respect the minimum distance")
        for threshold, trail in self.trail_ladder:
            if trail < self.min_stop_distance_pct or trail > self.base_trail_pct:
                raise ValueError(f"ladder trail {trail} outside [min distance, base trail]")
            if threshold <= 0:
                raise ValueError("ladder thresholds must be positive gains")
        if self.max_sector_positions is not None and self.max_sector_positions <= 0:
            raise ValueError("max_sector_positions must be positive or None")
        if self.reentry_cooldown_sessions < 0:
            raise ValueError("reentry_cooldown_sessions must be non-negative")
        if self.fallback_symbol is not None and self.fallback_symbol in SECTOR_ETFS:
            raise ValueError("fallback symbol may not be a sector ETF")

    def is_fallback(self, symbol: str) -> bool:
        return self.fallback_symbol is not None and symbol == self.fallback_symbol


V1 = StrategyParams(
    name="v1",
    max_positions=6,
    max_position_pct=Decimal("20"),
    max_trades_per_week=3,
    max_deployment_pct=Decimal("85"),
    min_stop_distance_pct=Decimal("3"),
    base_trail_pct=Decimal("10"),
    entry_stop_pct=Decimal("10"),
    entry_stop_band=(Decimal("9.5"), Decimal("10.5")),
    trail_ladder=((Decimal("20"), Decimal("5")), (Decimal("15"), Decimal("7"))),
    trail_convert_gain_pct=None,
    max_sector_positions=None,
    reentry_cooldown_sessions=0,
    fallback_symbol=None,
    sector_etfs_allowed=True,
)

V2 = StrategyParams(
    name="v2",
    max_positions=5,
    max_position_pct=Decimal("20"),
    max_trades_per_week=3,
    max_deployment_pct=Decimal("85"),
    min_stop_distance_pct=Decimal("3"),
    base_trail_pct=Decimal("10"),
    entry_stop_pct=Decimal("7"),
    entry_stop_band=(Decimal("6.5"), Decimal("7.5")),
    trail_ladder=((Decimal("15"), Decimal("7")),),
    trail_convert_gain_pct=Decimal("5"),
    max_sector_positions=2,
    reentry_cooldown_sessions=10,
    fallback_symbol="SPY",
    sector_etfs_allowed=False,
)

VERSIONS: Mapping[str, StrategyParams] = {V1.name: V1, V2.name: V2}


def params_for(name: object) -> StrategyParams:
    """Look a version up by name. Unknown names are an error, never a default."""
    if not isinstance(name, str) or name not in VERSIONS:
        raise ValueError(f"unknown strategy version {name!r}; known: {sorted(VERSIONS)}")
    return VERSIONS[name]


def params_from_env(environ: Mapping[str, str]) -> StrategyParams:
    """Active version from STRATEGY_VERSION; unset means v1, garbage is an error."""
    raw = environ.get(STRATEGY_VERSION_ENV)
    if raw is None or raw == "":
        return V1
    return params_for(raw.strip().lower())
