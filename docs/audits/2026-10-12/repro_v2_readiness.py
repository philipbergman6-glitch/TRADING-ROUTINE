"""Offline audit probes: eight expected failures at baseline 73da017.

Explicitly run with pytest; excluded from the normal tests/ collection.
These assert desired behavior and make no real broker calls. The version
probe deliberately checks the baseline's v1.1 rulebook against a v2 monitor.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datetime import datetime, timezone
from unittest.mock import patch
import json
import pytest
from risk_engine import V2, OrderProposal, PortfolioState, validate_order
from scripts import validate_order as vo, blotter as bl, validate_mutation as vm
from scripts.close_position import close_position, close_client_id
from scripts.replace_stop import Outcome
NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)

def fills_read(*args):
    assert args[0] == 'activities'
    rows = [dict(id='entry', transaction_time='2026-08-01T15:00:00Z', symbol='AMD', side='buy', qty='10', price='100', order_id='b'),
            dict(id='exit', transaction_time='2026-10-09T15:00:00Z', symbol='AMD', side='sell', qty='10', price='93', order_id='s')]
    return [r for r in rows if not args[1] or r['transaction_time'] > args[1]]

def test_long_held_exit_does_not_break_cooldown():
    original = bl.blotter_from_broker
    with patch.object(bl, 'blotter_from_broker', side_effect=lambda **kw: original(read=fills_read, **kw)):
        assert vo.cooldown_from_fills(NOW, V2) == frozenset({'AMD'})

def test_long_held_exit_does_not_block_unrelated_protection_cancel():
    original = bl.blotter_from_broker
    def read(*args):
        if args[0]=='account': return {'equity':'10000', 'cash':'9000'}
        if args[0]=='positions': return [{'symbol':'MSFT','qty':'10','market_value':'1000'}]
        if args[0]=='orders': return []
        if args[0]=='asset': return {'symbol':'MSFT','class':'us_equity'}
        if args[0]=='order-info': return {'id':'stop-msft','symbol':'MSFT','status':'new','side':'sell'}
        raise AssertionError(args)
    with patch.object(bl, 'blotter_from_broker', side_effect=lambda **kw: original(read=fills_read, **kw)), patch.object(vo,'adapter', side_effect=read):
        vm.validate_mutation('cancel','stop-msft',read=read,now=NOW,params=V2)

def test_fallback_buys_do_not_consume_active_weekly_count():
    def read(*args):
        if args[0]=='account': return {'equity':'10000','cash':'10000'}
        if args[0]=='positions': return []
        if args[0]=='orders': return [{'symbol':'SPY','side':'buy','filled_at':'2026-10-12T14:00:00Z'} for _ in range(3)]
        raise AssertionError(args)
    with patch.object(vo,'adapter',side_effect=read), patch.object(vo,'cooldown_from_fills',return_value=frozenset()):
        state=vo.read_portfolio(NOW,None,V2)
    result=validate_order(OrderProposal(symbol='AMD',qty='1',side='buy',price='100',stop_price='93',sector='Information Technology'),state,V2)
    assert result.approved, result.reasons()

@pytest.mark.parametrize('symbol,price,stop',[('VTI','100','93'),('AMD','600','558'),('AMD','5','4.65')])
def test_v2_rejects_excluded_universe(symbol,price,stop):
    state=PortfolioState(equity='10000',cash='10000',is_paper=True)
    result=validate_order(OrderProposal(symbol=symbol,qty='1',side='buy',price=price,stop_price=stop,sector='Information Technology'),state,V2)
    assert not result.approved, f'{symbol} at {price} approved'

def test_filled_prior_close_does_not_hide_a_new_same_day_position():
    calls=[]
    def read(*args):
        calls.append(args)
        if args[0]=='order-by-client': return {'id':'old-close','status':'filled','symbol':'AMD','qty':'10'}
        if args[0]=='positions': return [{'symbol':'AMD','qty':'5','market_value':'500'}]
        if args[0]=='orders': return []
        raise AssertionError(args)
    with pytest.raises(Outcome) as got:
        close_position('AMD',NOW,read=read,run=lambda *a: (_ for _ in ()).throw(AssertionError('no broker mutation permitted')),check=lambda *a:None)
    assert got.value.state != 'already_closed', {'state':got.value.state,'reads':calls}

def test_monitor_refuses_v2_when_repository_rulebook_is_v1():
    from scripts import protection_monitor as monitor
    from scripts.strategy_version import check, STRATEGY_FILE, PINS_FILE
    pins=json.loads(PINS_FILE.read_text())
    assert check(STRATEGY_FILE.read_text(), {'STRATEGY_VERSION':'v2'}, pins)[0] == 5
    with patch.dict(monitor.os.environ, {'STRATEGY_VERSION':'v2'}), patch.object(sys,'argv',['protection_monitor.py','--dry-run']), patch.object(monitor,'adapter',return_value=[]):
        assert monitor.main() != 0
