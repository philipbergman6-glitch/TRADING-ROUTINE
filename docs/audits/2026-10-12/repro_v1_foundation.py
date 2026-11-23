"""V1 scope validation; expected baseline: two passes and two failures.

Offline only. Run explicitly with pytest from the repository root.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from risk_engine import V1, OrderProposal, PortfolioState, validate_order
from scripts.validate_order import cooldown_from_fills
from scripts.close_position import close_position
from scripts.replace_stop import Outcome, EXIT_UNPROTECTED

NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)


def test_v1_does_not_read_v2_cooldown_history():
    with patch('scripts.blotter.blotter_from_broker', side_effect=AssertionError('must not read history')):
        assert cooldown_from_fills(NOW, V1) == frozenset()


def test_v1_does_not_have_v2_universe_price_restriction():
    result = validate_order(
        OrderProposal(symbol='AMD', qty='1', side='buy', price='600', stop_price='540'),
        PortfolioState(equity='10000', cash='10000', is_paper=True), V1)
    assert result.approved


def test_new_same_day_position_is_not_reported_closed_from_old_exit():
    def read(command, *args):
        if command == 'order-by-client':
            return {'id': 'earlier-exit', 'status': 'filled', 'symbol': 'AMD', 'qty': '10'}
        if command == 'positions':
            return [{'symbol': 'AMD', 'qty': '5', 'market_value': '500'}]
        if command == 'orders':
            return []
        raise AssertionError(command)
    with pytest.raises(Outcome) as got:
        close_position('AMD', NOW, read=read)
    assert got.value.state != 'already_closed'


def test_resumed_unprotected_close_refusal_is_still_an_incident():
    # Prior process canceled the stop and died; the resumed preflight refuses.
    def read(command, *args):
        if command == 'order-by-client':
            return None
        if command == 'positions':
            return [{'symbol': 'AMD', 'qty': '5', 'market_value': '500'}]
        if command == 'orders':
            return []
        raise AssertionError(command)
    def check(*args):
        raise ValueError('temporary preflight refusal')
    with pytest.raises(Outcome) as got:
        close_position('AMD', NOW, read=read, check=check)
    assert got.value.code == EXIT_UNPROTECTED, (got.value.code, got.value.state)
