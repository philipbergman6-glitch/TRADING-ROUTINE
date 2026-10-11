"""Segment records freeze the rulebook, prompts and model ids a score depends on; drift fails --check."""
from datetime import date
from pathlib import Path

from scripts import segment_record as sr

REPO = Path(__file__).resolve().parent.parent
RULEBOOK = "# Strategy\n- Active strategy version: v1.1 (notes)\n"
PROMPTS = {"routines/midday.md": sr.sha256_text("midday"), ".claude/commands/trade.md": sr.sha256_text("trade")}


def record():
    return sr.build_record(segment_id="0001", start=date(2026, 10, 13), rulebook_text=RULEBOOK, prompts=PROMPTS,
                           code_commit="abc123", model_ids={"midday": ["Claude Opus 5"]}, opened_on=date(2026, 10, 11))


def test_record_freezes_versions_and_hashes():
    rec = record()
    assert rec["status"] == "open" and rec["end_date"] is None
    assert rec["strategy_version"] == "v1.1" and rec["engine_version"] == "v1"
    assert rec["rulebook"]["sha256"] == sr.rulebook_sha256(RULEBOOK)
    assert rec["prompts"] == PROMPTS
    assert rec["account"]["baseline_equity_usd"] is None  # filled from the broker, never the log


def test_check_passes_when_tree_matches():
    assert sr.check_open_segments([("0001.json", record())], RULEBOOK, PROMPTS) == []


def test_rulebook_edit_during_open_segment_is_drift():
    problems = sr.check_open_segments([("0001.json", record())], RULEBOOK + "15. new rule\n", PROMPTS)
    assert problems == ["0001.json: rulebook sha256 changed during open segment"]


def test_prompt_edit_or_new_prompt_is_drift():
    changed = dict(PROMPTS, **{"routines/midday.md": sr.sha256_text("midday v2")})
    assert sr.check_open_segments([("0001.json", record())], RULEBOOK, changed) == [
        "0001.json: prompt changed or removed during open segment: routines/midday.md"]
    added = dict(PROMPTS, **{"routines/new.md": sr.sha256_text("x")})
    assert sr.check_open_segments([("0001.json", record())], RULEBOOK, added) == [
        "0001.json: new prompt not covered by the segment record: routines/new.md"]


def test_closed_segments_are_not_checked():
    rec = dict(record(), status="closed", end_date="2026-11-21")
    assert sr.check_open_segments([("0001.json", rec)], RULEBOOK + "edited", {}) == []


def test_model_ids_come_from_routine_commit_trailers():
    lines = [
        "midday scan 2026-10-09\x1fClaude Opus 5 <noreply@anthropic.com>",
        "market-open held 2026-10-13\x1fClaude Opus 5 <noreply@anthropic.com>",
        "EOD snapshot 2026-10-09\x1f",
        "dashboard data: 2026-10-09 [skip ci]\x1f",
        "docs: something\x1fClaude Fable 5.1 <noreply@anthropic.com>",
    ]
    ids = sr.model_ids_from_log(lines)
    assert ids["midday"] == ["Claude Opus 5"]
    assert ids["market-open"] == ["Claude Opus 5"]
    assert ids["daily-summary"] == []  # no trailer: the gap stays visible
    assert ids["pre-market"] == []


def test_committed_open_segments_match_this_tree():
    """CI guard: editing a prompt or the rulebook during an open segment must close it first."""
    problems = sr.check_open_segments(sr.load_records(REPO / "docs" / "experiments"),
                                      (REPO / "memory" / "TRADING-STRATEGY.md").read_text(encoding="utf-8"),
                                      sr.prompt_hashes(REPO))
    assert problems == [], "\n".join(problems)
