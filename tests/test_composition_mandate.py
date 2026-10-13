"""Rule 14, the composition mandate, as an engine check (#105 decisions 3-5, #136).

While the book holds no single name (every open position and reservation is a
broad ETF, or the book is empty), the next new position must be a single name.
A broad ETF passes only with a composition waiver, and the waiver is recorded
on the verdict.
"""

from datetime import datetime, timezone
import json
import os

import pytest

from risk_engine import (
    BROAD_ETFS,
    V1,
    V2,
    OrderProposal,
    PortfolioState,
    Position,
    Reservation,
    Rule,
    StrategyParams,
    is_broad_etf,
    build_oto_entry,
    fixed_stop_at_distance,
    validate_order,
)
from scripts import coordinator
from scripts.replace_stop import Outcome
from scripts.strategy_version import bind
from scripts.submit_entry import submit_entry
from scripts.validate_mutation import validate_mutation
from tests.store_support import Broker, Clock, fresh_stores, intent_lines, make_origin, writer_store

WAIVER = "no single name passed the entry checklist (RESEARCH-LOG 2026-10-13)"


def book(*symbols, reservations=()):
    return PortfolioState(
        equity="100000", cash="100000", is_paper=True, reservations=tuple(reservations),
        positions=tuple(Position(symbol=s, qty="10", market_value="1000") for s in symbols),
    )


def buy(symbol, qty="50", stop="90"):
    return OrderProposal(symbol=symbol, qty=qty, side="buy", price="100", stop_price=stop)


def test_broad_etf_list_is_the_sector_funds_plus_index_trackers():
    assert {"XLK", "XLE", "XLRE", "SPY", "QQQ", "IWM", "DIA", "VTI"} <= BROAD_ETFS
    assert is_broad_etf("xlk") and not is_broad_etf("AAPL") and not is_broad_etf("GLD")


def test_all_etf_book_refuses_a_rule_12_fallback_etf_add():
    result = validate_order(buy("XLV"), book("XLK", "XLE", "XLI"))
    assert result.broke(Rule.COMPOSITION_MANDATE)
    assert "composition waiver" in " ".join(result.reasons())


def test_empty_book_refuses_a_broad_etf():
    assert validate_order(buy("SPY"), book()).broke(Rule.COMPOSITION_MANDATE)


def test_waiver_passes_and_is_recorded_on_the_approval():
    result = validate_order(buy("XLV"), book("XLK", "XLE"), composition_waiver=WAIVER)
    assert result.approved
    assert [w.rule for w in result.waived] == [Rule.COMPOSITION_MANDATE]
    assert WAIVER in result.waivers()[0]


def test_single_name_into_an_all_etf_book_is_approved_without_a_waiver():
    result = validate_order(buy("AAPL"), book("XLK", "XLE"))
    assert result.approved and result.waived == ()


def test_etf_with_a_single_name_held_is_approved_without_a_waiver():
    result = validate_order(buy("XLV"), book("XLK", "AAPL"))
    assert result.approved and result.waived == ()


def test_reserved_single_name_lifts_the_mandate():
    pending = Reservation(intent_id="en-20261013-AAPL", symbol="AAPL", qty="10", price="100")
    assert validate_order(buy("XLV"), book("XLK", reservations=[pending])).approved


def test_reserved_etf_does_not_lift_the_mandate():
    pending = Reservation(intent_id="en-20261013-XLE", symbol="XLE", qty="10", price="100")
    assert validate_order(buy("XLV"), book(reservations=[pending])).broke(Rule.COMPOSITION_MANDATE)


def test_adding_to_a_held_etf_is_not_a_new_position():
    # Rule 14 governs "the next new position opened"; a top-up opens none.
    assert validate_order(buy("XLK"), book("XLK", "XLE")).approved


def test_unused_waiver_is_not_recorded():
    result = validate_order(buy("AAPL"), book(), composition_waiver=WAIVER)
    assert result.approved and result.waived == ()


def test_sells_are_never_constrained():
    sell = OrderProposal(symbol="XLK", qty="10", side="sell", price="100")
    assert validate_order(sell, book("XLK")).approved


def test_v2_has_no_composition_mandate():
    # v2 rule 9 makes sector ETFs ineligible anyway; its fallback SPY is a broad ETF.
    assert V1.composition_mandate is True and V2.composition_mandate is False
    result = validate_order(buy("SPY", stop="93"), book(), V2)
    assert result.approved and not result.broke(Rule.COMPOSITION_MANDATE)


@pytest.mark.parametrize("waiver,error", [
    ("", ValueError), ("   ", ValueError), (b"reason", TypeError), (1, TypeError),
])
def test_malformed_waiver_hard_fails(waiver, error):
    with pytest.raises(error, match="composition_waiver"):
        validate_order(buy("XLV"), book("XLK"), composition_waiver=waiver)


def test_malformed_mandate_flag_hard_fails():
    fields = {**V1.__dict__, "composition_mandate": "yes"}
    with pytest.raises(TypeError, match="composition_mandate"):
        StrategyParams(**fields)


def test_waiver_is_stripped_before_it_is_recorded():
    result = validate_order(buy("XLV"), book(), composition_waiver=f"  {WAIVER}\n")
    assert result.waived[0].detail.endswith(f"waiver: {WAIVER}")


def test_refusal_names_every_rule_including_the_mandate():
    result = validate_order(buy("XLV", qty="300"), book("XLK"))
    assert {v.rule for v in result.violations} >= {Rule.COMPOSITION_MANDATE, Rule.MAX_POSITION_PCT}


def test_waiver_never_waives_another_rule():
    result = validate_order(buy("XLV", qty="300"), book("XLK"), composition_waiver=WAIVER)
    assert not result.approved
    assert [v.rule for v in result.violations] == [Rule.MAX_POSITION_PCT]


# --- validate_order.py: --composition-waiver --------------------------------------

def run_cli(monkeypatch, capsys, *extra, positions=()):
    import scripts.validate_order as vo
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(vo, "read_portfolio", lambda *_a, **_k: book(*positions))
    monkeypatch.setattr("sys.argv", ["validate_order.py", "--symbol", "XLV", "--qty", "50", "--side", "buy",
                                     "--price", "100", "--stop-price", "90", "--json", *extra])
    code = vo.main()
    return code, json.loads(capsys.readouterr().out)


def test_cli_refuses_an_etf_into_an_all_etf_book_with_exit_3(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, positions=("XLK",))
    assert code == 3 and [v["rule"] for v in out["violations"]] == ["composition_mandate"]


def test_cli_waiver_approves_and_is_recorded(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, "--composition-waiver", WAIVER)
    assert code == 0 and out["approved"]
    assert out["composition_waiver"] == WAIVER
    assert [w["rule"] for w in out["waived"]] == ["composition_mandate"] and WAIVER in out["waived"][0]["detail"]


def test_cli_blank_waiver_is_a_usage_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as info:
        run_cli(monkeypatch, capsys, "--composition-waiver", "  ")
    assert info.value.code == 2


# --- the mutation gate and the coordinated entry ----------------------------------

NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)


class Market(Broker):
    def read(self, command, arg=None, *rest):
        if command == "asset":
            return {"symbol": arg, "class": "us_equity", "tradable": True, "status": "active"}
        if command == "quote":
            return {"quote": {"t": NOW.isoformat(), "ap": "100"}}
        return super().read(command, arg, *rest)


def gate(broker, body, **kw):
    """The exact-payload gate as alpaca.sh runs it: no reservations handed in."""
    return validate_mutation("order", json.dumps(body), read=broker.read, portfolio=book(), now=NOW,
                             binding=bind(os.environ), **kw)


def etf_oto(**changes):
    return {**build_oto_entry(symbol="XLV", qty="50", protection=fixed_stop_at_distance("100", "10")), **changes}


def test_gate_refuses_an_etf_buy_into_an_empty_book_without_a_waiver(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator, "open_store", fresh_stores(tmp_path))
    with pytest.raises(ValueError, match="composition_mandate"):
        gate(Market(), etf_oto(client_order_id="en-20261013-XLV"))


def test_gate_passes_with_a_waiver_from_the_caller():
    assert gate(Market(), etf_oto(), reservations=(), composition_waiver=WAIVER).symbol == "XLV"


def entry(store, broker, **kw):
    def check(command, argument, reservations=(), composition_waiver=None):
        return validate_mutation(command, argument, read=broker.read, portfolio=book(), now=NOW,
                                 binding=bind(os.environ), reservations=reservations,
                                 composition_waiver=composition_waiver)
    clock = Clock(NOW)
    with pytest.raises(Outcome) as info:
        submit_entry(etf_oto(), read=broker.read, run=broker.run, now=NOW, store=store, writer="market-open",
                     check=check, clock=clock, sleep=clock.sleep, fault=lambda _: None, **kw)
    return info.value


def test_coordinated_entry_records_the_waiver_and_the_alpaca_gate_reads_it(tmp_path, monkeypatch):
    origin = make_origin(tmp_path)
    store, broker = writer_store(tmp_path, origin, "a"), Market()
    got = entry(store, broker, composition_waiver=WAIVER)
    assert got.state == "submitted"
    recorded = intent_lines(origin, "en-20261013-XLV")[0]
    assert (recorded["state"], recorded["composition_waiver"]) == ("recorded", WAIVER)
    # alpaca.sh re-validates the exact body before its POST (no buy pending yet);
    # the waiver comes from the store.
    (tmp_path / "gate").mkdir()
    monkeypatch.setattr(coordinator, "open_store", lambda environ=None: writer_store(tmp_path / "gate", origin, "g"))
    assert gate(Market(), broker.posts[0]).symbol == "XLV"


def test_coordinated_entry_without_a_waiver_is_refused_and_recorded(tmp_path):
    origin = make_origin(tmp_path)
    got = entry(writer_store(tmp_path, origin, "a"), Market())
    assert (got.code, got.state) == (3, "refused")
    refused = intent_lines(origin, "en-20261013-XLV")
    assert [e["state"] for e in refused] == ["refused"] and "composition_mandate" in refused[0]["reasons"][0]


def test_an_etf_body_whose_intent_carries_no_waiver_cannot_slip_past_the_alpaca_gate(tmp_path, monkeypatch):
    origin = make_origin(tmp_path)
    store, broker = writer_store(tmp_path, origin, "a"), Market()
    assert entry(store, broker, composition_waiver=WAIVER).state == "submitted"
    (tmp_path / "gate").mkdir()
    monkeypatch.setattr(coordinator, "open_store", lambda environ=None: writer_store(tmp_path / "gate", origin, "g"))
    forged = {**broker.posts[0], "client_order_id": "en-20261013-XLV-b"}   # an intent never recorded
    with pytest.raises(ValueError, match="composition_mandate"):
        gate(Market(), forged)


def test_submit_entry_cli_rejects_a_blank_waiver(monkeypatch):
    from scripts import submit_entry as cli
    monkeypatch.setattr("sys.argv", ["submit_entry.py", "--symbol", "XLV", "--qty", "5", "--price", "100",
                                     "--composition-waiver", ""])
    with pytest.raises(SystemExit) as info:
        cli.main()
    assert info.value.code == 2


def test_submit_entry_rerun_command_keeps_the_waiver(monkeypatch, capsys):
    from scripts import submit_entry as cli

    def fake(b, intent=None, tag=None, binding=None, composition_waiver=None):
        assert composition_waiver == WAIVER
        raise Outcome(8, "submitted_outcome_unknown_rerun", intent="en-20261013-XLV")
    monkeypatch.setattr(cli, "submit_entry", fake)
    monkeypatch.setattr("sys.argv", ["submit_entry.py", "--symbol", "XLV", "--qty", "5", "--price", "100",
                                     "--composition-waiver", WAIVER])
    assert cli.main() == 8
    assert json.loads(capsys.readouterr().out)["rerun"].endswith(f"--composition-waiver '{WAIVER}'")
