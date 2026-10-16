"""Golden and hard-fail tests for scripts/build_brain_index.py (map #169, ticket #174).

The brain index joins the committed record per symbol and per UTC date. It
must reproduce docs/brain/index.json exactly, and it must refuse to publish
when any input is unrecognised, instead of emitting a partial index.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "build_brain_index", REPO / "scripts" / "build_brain_index.py")
bi = importlib.util.module_from_spec(spec)
sys.modules["build_brain_index"] = bi
spec.loader.exec_module(bi)


@pytest.fixture(scope="module")
def built():
    return bi.build()


# ---------------------------------------------------------------- golden

@pytest.mark.golden
def test_golden_reproduces_committed_index_json(built):
    assert bi.render_json(built) == bi.OUT_JSON.read_text(encoding="utf-8"), (
        "regenerated index.json differs from committed docs/brain/index.json — "
        "run scripts/build_brain_index.py and commit, or fix the parser")


@pytest.mark.golden
def test_golden_reproduces_committed_index_md(built):
    assert bi.render_md(built) == bi.OUT_MD.read_text(encoding="utf-8")


def test_json_is_deterministic_and_sorted(built):
    once, twice = bi.render_json(built), bi.render_json(bi.build())
    assert once == twice
    data = json.loads(once)
    assert list(data) == sorted(data)
    assert once.endswith("\n")


# ---------------------------------------------------------- entry headers

def test_entry_header_forms_are_recognised():
    parse = bi.parse_entry_header
    assert parse("## 2026-10-15 — Pre-market Research", "research")[:3] == (
        "2026-10-15", "pre-market-research", "Pre-market Research")
    assert parse("### Sep 9 — EOD Snapshot (Day 96, Wednesday)", "trade")[:2] == (
        "2026-09-09", "eod-snapshot")
    assert parse("## Day 0 — EOD Snapshot", "trade")[0] == bi.DAY0_DATE
    d, kind, title, note = parse(
        "## 2026-09-17 — Pre-Market Research — FOMC DECISION DAY", "research")
    assert (d, kind, note) == ("2026-09-17", "pre-market-research", "FOMC DECISION DAY")
    assert parse("### Decision", "research") is None
    assert parse("### May 21 Execution Note", "research") is None


def test_hard_fails_on_unknown_entry_kind():
    with pytest.raises(bi.ParseError, match="unknown trade-log entry kind"):
        bi.parse_entry_header("## 2026-10-15 — Lunch Snapshot", "trade")


def test_hard_fails_on_unknown_research_kind():
    with pytest.raises(bi.ParseError, match="unknown research-log entry kind"):
        bi.parse_entry_header("## 2026-10-15 — Evening Musings", "research")


def test_hard_fails_on_a_subsection_before_any_entry():
    with pytest.raises(bi.ParseError, match="before the first dated entry"):
        bi.parse_log("# Trade Log\n\n### Actions\n- none\n", "trade", symbols={"AMD"})


def test_hard_fails_on_a_top_level_header_that_is_not_an_entry():
    text = "# Trade Log\n\n## 2026-10-01 — Midday Scan\nx\n\n## Random notes\ny\n"
    with pytest.raises(bi.ParseError, match="not a dated entry"):
        bi.parse_log(text, "trade", symbols={"AMD"})


def test_entries_carry_line_symbols_and_sections():
    text = ("# Research Log\n\n## 2026-10-01 — Pre-market Research\n\n"
            "### Trade Ideas\n- AMD looks strong; MU weak\n\n### Decision\nBuy AMD.\n\n"
            "## 2026-10-02 — Midday Scan\n\nHold MU.\n")
    entries = bi.parse_log(text, "research", symbols={"AMD", "MU", "F"})
    assert [e["line"] for e in entries] == [3, 11]
    first = entries[0]
    assert first["id"] == "research/2026-10-01/pre-market-research/1"
    assert first["symbols"] == ["AMD", "MU"]
    assert first["ideas"] == ["AMD", "MU"]
    assert first["decision"] == ["AMD"]
    assert first["decision_text"] == "Buy AMD."
    assert entries[1]["symbols"] == ["MU"]


def test_same_day_same_kind_entries_get_a_sequence():
    text = ("## 2026-10-01 — Midday Scan\na\n\n## 2026-10-01 — Midday Scan\nb\n")
    ids = [e["id"] for e in bi.parse_log(text, "trade", symbols=set())]
    assert ids == ["trade/2026-10-01/midday-scan/1", "trade/2026-10-01/midday-scan/2"]


def test_engineering_test_symbol_is_never_mentioned():
    text = "## 2026-10-01 — Midday Scan\nF filled as a test; AMD held.\n"
    (entry,) = bi.parse_log(text, "trade", symbols={"AMD", "F"})
    assert entry["symbols"] == ["AMD"]


# ----------------------------------------------------------- weekly review

def test_weeks_cover_their_seven_days(built):
    weeks = built["weeks"]
    assert weeks["2026-05-01"]["grade"]
    assert bi.week_for("2026-04-27", weeks) == "2026-05-01"
    assert bi.week_for("2026-05-01", weeks) == "2026-05-01"
    assert bi.week_for("2026-05-02", weeks) == "2026-05-08"


def test_hard_fails_on_a_week_without_a_grade():
    text = "## Week ending 2026-05-01\n\n### Stats\nx\n\n### Closed Trades\nAMD\n"
    with pytest.raises(bi.ParseError, match="no 'Overall Grade'"):
        bi.parse_weeks(text, symbols={"AMD"})


# --------------------------------------------------------- blotter + state

def test_lifecycles_exclude_test_fills_and_carry_sectors(built):
    syms = built["symbols"]
    assert "F" not in syms
    for s, rec in syms.items():
        if rec["round_trips"] or rec["open_lots"]:
            assert rec["sector"], s


def test_hard_fails_on_traded_symbol_without_sector():
    blotter = {"round_trips": [], "open_lots": [{
        "symbol": "ZZZ", "entered": "2026-10-01T13:30:00+00:00", "qty": "1",
        "avg_in": "1.00", "entry_order_ids": ["x"]}]}
    with pytest.raises(bi.ParseError, match="ZZZ traded but missing"):
        bi.index_blotter(blotter, {"AMD": "Information Technology"})


def test_refusals_are_listed_with_symbol_and_month(built):
    refusals = built["refusals"]
    assert refusals, "the record holds refusals since 2026-10-12"
    for r in refusals:
        assert set(r) >= {"at", "run", "routine", "text", "symbol"}
    assert bi.query_refusals(built, "2026-10")


def test_runs_are_cut_off_at_the_latest_eod_log_date(built):
    asof = built["generated_from"]["trade_log_asof"]
    for run in built["runs"].values():
        assert run["started_at"][:10] < asof


def test_hard_fails_on_a_malformed_run_record(built, monkeypatch):
    bad = {"id": "deadbeef" * 4, "kind": "run", "at": "2026-10-12T00:00:00+00:00",
           "writer": "w", "schema": 1, "op": "start", "run": "x"}
    monkeypatch.setattr(bi, "read_state", lambda: [bad])
    with pytest.raises(bi.ParseError):
        bi.build()


# ------------------------------------------------------------------ query

def test_everything_about_a_symbol(built):
    pltr = bi.query_symbol(built, "PLTR")
    assert pltr["round_trips"], "PLTR has closed round trips in BLOTTER.json"
    assert pltr["research"], "PLTR is named in research entries"
    assert pltr["trade_log"], "PLTR is named in trade-log entries"


def test_query_unknown_symbol_hard_fails(built):
    with pytest.raises(bi.ParseError, match="not in the index"):
        bi.query_symbol(built, "NOPE")


def test_dates_join_every_source(built):
    d = built["dates"]
    assert all(list(v) == sorted(v) for v in d.values())
    asof = built["generated_from"]["trade_log_asof"]
    assert d[asof]["trade_log"]


def test_readme_links_the_index():
    text = (REPO / "docs" / "brain" / "README.md").read_text(encoding="utf-8")
    assert "INDEX.md" in text and "index.json" in text


# ------------------------------------------------------------ routine gate

LOG_WRITING_ROUTINES = [
    REPO / "routines" / name for name in
    ("pre-market.md", "market-open.md", "midday.md", "daily-summary.md", "weekly-review.md")
] + [
    REPO / ".claude" / "commands" / name for name in
    ("pre-market.md", "market-open.md", "midday.md", "daily-summary.md", "weekly-review.md")
]


def test_parse_mode_parses_everything_and_writes_nothing(tmp_path, monkeypatch, capsys):
    # 2026-10-16: a "### <date> — Midday" header (not "Midday Scan") failed
    # dashboard-data and tests three times in one day. --parse is the gate the
    # routines run before committing; it must exercise the same parsers and
    # leave the published files alone.
    monkeypatch.setattr(bi, "OUT_JSON", tmp_path / "index.json")
    monkeypatch.setattr(bi, "OUT_MD", tmp_path / "INDEX.md")
    assert bi.main(["--parse"]) == 0
    assert not (tmp_path / "index.json").exists() and not (tmp_path / "INDEX.md").exists()
    out = capsys.readouterr().out
    assert out.startswith("OK: parsed") and "nothing written" in out


def test_parse_mode_hard_fails_on_an_unknown_header(tmp_path, monkeypatch):
    bad = bi.TRADE_LOG.read_text(encoding="utf-8").replace(
        "— Midday Scan (Day 124", "— Midday (Day 124", 1)
    assert bad != bi.TRADE_LOG.read_text(encoding="utf-8")
    (tmp_path / "TRADE-LOG.md").write_text(bad, encoding="utf-8")
    monkeypatch.setattr(bi, "TRADE_LOG", tmp_path / "TRADE-LOG.md")
    with pytest.raises(bi.ParseError, match="unknown trade-log entry kind 'Midday'"):
        bi.main(["--parse"])


@pytest.mark.parametrize("command", LOG_WRITING_ROUTINES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_log_writing_routine_runs_the_parse_gate_before_committing(command):
    text = command.read_text(encoding="utf-8")
    assert "python3 scripts/build_brain_index.py --parse" in text, command
