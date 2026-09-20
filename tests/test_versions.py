"""Strategy versions: v1 is byte-for-byte the old behaviour, v2 changes only
what docs/STRATEGY-SPEC.md says it changes, and each v2 rule is proved in
both directions."""

from decimal import Decimal

import pytest

from risk_engine import (
    BASE_TRAIL_PCT,
    MAX_POSITIONS,
    MIN_STOP_DISTANCE_PCT,
    SECTOR_ETFS,
    V1,
    V2,
    OrderProposal,
    PortfolioState,
    Position,
    Rule,
    Side,
    StrategyParams,
    max_affordable_shares,
    params_for,
    params_from_env,
    required_trail_percent,
    validate_order,
    validate_stop_change,
)
from risk_engine.protection import fixed_stop_at_distance


def portfolio(**overrides) -> PortfolioState:
    defaults = dict(equity=Decimal("10000"), cash=Decimal("10000"), is_paper=True,
                    positions=(), trades_this_week=0)
    return PortfolioState(**{**defaults, **overrides})


def buy(**overrides) -> OrderProposal:
    """A v2-abiding buy: 10 shares at $100 (10% of $10k) with a 7% fixed stop."""
    defaults = dict(symbol="AMD", qty=Decimal("10"), side=Side.BUY, price=Decimal("100"),
                    stop_price=Decimal("93"), sector="Information Technology")
    return OrderProposal(**{**defaults, **overrides})


def pos(symbol, sector=None, value="1000"):
    return Position(symbol=symbol, qty=Decimal("10"), market_value=Decimal(value), sector=sector)


# --- lookup ----------------------------------------------------------------

def test_module_constants_are_v1():
    assert (MAX_POSITIONS, BASE_TRAIL_PCT, MIN_STOP_DISTANCE_PCT) == (
        V1.max_positions, V1.base_trail_pct, V1.min_stop_distance_pct)


def test_params_from_env_defaults_to_v1_and_rejects_garbage():
    assert params_from_env({}) is V1
    assert params_from_env({"STRATEGY_VERSION": ""}) is V1
    assert params_from_env({"STRATEGY_VERSION": "V2"}) is V2
    with pytest.raises(ValueError):
        params_from_env({"STRATEGY_VERSION": "v3"})
    with pytest.raises(ValueError):
        params_for(None)


def test_params_are_self_consistent():
    with pytest.raises(ValueError):
        StrategyParams(**{**V2.__dict__, "entry_stop_pct": Decimal("9")})
    with pytest.raises(ValueError):
        StrategyParams(**{**V2.__dict__, "fallback_symbol": "XLK"})


# --- v1 unchanged ------------------------------------------------------------

def test_v1_default_is_identical_to_explicit_v1():
    p = buy(stop_price=Decimal("90"), sector=None)
    assert validate_order(p, portfolio()).approved
    assert validate_order(p, portfolio(), V1).approved


def test_v1_ignores_sector_cooldown_and_sector_etfs():
    state = portfolio(positions=(pos("NVDA", None), pos("AVGO", None)),
                      cooldown_symbols=frozenset({"XLK"}))
    p = buy(symbol="XLK", stop_price=Decimal("90"), sector=None)
    assert validate_order(p, state, V1).approved


# --- v2 entry stop -----------------------------------------------------------

@pytest.mark.parametrize("stop, ok", [("93", True), ("93.5", True), ("92.5", True),
                                      ("90", False), ("94", False)])
def test_v2_entry_stop_band_is_seven_percent(stop, ok):
    result = validate_order(buy(stop_price=Decimal(stop)), portfolio(), V2)
    assert result.approved is ok
    if not ok:
        assert result.broke(Rule.STOP_DISTANCE)


def test_fixed_stop_at_distance_uses_version_entry_pct():
    assert fixed_stop_at_distance("100", V2.entry_stop_pct).stop_price == Decimal("93.00")
    assert fixed_stop_at_distance("100", V1.entry_stop_pct).stop_price == Decimal("90.00")


# --- v2 trail ladder ---------------------------------------------------------

@pytest.mark.parametrize("gain, v1, v2", [("0", "10", "10"), ("14.99", "10", "10"),
                                          ("15", "7", "7"), ("20", "5", "7"), ("50", "5", "7")])
def test_trail_ladder_per_version(gain, v1, v2):
    assert required_trail_percent(gain, V1) == Decimal(v1)
    assert required_trail_percent(gain, V2) == Decimal(v2)
    assert required_trail_percent(gain) == Decimal(v1)


def test_v2_converts_fixed_leg_only_after_five_percent():
    assert V1.trail_convert_gain_pct is None
    assert V2.trail_convert_gain_pct == Decimal("5")


# --- v2 sector cap -----------------------------------------------------------

def test_v2_sector_cap_allows_second_refuses_third():
    tech = "Information Technology"
    two = portfolio(positions=(pos("NVDA", tech), pos("AVGO", tech)))
    one = portfolio(positions=(pos("NVDA", tech), pos("XOM", "Energy")))
    assert validate_order(buy(sector=tech), one, V2).approved
    result = validate_order(buy(sector=tech), two, V2)
    assert result.broke(Rule.MAX_SECTOR_POSITIONS)
    assert validate_order(buy(sector="Energy"), two, V2).approved


def test_v2_sector_cap_refuses_when_a_sector_is_unknown():
    assert validate_order(buy(sector=None), portfolio(), V2).broke(Rule.MAX_SECTOR_POSITIONS)
    state = portfolio(positions=(pos("NVDA", None),))
    assert validate_order(buy(), state, V2).broke(Rule.MAX_SECTOR_POSITIONS)


def test_v2_top_up_of_existing_position_skips_sector_cap():
    tech = "Information Technology"
    state = portfolio(positions=(pos("AMD", tech, "500"), pos("NVDA", tech)))
    assert validate_order(buy(qty=Decimal("5")), state, V2).approved


# --- v2 universe and cooldown -----------------------------------------------

def test_v2_refuses_sector_etfs_as_active_positions():
    for etf in sorted(SECTOR_ETFS):
        result = validate_order(buy(symbol=etf, sector="Any"), portfolio(), V2)
        assert result.broke(Rule.UNIVERSE), etf
    assert not validate_order(buy(), portfolio(), V2).broke(Rule.UNIVERSE)


def test_v2_cooldown_refuses_named_symbol_only():
    state = portfolio(cooldown_symbols=frozenset({"amd"}))
    assert validate_order(buy(), state, V2).broke(Rule.REENTRY_COOLDOWN)
    assert validate_order(buy(symbol="MU"), state, V2).approved


# --- v2 fallback -------------------------------------------------------------

def test_v2_fallback_is_exempt_from_slots_sector_and_weekly_count():
    tech = "Information Technology"
    full = portfolio(
        positions=tuple(pos(s, tech, "500") for s in ("A", "B", "C", "D", "E")),
        trades_this_week=3, cooldown_symbols=frozenset({"SPY"}))
    spy = buy(symbol="SPY", qty=Decimal("20"), price=Decimal("100"), sector=None)
    assert validate_order(spy, full, V2).approved


def test_v2_fallback_still_needs_cash_and_deployment_headroom():
    spy = buy(symbol="SPY", qty=Decimal("90"), price=Decimal("100"), sector=None)
    result = validate_order(spy, portfolio(cash=Decimal("8000")), V2)
    assert result.broke(Rule.SUFFICIENT_CASH) and result.broke(Rule.MAX_DEPLOYMENT_PCT)


def test_v2_fallback_position_does_not_occupy_an_active_slot():
    tech = "Information Technology"
    state = portfolio(positions=(pos("SPY", None, "3000"),) + tuple(
        pos(s, "Energy" if i % 2 else tech, "500") for i, s in enumerate("ABCD")))
    assert validate_order(buy(sector="Health Care"), state, V2).approved
    five = portfolio(positions=(pos("SPY", None),) + tuple(
        pos(s, "Energy" if i % 2 else tech, "500") for i, s in enumerate("ABCDE")))
    assert validate_order(buy(sector="Health Care"), five, V2).broke(Rule.MAX_POSITIONS)


# --- shared helpers take params ----------------------------------------------

def test_stop_change_and_sizing_take_params():
    assert validate_stop_change("90", "97.5", "100", V2).broke(Rule.STOP_DISTANCE)
    assert validate_stop_change("90", "96", "100", V2).approved
    assert max_affordable_shares(portfolio(), "100", params=V2) == 20
