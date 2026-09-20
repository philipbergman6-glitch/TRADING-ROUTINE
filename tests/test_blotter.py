"""Fill-based blotter: FIFO pairing, cooldown and sector streaks, all offline."""
from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from risk_engine.blotter import (build_blotter, cooldown_symbols, parse_fills,
                                 sector_failure_streaks, sessions_between)
from scripts import blotter as cli


def fill(i, t, sym, side, qty, price, order=None):
    return {"id": str(i), "activity_type": "FILL", "transaction_time": t, "symbol": sym,
            "side": side, "qty": str(qty), "price": str(price), "order_id": order or f"o{i}"}


FILLS = [
    fill(1, "2026-04-28T13:30:00Z", "AMD", "buy", 62, "314.97"),
    fill(2, "2026-04-28T13:31:00Z", "PLTR", "buy", 142, "142.30"),
    fill(3, "2026-05-06T15:00:00Z", "PLTR", "sell", 142, "132.33"),
    fill(4, "2026-05-06T18:00:00Z", "AMD", "sell", 62, "408.93"),
    fill(5, "2026-05-07T13:30:00Z", "AMD", "buy", 49, "414.16"),
    fill(6, "2026-05-18T14:00:00Z", "AMD", "sell", 20, "421.44"),  # partial exit
    fill(7, "2026-05-18T14:01:00Z", "AMD", "sell", 29, "421.44"),  # rest, same order
]
FILLS[6]["order_id"] = FILLS[5]["order_id"]


def test_fifo_round_trips_match_research_0006():
    b = build_blotter(parse_fills(FILLS))
    assert [(t.symbol, str(t.qty), str(t.pnl), str(t.pnl_pct)) for t in b.round_trips] == [
        ("PLTR", "142", "-1415.74", "-7.01"),
        ("AMD", "62", "5825.52", "29.83"),
        ("AMD", "49", "356.72", "1.76"),
    ]
    assert b.round_trips[2].exit_order_ids == ("o6",)
    assert b.open_lots == ()


def test_open_lots_and_partial_close_are_both_reported():
    b = build_blotter(parse_fills(FILLS[:5] + [fill(8, "2026-05-19T14:00:00Z", "AMD", "sell", 9, "430")]))
    assert [(o.symbol, str(o.qty), str(o.avg_in)) for o in b.open_lots] == [("AMD", "40", "414.1600")]
    assert [str(t.qty) for t in b.round_trips if t.symbol == "AMD"] == ["62", "9"]


def test_sell_without_lot_is_an_error_not_a_skip():
    with pytest.raises(ValueError, match="exceeds open lots"):
        build_blotter(parse_fills([fill(1, "2026-05-01T14:00:00Z", "F", "sell", 1, "12")]))


def test_missing_fields_and_non_fill_rows_are_rejected():
    bad = dict(FILLS[0]); del bad["price"]
    with pytest.raises(ValueError, match="missing"):
        parse_fills([bad])
    with pytest.raises(ValueError, match="not a FILL"):
        parse_fills([{**FILLS[0], "activity_type": "FEE"}])


def test_exclusion_drops_test_symbol_only():
    rows = FILLS + [fill(9, "2026-08-11T14:00:00Z", "F", "buy", 1, "12"),
                    fill(10, "2026-08-11T14:01:00Z", "F", "sell", 1, "11.92")]
    b = build_blotter(parse_fills(rows), frozenset({"F"}))
    assert {t.symbol for t in b.round_trips} == {"AMD", "PLTR"}


def test_sessions_between_counts_weekdays():
    assert sessions_between(date(2026, 5, 18), date(2026, 5, 18)) == 0   # Monday -> same day
    assert sessions_between(date(2026, 5, 15), date(2026, 5, 18)) == 1   # Fri -> Mon
    assert sessions_between(date(2026, 5, 18), date(2026, 6, 1)) == 10


def test_cooldown_uses_latest_exit_and_version_window():
    b = build_blotter(parse_fills(FILLS))
    assert cooldown_symbols(b, date(2026, 5, 29), 10) == frozenset({"AMD"})   # 9 sessions after May 18
    assert cooldown_symbols(b, date(2026, 6, 1), 10) == frozenset()            # 10 sessions: expired
    assert cooldown_symbols(b, date(2026, 5, 7), 10) == frozenset({"AMD", "PLTR"})
    assert cooldown_symbols(b, date(2026, 5, 7), 0) == frozenset()


def test_sector_streaks_reset_on_a_winner_and_require_every_sector():
    b = build_blotter(parse_fills(FILLS))
    tech = {"AMD": "Information Technology", "PLTR": "Information Technology"}
    assert sector_failure_streaks(b, tech) == {"Information Technology": 0}
    losers = build_blotter(parse_fills(FILLS[:4]))  # PLTR lost, then AMD won
    assert sector_failure_streaks(losers, tech) == {"Information Technology": 0}
    two = build_blotter(parse_fills([
        fill(1, "2026-06-03T13:30:00Z", "NVDA", "buy", 90, "219.64"),
        fill(2, "2026-06-03T13:31:00Z", "MSFT", "buy", 48, "436.20"),
        fill(3, "2026-06-09T14:00:00Z", "NVDA", "sell", 90, "199.37"),
        fill(4, "2026-06-09T15:00:00Z", "MSFT", "sell", 48, "401.09")]))
    assert sector_failure_streaks(two, {"NVDA": "IT", "MSFT": "IT"}) == {"IT": 2}
    with pytest.raises(ValueError, match="no sector recorded for MSFT"):
        sector_failure_streaks(two, {"NVDA": "IT"})


def test_fetch_pages_by_last_id_until_short_page():
    pages = {"": [fill(i, "2026-05-01T14:00:00Z", "AMD", "buy", 1, "1") for i in range(100)],
             "99": [fill(100, "2026-05-01T15:00:00Z", "AMD", "buy", 1, "1")]}
    calls = []

    def read(*args):
        calls.append(args)
        return pages[args[2] if len(args) > 2 else ""]

    rows = cli.fetch_fills(read)
    assert len(rows) == 101 and calls == [("activities", ""), ("activities", "", "99")]


def test_check_positions_reports_every_quantity_difference():
    b = build_blotter(parse_fills(FILLS[:5]))
    assert cli.check_positions(b, [{"symbol": "AMD", "qty": "49"}]) == []
    issues = cli.check_positions(b, [{"symbol": "AMD", "qty": "48"}, {"symbol": "XLB", "qty": "412"}])
    assert issues == ["AMD: broker holds 48, fills imply 49", "XLB: broker holds 412, fills imply 0"]


def test_json_and_markdown_render(tmp_path):
    b = build_blotter(parse_fills(FILLS))
    out = cli.to_json(b)
    assert out["round_trips"][1]["pnl"] == "5825.52" and out["open_lots"] == []
    md = cli.to_markdown(b)
    assert "| AMD | 04-28 | 05-06 | 62 | 314.97 | 408.93 | +5,825.52 | +29.83 |" in md
    sectors = tmp_path / "SECTORS.json"
    sectors.write_text(json.dumps({"_note": "x", "amd": "IT"}))
    assert cli.load_sectors(sectors) == {"AMD": "IT"}
