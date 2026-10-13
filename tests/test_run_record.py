"""Run records (ADR 0012): one start and one finish line per run in the
committed state store, folded into runs; anything malformed hard-fails."""
import json
import subprocess

import pytest

from scripts import run_record as rr
from scripts.state_store import STATE_FILE, StateStore, encode, new_event

RUN = "market-open-20261013T133000Z-a1b2c3"


def start(run=RUN, **over):
    fields = {"op": "start", "run": run, "routine": "market-open", "trigger": "cloud",
              "code_sha": "0" * 40, "code_subject": "dashboard data: 2026-10-12 [skip ci]",
              "code_dirty": False, "rulebook_version": "v1.1", "rulebook_sha256": "a" * 64,
              "rulebook_pinned": True, "command_file": "routines/market-open.md",
              "command_sha256": "b" * 64, "model_id": "claude-opus-5", "model_source": "self-reported",
              "host_ref": None}
    fields.update(over)
    return new_event("run", run, **fields)


def finish(run=RUN, **over):
    fields = {"op": "finish", "run": run, "outcome": "no-trade", "actions": [], "refusals": [],
              "incidents": [], "intents": []}
    fields.update(over)
    return new_event("run", run, **fields)


# --- folding the store into runs ----------------------------------------------

def test_a_start_and_its_finish_fold_into_one_finished_run():
    s, f = start(), finish(outcome="actions", actions=["buy XLK 10"], intents=["en-20261013-XLK"])
    (run,) = rr.fold([s, f])
    assert run.run == RUN and run.routine == "market-open"
    assert run.started_at == s["at"] and run.ended_at == f["at"]
    assert run.outcome == "actions" and run.intents == ("en-20261013-XLK",)


def test_a_start_without_a_finish_is_an_unfinished_run():
    (run,) = rr.fold([start()])
    assert run.ended_at is None and run.outcome is None


def test_other_kinds_in_the_store_are_ignored():
    assert rr.fold([new_event("lease", "midday/1", op="acquire")]) == []


@pytest.mark.parametrize("events, reason", [
    (lambda: [finish()], "no start"),
    (lambda: [start(), start()], "started twice"),
    (lambda: [start(), finish(), finish()], "finished twice"),
    (lambda: [start(), {**finish(), "writer": "midday-20261013T170000Z-ffffff"}], "writer"),
])
def test_fold_hard_fails_on_an_impossible_sequence(events, reason):
    with pytest.raises(rr.MalformedRunRecord, match=reason):
        rr.fold(events())


@pytest.mark.parametrize("line", [
    lambda: {**start(), "extra": 1},
    lambda: {k: v for k, v in start().items() if k != "code_sha"},
    lambda: start(routine="lunch"),
    lambda: start(trigger="schedule"),  # cloud routines are not GitHub schedules
    lambda: start(routine="protection-monitor", trigger="cloud",
                  run="protection-monitor-20261013T133000Z-a1b2c3"),
    lambda: start(run="midday-20261013T133000Z-a1b2c3"),  # run id names another routine
    lambda: start(code_sha="abc"),
    lambda: start(rulebook_pinned="yes"),
    lambda: start(model_source="self-reported", model_id=None),
    lambda: start(model_source="unexposed", model_id="claude-opus-5"),
    lambda: start(command_file="/etc/passwd"),
    lambda: finish(outcome="profit"),
    lambda: finish(outcome="no-trade", actions=["buy XLK 10"]),  # outcome contradicts lists
    lambda: finish(actions="buy XLK"),
    lambda: finish(actions=[""]),
    lambda: finish(intents=["XLK please"]),
    lambda: {**finish(), "op": "pause"},
])
def test_a_malformed_line_hard_fails(line):
    event = line()
    with pytest.raises(rr.MalformedRunRecord):
        rr.fold([start(), event] if event.get("op") == "finish" else [event])


@pytest.mark.parametrize("lists, expected", [
    ({}, "no-trade"),
    ({"refusals": ["rule 8: 3 trades this week"]}, "refused"),
    ({"actions": ["tighten MU 7%"], "refusals": ["x"]}, "actions"),
    ({"incidents": ["push not on main"], "actions": ["buy XLK 10"]}, "incident"),
])
def test_outcome_is_derived_from_what_happened(lists, expected):
    assert rr.outcome_of(**{"actions": [], "refusals": [], "incidents": [], **lists}) == expected


# --- the writer: start and finish against a bare origin ------------------------

RULEBOOK = "# Rules\n- Active strategy version: v1.1\n"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def checkout(tmp_path):
    """A routine's checkout of a bare origin holding a pinned rulebook and the
    instruction files, as a cloud routine sees after its sync."""
    import hashlib
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    work = tmp_path / "work"
    git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    git("config", "user.name", "routine", cwd=work)
    git("config", "user.email", "routine@example.invalid", cwd=work)
    (work / "memory").mkdir()
    (work / "memory" / "TRADING-STRATEGY.md").write_text(RULEBOOK)
    (work / "docs").mkdir()
    pin = hashlib.sha256(RULEBOOK.encode()).hexdigest()
    (work / "docs" / "rulebook-pins.json").write_text(json.dumps({"v1.1": {"sha256": pin}}))
    (work / "routines").mkdir()
    (work / "routines" / "market-open.md").write_text("STEP 1 — trade\n")
    git("add", ".", cwd=work)
    git("commit", "-q", "-m", "seed main", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)
    return work


def runs_on_origin(work):
    return rr.fold(StateStore(work).fetch().events)


def cli(work, *args, environ=None):
    return rr.main(["--repo", str(work), *args], environ={} if environ is None else environ)


def start_market_open(work, *extra, environ=None):
    return cli(work, "start", "--routine", "market-open", "--trigger", "cloud",
               "--command-file", "routines/market-open.md", *extra, environ=environ)


def test_start_records_the_provenance_of_the_checkout(checkout, capsys):
    import hashlib
    assert start_market_open(checkout, "--model", "claude-opus-5") == rr.EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    (run,) = runs_on_origin(checkout)
    assert run.run == printed["run"] and run.ended_at is None
    s = run.start
    assert s["code_sha"] == git("rev-parse", "HEAD", cwd=checkout).strip()
    assert s["code_subject"] == "seed main" and s["code_dirty"] is False
    assert (s["rulebook_version"], s["rulebook_pinned"]) == ("v1.1", True)
    assert s["command_sha256"] == hashlib.sha256(b"STEP 1 \xe2\x80\x94 trade\n").hexdigest()
    assert (s["model_id"], s["model_source"]) == ("claude-opus-5", "self-reported")


def test_finish_closes_the_run_start_remembered(checkout):
    start_market_open(checkout, "--model", "claude-opus-5")
    assert cli(checkout, "finish", "--action", "buy XLK 10", "--refusal", "rule 8: MU",
               "--intent", "en-20261013-XLK") == rr.EXIT_OK
    (run,) = runs_on_origin(checkout)
    assert run.outcome == "actions" and run.actions == ("buy XLK 10",)
    assert run.refusals == ("rule 8: MU",) and run.intents == ("en-20261013-XLK",)
    # the run is done: a second finish has nothing to close
    assert cli(checkout, "finish") == rr.EXIT_USAGE


def test_a_finish_with_no_started_run_is_refused(checkout):
    assert cli(checkout, "finish") == rr.EXIT_USAGE
    assert runs_on_origin(checkout) == []


def test_an_unpinned_rulebook_is_recorded_as_unpinned_not_hidden(checkout):
    (checkout / "memory" / "TRADING-STRATEGY.md").write_text(RULEBOOK + "- rule 15\n")
    start_market_open(checkout, "--model", "claude-opus-5")
    (run,) = runs_on_origin(checkout)
    assert run.start["rulebook_pinned"] is False and run.start["code_dirty"] is True


def test_model_is_unexposed_when_neither_flag_nor_environment_names_it(checkout):
    start_market_open(checkout)
    (run,) = runs_on_origin(checkout)
    assert (run.start["model_id"], run.start["model_source"]) == (None, "unexposed")


def test_model_from_the_environment_is_labelled_as_such(checkout):
    start_market_open(checkout, environ={"ANTHROPIC_MODEL": "claude-opus-5"})
    (run,) = runs_on_origin(checkout)
    assert run.start["model_source"] == "env:ANTHROPIC_MODEL"


def test_a_github_run_is_referenced_by_its_run_id(checkout):
    (checkout / ".github").mkdir()
    (checkout / ".github" / "monitor.yml").write_text("on: schedule\n")
    assert cli(checkout, "start", "--routine", "protection-monitor", "--trigger", "schedule",
               "--command-file", ".github/monitor.yml",
               environ={"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}) == rr.EXIT_OK
    (run,) = runs_on_origin(checkout)
    assert run.start["host_ref"] == "github-actions:123/2"
    assert run.start["model_source"] == "not-applicable"


@pytest.mark.parametrize("args", [
    ["--routine", "lunch", "--trigger", "cloud", "--command-file", "routines/market-open.md"],
    ["--routine", "market-open", "--trigger", "cloud", "--command-file", "routines/missing.md"],
    ["--routine", "market-open", "--trigger", "cloud", "--command-file", "../outside.md"],
    ["--routine", "market-open", "--trigger", "schedule", "--command-file", "routines/market-open.md"],
    ["--routine", "protection-monitor", "--trigger", "schedule",
     "--command-file", "routines/market-open.md", "--model", "claude-opus-5"],
])
def test_a_start_that_would_be_malformed_never_reaches_the_store(checkout, args):
    assert cli(checkout, "start", *args) == rr.EXIT_USAGE
    assert runs_on_origin(checkout) == []


def test_a_finish_that_would_be_malformed_never_reaches_the_store(checkout):
    start_market_open(checkout)
    assert cli(checkout, "finish", "--intent", "buy XLK") == rr.EXIT_USAGE
    (run,) = runs_on_origin(checkout)
    assert run.ended_at is None


def test_unreachable_store_fails_closed_and_remembers_no_run(checkout):
    git("remote", "set-url", "origin", str(checkout.parent / "gone.git"), cwd=checkout)
    assert start_market_open(checkout) == rr.EXIT_STORE_UNAVAILABLE
    git("remote", "set-url", "origin", str(checkout.parent / "origin.git"), cwd=checkout)
    assert cli(checkout, "finish") == rr.EXIT_USAGE


def test_a_corrupt_store_is_a_store_failure(checkout):
    (checkout / STATE_FILE).parent.mkdir()
    (checkout / STATE_FILE).write_text(encode(finish()))  # a finish with no start
    git("add", ".", cwd=checkout)
    git("commit", "-q", "-m", "corrupt", cwd=checkout)
    git("push", "-q", "origin", "HEAD:main", cwd=checkout)
    assert start_market_open(checkout) == rr.EXIT_STORE_UNAVAILABLE


# --- the protection monitor's report -------------------------------------------

def report_file(tmp_path, report):
    path = tmp_path / "report.json"
    path.write_text(report if isinstance(report, str) else json.dumps(report))
    return path


def test_an_overlong_monitor_issue_is_cut_so_the_finish_still_lands(tmp_path):
    report = {"exit": 5, "results": [], "coverage": {"ok": False, "issues": ["x" * 2000]}, "holds": []}
    (issue, _) = rr.monitor_lists(report_file(tmp_path, report))["incidents"]
    assert len(issue) == rr.MAX_TEXT


def test_a_clean_monitor_run_with_nothing_due_is_no_trade(tmp_path):
    report = {"exit": 0, "results": [], "coverage": {"ok": True, "issues": []}, "holds": [], "standing": []}
    lists = rr.monitor_lists(report_file(tmp_path, report))
    assert lists == {"actions": [], "refusals": [], "incidents": []}


def test_monitor_actions_holds_and_issues_map_to_the_record(tmp_path):
    report = {"exit": 8, "results": [{"kind": "tighten", "symbol": "MU", "state": "unprotected", "exit": 8}],
              "coverage": {"ok": False, "issues": ["XLB uncovered: 412 held, 0 covered"]},
              "holds": ["XLP: HOLD fixed 80.10"], "standing": []}
    lists = rr.monitor_lists(report_file(tmp_path, report))
    assert lists["actions"] == ["tighten MU -> unprotected"]
    assert lists["refusals"] == ["XLP: HOLD fixed 80.10"]
    assert lists["incidents"] == ["XLB uncovered: 412 held, 0 covered", "monitor exit 8"]


@pytest.mark.parametrize("content", [None, "", "{not json", "[]", '{"exit": "zero"}'])
def test_a_missing_or_unreadable_report_is_itself_the_incident(tmp_path, content):
    path = tmp_path / "absent.json" if content is None else report_file(tmp_path, content)
    lists = rr.monitor_lists(path)
    assert lists["actions"] == [] and len(lists["incidents"]) == 1
    assert "no readable report" in lists["incidents"][0]


def test_finish_from_a_monitor_report_closes_the_monitor_run(checkout, tmp_path):
    (checkout / "wf.yml").write_text("on: schedule\n")
    cli(checkout, "start", "--routine", "protection-monitor", "--trigger", "schedule", "--command-file", "wf.yml")
    report = {"exit": 4, "state": "broker_state_unavailable", "adapter_exit": 4}
    assert cli(checkout, "finish", "--monitor-report", str(report_file(tmp_path, report))) == rr.EXIT_OK
    (run,) = runs_on_origin(checkout)
    assert run.outcome == "incident" and run.incidents == ("broker_state_unavailable", "monitor exit 4")


# --- wiring: every routine and the monitor write a run record -------------------

from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
COPIES = [(r, trigger, path) for r in sorted(rr.CLAUDE_ROUTINES)
          for trigger, path in (("cloud", f"routines/{r}.md"), ("local", f".claude/commands/{r}.md"))]


@pytest.mark.parametrize("routine, trigger, path", COPIES)
def test_every_routine_copy_starts_and_finishes_its_own_run_record(routine, trigger, path):
    text = " ".join((REPO / path).read_text(encoding="utf-8").replace("\\\n", " ").split())
    start_cmd = (f"python3 scripts/run_record.py {'--local ' if trigger == 'local' else ''}start "
                 f"--routine {routine} --trigger {trigger} --command-file {path} --model")
    assert start_cmd in text
    assert f"python3 scripts/run_record.py {'--local ' if trigger == 'local' else ''}finish" in text
    assert text.index(start_cmd) < text.rindex("scripts/run_record.py")


def test_the_monitor_workflow_starts_and_finishes_a_run_record():
    text = (REPO / ".github/workflows/protection-monitor.yml").read_text(encoding="utf-8")
    assert "run_record.py start --routine protection-monitor" in text
    assert "--command-file .github/workflows/protection-monitor.yml" in text
    assert 'run_record.py finish --monitor-report' in text
    assert text.index("run_record.py start") < text.index("scripts/protection_monitor.py") \
        < text.index("run_record.py finish")


READ_ONLY = ("pre-market", "daily-summary", "weekly-review")


@pytest.mark.parametrize("routine, trigger, path", [c for c in COPIES if c[0] in READ_ONLY])
def test_read_only_routines_report_unfinished_intents_in_their_run_record(routine, trigger, path):
    """ADR 0010 section 5: read-only routines never take the lease or recover;
    they pass non-terminal intents, stale leases and takeovers to finish."""
    text = " ".join((REPO / path).read_text(encoding="utf-8").replace("\\\n", " ").split())
    prefix = "TRADING_STATE_STORE=local " if trigger == "local" else ""
    status = f"STATUS_JSON=$({prefix}python3 scripts/coordinator.py status); STATUS_EXIT=$?"
    assert status in text
    assert text.index(status) < text.rindex("scripts/run_record.py")
    step = text[text.index(status):]
    for incident in ('"unfinished intent <intent>', '"lease takeover <lease>', '"stale lease <lease>',
                     '"state store unavailable: <reason>"', "Any other exit"):
        assert incident in step, f"{path}: lacks {incident}"
    assert "coordinator.py recover" not in text
    assert "every STEP 2b incident" in text[text.rindex("LAST STEP"):]
