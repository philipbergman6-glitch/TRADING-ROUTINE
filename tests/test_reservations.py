"""Reservations: capacity an unfinished entry intent holds (ADR 0010 §6).

Each rule that counts reservations gets a pair: the same order is approved
without the reservation and refused with it, so the test proves the
reservation is what flipped the verdict.
"""

from decimal import Decimal

import pytest

from risk_engine import (
    V2,
    OrderProposal,
    PortfolioState,
    Position,
    Reservation,
    Rule,
    Side,
    max_affordable_shares,
    validate_order,
)
from risk_engine.protection import fixed_stop_at_distance

EQUITY = Decimal("100000")


def portfolio(**overrides) -> PortfolioState:
    defaults = dict(
        equity=EQUITY,
        cash=Decimal("100000"),
        is_paper=True,
        reservations=(),
        positions=(),
        trades_this_week=0,
    )
    return PortfolioState(**{**defaults, **overrides})


def reservation(**overrides) -> Reservation:
    """1 share of MSFT at $100, reserved by intent i-1."""
    defaults = dict(intent_id="i-1", symbol="MSFT", qty="1", price="100", sector=None)
    return Reservation(**{**defaults, **overrides})


def buy(**overrides) -> OrderProposal:
    """100 shares of AAPL at $100 = 10% of equity, with the v1 entry trail."""
    defaults = dict(
        symbol="AAPL", qty=Decimal("100"), side=Side.BUY, price=Decimal("100"),
        trail_percent=Decimal("10"),
    )
    return OrderProposal(**{**defaults, **overrides})


def held(count: int, value: str = "1000") -> tuple[Position, ...]:
    return tuple(
        Position(symbol=f"SYM{i}", qty=Decimal("1"), market_value=Decimal(value))
        for i in range(count)
    )


# --- The boundary ------------------------------------------------------------


def test_portfolio_state_without_reservations_fails_loudly():
    with pytest.raises(TypeError):
        PortfolioState(equity=EQUITY, cash=EQUITY, is_paper=True)


def test_reservation_money_is_decimal_and_symbol_is_cleaned():
    r = reservation(symbol=" msft ", qty="3", price="12.50")
    assert (r.symbol, r.qty, r.price, r.notional) == (
        "MSFT", Decimal("3"), Decimal("12.50"), Decimal("37.50"),
    )


@pytest.mark.parametrize("bad, error", [
    (dict(price=100.0), TypeError),
    (dict(qty=1.0), TypeError),
    (dict(qty="0"), ValueError),
    (dict(qty="-1"), ValueError),
    (dict(qty="1.5"), ValueError),
    (dict(price="0"), ValueError),
    (dict(intent_id=""), ValueError),
    (dict(intent_id=" "), ValueError),
    (dict(intent_id=7), TypeError),
    (dict(symbol=""), ValueError),
    (dict(sector=""), ValueError),
])
def test_malformed_reservation_is_refused_at_construction(bad, error):
    with pytest.raises(error):
        reservation(**bad)


@pytest.mark.parametrize("bad, error", [
    (None, TypeError),
    ("i-1", TypeError),
    (({"intent_id": "i-1", "symbol": "MSFT", "qty": "1", "price": "100"},), TypeError),
])
def test_reservations_must_be_reservation_objects(bad, error):
    with pytest.raises(error):
        portfolio(reservations=bad)


def test_one_intent_cannot_reserve_twice():
    with pytest.raises(ValueError, match="i-1"):
        portfolio(reservations=(reservation(), reservation(symbol="NVDA")))


def v2_buy(**overrides) -> OrderProposal:
    """A v2-abiding buy: 100 AMD at $100 (10% of equity), 7% fixed stop."""
    defaults = dict(symbol="AMD", qty=Decimal("100"), side=Side.BUY, price=Decimal("100"),
                    stop_price=Decimal("93"), sector="Information Technology")
    return OrderProposal(**{**defaults, **overrides})


def v2_held(count: int) -> tuple[Position, ...]:
    sectors = ("Energy", "Utilities", "Financials", "Health Care", "Materials")
    return tuple(
        Position(symbol=f"SYM{i}", qty=Decimal("1"), market_value=Decimal("1000"),
                 sector=sectors[i])
        for i in range(count)
    )


# --- Rule 3: position slots -------------------------------------------------


def test_a_reserved_new_symbol_takes_a_slot():
    five = held(5)
    assert validate_order(buy(), portfolio(positions=five))
    result = validate_order(buy(), portfolio(positions=five, reservations=(reservation(),)))
    assert result.broke(Rule.MAX_POSITIONS)
    assert "i-1" in " ".join(result.reasons())


def test_two_reservations_on_one_new_symbol_take_one_slot():
    four = held(4)
    both = (reservation(intent_id="i-1"), reservation(intent_id="i-2"))
    assert not validate_order(buy(), portfolio(positions=four, reservations=both)).broke(
        Rule.MAX_POSITIONS
    )
    one_more = both + (reservation(intent_id="i-3", symbol="NVDA"),)
    assert validate_order(buy(), portfolio(positions=four, reservations=one_more)).broke(
        Rule.MAX_POSITIONS
    )


def test_a_reservation_adding_to_a_held_symbol_takes_no_slot():
    five = held(5)
    adds = (reservation(symbol="SYM0"),)
    assert not validate_order(buy(), portfolio(positions=five, reservations=adds)).broke(
        Rule.MAX_POSITIONS
    )


def test_buying_a_reserved_symbol_opens_no_new_slot():
    """The slot is already taken by the reservation; a second buy shares it."""
    five = held(5)
    result = validate_order(
        buy(symbol="MSFT"), portfolio(positions=five, reservations=(reservation(),))
    )
    assert not result.broke(Rule.MAX_POSITIONS)


def test_a_fallback_reservation_takes_no_slot():
    four = v2_held(4)
    spy = (reservation(symbol="SPY"),)
    assert validate_order(v2_buy(), portfolio(positions=four), V2)
    assert not validate_order(v2_buy(), portfolio(positions=four, reservations=spy), V2).broke(
        Rule.MAX_POSITIONS
    )


# --- Rule 8: weekly trade count ---------------------------------------------


def test_a_reservation_takes_a_weekly_trade():
    assert validate_order(buy(), portfolio(trades_this_week=1, reservations=(reservation(),)))
    result = validate_order(buy(), portfolio(trades_this_week=2, reservations=(reservation(),)))
    assert result.broke(Rule.MAX_TRADES_PER_WEEK)
    assert "i-1" in " ".join(result.reasons())


def test_each_reserving_intent_is_its_own_weekly_trade():
    """trades_this_week counts filled buy orders, so each intent will add one."""
    both = (reservation(intent_id="i-1"), reservation(intent_id="i-2"))
    assert validate_order(buy(), portfolio(reservations=both))
    assert validate_order(buy(), portfolio(trades_this_week=1, reservations=both)).broke(
        Rule.MAX_TRADES_PER_WEEK
    )


def test_an_add_to_held_reservation_still_takes_a_weekly_trade():
    """The engine counts adds as trades, and the add's fill will be counted."""
    adds = (reservation(symbol="SYM0"),)
    result = validate_order(buy(), portfolio(positions=held(1), trades_this_week=2,
                                             reservations=adds))
    assert result.broke(Rule.MAX_TRADES_PER_WEEK)


def test_a_fallback_reservation_takes_no_weekly_trade():
    spy = (reservation(symbol="SPY"),)
    assert not validate_order(
        v2_buy(), portfolio(trades_this_week=2, reservations=spy), V2
    ).broke(Rule.MAX_TRADES_PER_WEEK)


# --- Rule 3: position size --------------------------------------------------


def test_reserved_notional_adds_to_the_symbols_resulting_position():
    """$10,000 buy + $10,100 reserved in the same name = 20.1% of equity."""
    same = (reservation(symbol="AAPL", qty="101"),)
    other = (reservation(symbol="MSFT", qty="101"),)
    assert not validate_order(buy(), portfolio(reservations=other)).broke(Rule.MAX_POSITION_PCT)
    result = validate_order(buy(), portfolio(reservations=same))
    assert result.broke(Rule.MAX_POSITION_PCT)
    assert "i-1" in " ".join(result.reasons())


# --- Rule 2: deployment ceiling ---------------------------------------------


def test_reserved_notional_counts_as_deployed():
    """$75,000 held + $10,000 buy is 85%; $100 more reserved tips it over."""
    state = dict(positions=held(5, "15000"), cash=Decimal("25000"))
    assert validate_order(buy(), portfolio(**state))
    result = validate_order(buy(), portfolio(**state, reservations=(reservation(symbol="SYM0"),)))
    assert result.broke(Rule.MAX_DEPLOYMENT_PCT)
    assert "i-1" in " ".join(result.reasons())


# --- Rule 13: cash ----------------------------------------------------------


def test_reserved_notional_is_not_available_cash():
    assert validate_order(buy(), portfolio(cash=Decimal("10000")))
    result = validate_order(buy(), portfolio(cash=Decimal("10000"),
                                             reservations=(reservation(),)))
    assert result.broke(Rule.SUFFICIENT_CASH)
    assert "i-1" in " ".join(result.reasons())


# --- The fallback is exempt from counts, never from money --------------------


def test_a_fallback_reservation_still_uses_cash_and_deployment():
    spy = (reservation(symbol="SPY", qty="751"),)  # $75,100 reserved
    result = validate_order(v2_buy(), portfolio(reservations=spy), V2)
    assert result.broke(Rule.MAX_DEPLOYMENT_PCT)
    tight = validate_order(v2_buy(), portfolio(cash=Decimal("10000"),
                                               reservations=(reservation(symbol="SPY"),)), V2)
    assert tight.broke(Rule.SUFFICIENT_CASH)


# --- v2 rule 3: sector cap --------------------------------------------------

IT = "Information Technology"


def test_a_reserved_new_symbol_counts_toward_its_sector():
    one_it = (Position(symbol="MSFT", qty=Decimal("1"), market_value=Decimal("1000"), sector=IT),)
    nvda = (reservation(symbol="NVDA", sector=IT),)
    assert validate_order(v2_buy(), portfolio(positions=one_it), V2)
    result = validate_order(v2_buy(), portfolio(positions=one_it, reservations=nvda), V2)
    assert result.broke(Rule.MAX_SECTOR_POSITIONS)
    assert "i-1" in " ".join(result.reasons())


def test_a_reserved_new_symbol_without_a_sector_cannot_be_counted():
    result = validate_order(v2_buy(), portfolio(reservations=(reservation(symbol="NVDA"),)), V2)
    assert result.broke(Rule.MAX_SECTOR_POSITIONS)
    assert "i-1" in " ".join(result.reasons())


def test_an_add_to_held_reservation_is_not_counted_twice_in_its_sector():
    one_it = (Position(symbol="MSFT", qty=Decimal("1"), market_value=Decimal("1000"), sector=IT),)
    adds = (reservation(symbol="MSFT", sector=IT),)
    assert not validate_order(v2_buy(), portfolio(positions=one_it, reservations=adds), V2).broke(
        Rule.MAX_SECTOR_POSITIONS
    )


# --- Sizing uses the same view ----------------------------------------------


def test_max_affordable_shares_leaves_reserved_cash_alone():
    state = dict(cash=Decimal("10000"))
    assert max_affordable_shares(portfolio(**state), "100", "AAPL") == 100
    reserved = (reservation(qty="50"),)  # $5,000 reserved in MSFT
    assert max_affordable_shares(portfolio(**state, reservations=reserved), "100", "AAPL") == 50


def test_max_affordable_shares_counts_reserved_shares_in_the_same_name():
    reserved = (reservation(symbol="AAPL", qty="50"),)  # 20% cap $20,000 less $5,000
    assert max_affordable_shares(portfolio(reservations=reserved), "100", "AAPL") == 150


def test_max_affordable_shares_counts_reservations_as_deployed():
    state = dict(positions=held(5, "15000"), cash=Decimal("25000"))  # 85% cap leaves $10,000
    reserved = (reservation(symbol="SYM0", qty="50"),)
    assert max_affordable_shares(portfolio(**state, reservations=reserved), "100", "AAPL") == 50
