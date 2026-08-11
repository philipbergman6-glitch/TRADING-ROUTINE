"""Every mechanised rule, proved in both directions.

A rule with only a happy-path test has not been demonstrated -- it may simply
never fire. So each rule gets a pair: one order that passes it and one that
breaks it, differing only in the quantity under test.
"""

from decimal import Decimal

import pytest

from risk_engine import (
    MAX_POSITIONS,
    UNMECHANISED,
    OrderProposal,
    PortfolioState,
    Position,
    Rule,
    Side,
    max_affordable_shares,
    required_trail_percent,
    validate_order,
    validate_stop_change,
)

EQUITY = Decimal("100000")


def portfolio(**overrides) -> PortfolioState:
    defaults = dict(
        equity=EQUITY,
        cash=Decimal("100000"),
        is_paper=True,
        positions=(),
        trades_this_week=0,
    )
    return PortfolioState(**{**defaults, **overrides})


def buy(**overrides) -> OrderProposal:
    """A well-formed, rule-abiding buy: 100 shares at $100 = 10% of equity."""
    defaults = dict(
        symbol="AAPL",
        qty=Decimal("100"),
        side=Side.BUY,
        price=Decimal("100"),
        trail_percent=Decimal("10"),
    )
    return OrderProposal(**{**defaults, **overrides})


def positions(count: int, value: str = "1000") -> tuple[Position, ...]:
    return tuple(
        Position(symbol=f"SYM{i}", qty=Decimal("1"), market_value=Decimal(value))
        for i in range(count)
    )


def test_a_clean_order_is_approved():
    result = validate_order(buy(), portfolio())
    assert result.approved, result.reasons()
    assert bool(result) is True


# --- Rule: paper account only ----------------------------------------------


def test_paper_account_passes():
    assert not validate_order(buy(), portfolio(is_paper=True)).broke(
        Rule.PAPER_ACCOUNT_ONLY
    )


def test_live_account_is_refused():
    result = validate_order(buy(), portfolio(is_paper=False))
    assert not result
    assert result.broke(Rule.PAPER_ACCOUNT_ONLY)


def test_live_account_is_refused_for_sells_too():
    """The account-mode boundary is not a position-sizing concern."""
    held = (Position("AAPL", Decimal("100"), Decimal("10000")),)
    result = validate_order(
        buy(side=Side.SELL, trail_percent=None), portfolio(is_paper=False, positions=held)
    )
    assert result.broke(Rule.PAPER_ACCOUNT_ONLY)


# --- Rule 1: stocks only ----------------------------------------------------


def test_equity_symbol_passes_stocks_only():
    assert not validate_order(buy(symbol="AAPL"), portfolio()).broke(Rule.STOCKS_ONLY)


def test_option_contract_symbol_is_refused():
    result = validate_order(buy(symbol="AAPL260116C00150000"), portfolio())
    assert not result
    assert result.broke(Rule.STOCKS_ONLY)


# --- Rule 3a: max 6 positions ----------------------------------------------


def test_sixth_position_is_allowed():
    result = validate_order(buy(), portfolio(positions=positions(MAX_POSITIONS - 1)))
    assert not result.broke(Rule.MAX_POSITIONS)


def test_seventh_position_is_refused():
    result = validate_order(buy(), portfolio(positions=positions(MAX_POSITIONS)))
    assert not result
    assert result.broke(Rule.MAX_POSITIONS)


def test_adding_to_an_existing_position_does_not_open_a_slot():
    held = positions(MAX_POSITIONS)
    topping_up = buy(symbol=held[0].symbol)
    assert not validate_order(topping_up, portfolio(positions=held)).broke(
        Rule.MAX_POSITIONS
    )


# --- Rule 3b: max 20% per position ------------------------------------------


def test_position_at_the_20pct_cap_is_allowed():
    result = validate_order(buy(qty=Decimal("200")), portfolio())  # exactly 20%
    assert not result.broke(Rule.MAX_POSITION_PCT)


def test_position_over_20pct_is_refused():
    result = validate_order(buy(qty=Decimal("201")), portfolio())
    assert not result
    assert result.broke(Rule.MAX_POSITION_PCT)


def test_cap_is_measured_on_the_resulting_position_not_the_order():
    """Topping up a 15% holding by 10% breaks the cap even though 10% < 20%."""
    held = (Position("AAPL", Decimal("150"), Decimal("15000")),)
    result = validate_order(buy(qty=Decimal("100")), portfolio(positions=held))
    assert result.broke(Rule.MAX_POSITION_PCT)


# --- Rule 8: max 3 new trades per week --------------------------------------


def test_third_trade_of_the_week_is_allowed():
    assert not validate_order(buy(), portfolio(trades_this_week=2)).broke(
        Rule.MAX_TRADES_PER_WEEK
    )


def test_fourth_trade_of_the_week_is_refused():
    result = validate_order(buy(), portfolio(trades_this_week=3))
    assert not result
    assert result.broke(Rule.MAX_TRADES_PER_WEEK)


# --- Cash --------------------------------------------------------------------


def test_order_within_cash_is_allowed():
    assert not validate_order(buy(), portfolio(cash=Decimal("10000"))).broke(
        Rule.SUFFICIENT_CASH
    )


def test_order_exceeding_cash_is_refused():
    result = validate_order(buy(), portfolio(cash=Decimal("9999")))
    assert not result
    assert result.broke(Rule.SUFFICIENT_CASH)


# --- Rule 2: deployment ceiling ---------------------------------------------


def test_deployment_at_the_ceiling_is_allowed():
    held = positions(1, value="75000")
    result = validate_order(buy(), portfolio(positions=held))  # 75% + 10% = 85%
    assert not result.broke(Rule.MAX_DEPLOYMENT_PCT)


def test_deployment_over_the_ceiling_is_refused():
    held = positions(1, value="76000")
    result = validate_order(buy(), portfolio(positions=held))  # 76% + 10% = 86%
    assert not result
    assert result.broke(Rule.MAX_DEPLOYMENT_PCT)


# --- Rule 4: every buy carries its stop -------------------------------------


def test_buy_with_a_trailing_stop_is_allowed():
    assert not validate_order(buy(trail_percent=Decimal("10")), portfolio()).broke(
        Rule.STOP_REQUIRED
    )


def test_buy_with_a_fixed_stop_is_allowed():
    order = buy(trail_percent=None, stop_price=Decimal("90"))
    assert not validate_order(order, portfolio()).broke(Rule.STOP_REQUIRED)


def test_unprotected_buy_is_refused():
    """The structural fix for buy-then-hope-the-stop-lands."""
    result = validate_order(buy(trail_percent=None), portfolio())
    assert not result
    assert result.broke(Rule.STOP_REQUIRED)


# --- Rule 7: stop distance ---------------------------------------------------


def test_stop_outside_3pct_is_allowed():
    order = buy(trail_percent=None, stop_price=Decimal("96"))  # 4% away
    assert not validate_order(order, portfolio()).broke(Rule.STOP_DISTANCE)


def test_stop_inside_3pct_is_refused():
    order = buy(trail_percent=None, stop_price=Decimal("98"))  # 2% away
    result = validate_order(order, portfolio())
    assert not result
    assert result.broke(Rule.STOP_DISTANCE)


def test_stop_above_entry_is_refused():
    order = buy(trail_percent=None, stop_price=Decimal("101"))
    assert validate_order(order, portfolio()).broke(Rule.STOP_DISTANCE)


def test_trail_tighter_than_3pct_is_refused():
    result = validate_order(buy(trail_percent=Decimal("2")), portfolio())
    assert result.broke(Rule.STOP_DISTANCE)


# --- Rule 7: a stop never moves down ----------------------------------------


def test_raising_a_stop_is_allowed():
    assert validate_stop_change(current_stop="90", new_stop="95", current_price="110")


def test_holding_a_stop_is_allowed():
    assert validate_stop_change(current_stop="90", new_stop="90", current_price="110")


def test_lowering_a_stop_is_refused():
    result = validate_stop_change(current_stop="95", new_stop="90", current_price="110")
    assert not result
    assert result.broke(Rule.STOP_NEVER_LOWERED)


def test_raising_a_stop_too_close_to_price_is_refused():
    result = validate_stop_change(current_stop="90", new_stop="109", current_price="110")
    assert result.broke(Rule.STOP_DISTANCE)


def test_stop_change_rejects_nonsense_price():
    with pytest.raises(ValueError):
        validate_stop_change(current_stop="90", new_stop="95", current_price="0")


# --- Rule 6: the trail ladder ------------------------------------------------


@pytest.mark.parametrize(
    "gain,expected",
    [
        ("0", "10"),
        ("14.99", "10"),
        ("15", "7"),
        ("19.99", "7"),
        ("20", "5"),
        ("150", "5"),
        ("-5", "10"),
    ],
)
def test_trail_ladder(gain, expected):
    assert required_trail_percent(gain) == Decimal(expected)


# --- Sizing ------------------------------------------------------------------


def test_max_affordable_shares_respects_the_20pct_cap():
    assert max_affordable_shares(portfolio(), price="100") == 200


def test_max_affordable_shares_respects_cash():
    assert max_affordable_shares(portfolio(cash=Decimal("5000")), price="100") == 50


def test_max_affordable_shares_respects_existing_holding():
    held = (Position("AAPL", Decimal("150"), Decimal("15000")),)
    assert max_affordable_shares(portfolio(positions=held), price="100", symbol="AAPL") == 50


def test_max_affordable_shares_is_zero_when_fully_deployed():
    held = positions(1, value="85000")
    assert max_affordable_shares(portfolio(positions=held), price="100") == 0


def test_sizing_output_always_validates():
    """The engine cannot recommend a size it would then refuse."""
    state = portfolio()
    qty = max_affordable_shares(state, price="100", symbol="AAPL")
    assert validate_order(buy(qty=Decimal(qty)), state).approved


# --- Selling -----------------------------------------------------------------


def test_selling_a_held_position_is_allowed():
    held = (Position("AAPL", Decimal("100"), Decimal("10000")),)
    order = buy(side=Side.SELL, trail_percent=None)
    assert validate_order(order, portfolio(positions=held)).approved


def test_selling_more_than_held_is_refused():
    held = (Position("AAPL", Decimal("50"), Decimal("5000")),)
    order = buy(side=Side.SELL, trail_percent=None)
    assert not validate_order(order, portfolio(positions=held))


def test_selling_a_position_you_do_not_have_is_refused():
    order = buy(side=Side.SELL, trail_percent=None)
    assert not validate_order(order, portfolio())


def test_sells_need_no_stop():
    """Sells reduce risk, so the protection rule must not fire on them."""
    held = (Position("AAPL", Decimal("100"), Decimal("10000")),)
    order = buy(side=Side.SELL, trail_percent=None)
    assert not validate_order(order, portfolio(positions=held)).broke(Rule.STOP_REQUIRED)


# --- Input handling: hard-fail, never silently pass -------------------------


def test_float_money_is_refused_outright():
    """Accepting 0.1 as a float is the silent rounding bug this prevents."""
    with pytest.raises(TypeError):
        buy(price=100.5)


def test_zero_quantity_is_refused():
    with pytest.raises(ValueError):
        buy(qty=Decimal("0"))


def test_negative_quantity_is_refused():
    with pytest.raises(ValueError):
        buy(qty=Decimal("-10"))


def test_fractional_shares_are_refused():
    with pytest.raises(ValueError):
        buy(qty=Decimal("10.5"))


def test_empty_symbol_is_refused():
    with pytest.raises(ValueError):
        buy(symbol="   ")


def test_symbol_is_normalised():
    assert buy(symbol=" aapl ").symbol == "AAPL"


def test_account_mode_must_be_explicit():
    """No convenient default: a caller that forgets must fail loudly."""
    with pytest.raises(TypeError):
        portfolio(is_paper="yes")


def test_zero_equity_is_refused():
    with pytest.raises(ValueError):
        portfolio(equity=Decimal("0"))


def test_validate_order_rejects_wrong_types():
    with pytest.raises(TypeError):
        validate_order("not an order", portfolio())
    with pytest.raises(TypeError):
        validate_order(buy(), "not a portfolio")


# --- The refusal must be legible --------------------------------------------


def test_every_violated_rule_is_reported_not_just_the_first():
    result = validate_order(
        buy(qty=Decimal("500"), trail_percent=None),  # oversized AND unprotected
        portfolio(trades_this_week=5, cash=Decimal("1000")),
    )
    broken = {v.rule for v in result.violations}
    assert Rule.MAX_POSITION_PCT in broken
    assert Rule.MAX_TRADES_PER_WEEK in broken
    assert Rule.SUFFICIENT_CASH in broken
    assert Rule.STOP_REQUIRED in broken
    assert len(result.reasons()) == len(result.violations)


def test_unmechanised_rules_are_documented_not_dropped():
    """The rules left to human judgment are named on purpose."""
    assert "sector_momentum" in UNMECHANISED
    assert "sector_exit_after_two_failures" in UNMECHANISED
    assert all(len(reason) > 20 for reason in UNMECHANISED.values())
