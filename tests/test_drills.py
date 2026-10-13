"""The freeze-rehearsal drills (#112, docs/DRILLS.md) that run in CI against the
stubbed broker, plus the guards that keep drill machinery off production."""
import pytest

from scripts import coordinator


# --- the drill account has its own state store ------------------------------------

def test_the_drill_profile_coordinates_on_its_own_store_branch():
    assert coordinator.open_store({"ALPACA_PROFILE": "drill"}).branch == "drill-state"
    assert coordinator.open_store({"ALPACA_PROFILE": "production"}).branch == "main"
    assert coordinator.open_store({}).branch == "main"


def test_an_unknown_profile_has_no_store():
    with pytest.raises(ValueError, match="ALPACA_PROFILE"):
        coordinator.open_store({"ALPACA_PROFILE": "staging"})


# --- a drill session leaves a run record on the drill store -----------------------

from scripts import run_record as rr  # noqa: E402
from scripts.state_store import StateStore  # noqa: E402
from tests.test_run_record import checkout, git  # noqa: E402,F401  (fixture)

DRILL = {"ALPACA_PROFILE": "drill"}


def drill_start(work, environ):
    return rr.main(["--repo", str(work), "start", "--routine", "drill", "--trigger", "local",
                    "--command-file", "docs/DRILLS.md", "--model", "claude-opus-5-5"], environ=environ)


def test_a_drill_run_is_recorded_on_the_drill_store_never_on_main(checkout):
    (checkout / "docs" / "DRILLS.md").write_text("# Drills\n")
    git("add", ".", cwd=checkout)
    git("commit", "-q", "-m", "runbook", cwd=checkout)
    git("push", "-q", "origin", "HEAD:main", "HEAD:drill-state", cwd=checkout)

    assert drill_start(checkout, DRILL) == rr.EXIT_OK
    assert rr.main(["--repo", str(checkout), "finish", "--action", "buy SPY 1"], environ=DRILL) == rr.EXIT_OK

    (run,) = rr.fold(StateStore(checkout, branch="drill-state").fetch().events)
    assert (run.routine, run.trigger, run.outcome) == ("drill", "local", "actions")
    assert rr.fold(StateStore(checkout).fetch().events) == []


def test_a_drill_run_record_is_refused_outside_the_drill_profile(checkout):
    assert drill_start(checkout, {}) == rr.EXIT_USAGE
    assert drill_start(checkout, {"ALPACA_PROFILE": "production"}) == rr.EXIT_USAGE
    assert rr.fold(StateStore(checkout).fetch().events) == []


# --- CI drills (docs/DRILLS.md catalogue) -------------------------------------------

import os  # noqa: E402
import subprocess  # noqa: E402

from scripts import validate_order  # noqa: E402
from scripts.coordinator import Outcome, send_alerts  # noqa: E402
from scripts.strategy_version import bind  # noqa: E402
from scripts.submit_entry import submit_entry  # noqa: E402
from scripts.validate_mutation import validate_mutation  # noqa: E402
from tests.store_support import NOW, Clock, intent_lines, make_origin, writer_store  # noqa: E402
from tests.test_coordinated_helpers import Market, engine_gate, oto  # noqa: E402


def entry(store, broker, clock, check=None):
    with pytest.raises(Outcome) as info:
        submit_entry(oto("AMD", 10), read=broker.read, run=broker.run, now=clock(), store=store, writer="market-open",
                     check=check or engine_gate(broker), clock=clock, sleep=clock.sleep, fault=lambda _: None)
    return info.value


def test_drill_cross_midnight_retry_adopts_the_lost_entry_instead_of_buying_again(tmp_path):
    store, broker = writer_store(tmp_path, make_origin(tmp_path), "routine"), Market()
    broker.lose_responses, broker.hidden_lookups = 1, 99      # lands, but stays invisible past the budget
    clock = Clock(NOW.replace(hour=23, minute=58))           # Tuesday 23:58 UTC

    lost = entry(store, broker, clock)
    assert (lost.code, lost.detail["intent"]) == (8, "en-20261013-AMD")

    broker.hidden_lookups = 0
    clock.advance(minutes=10)                                # Wednesday 00:08 UTC: a new mint day
    rerun = entry(store, broker, clock)

    assert (rerun.code, rerun.state, rerun.detail["intent"]) == (0, "already_submitted", "en-20261013-AMD")
    assert {p["client_order_id"] for p in broker.posts} == {"en-20261013-AMD"}
    assert [e["state"] for e in intent_lines(store_origin(store))] == ["recorded", "lost", "acknowledged"]


def store_origin(store):
    return subprocess.run(["git", "remote", "get-url", "origin"], cwd=store.repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("history", [[{"side": "buy"}] * 500, {"message": "not a list"}])
def test_drill_missing_history_refuses_the_buy_with_exit_4(tmp_path, monkeypatch, history):
    store, broker = writer_store(tmp_path, make_origin(tmp_path), "routine"), Market()
    account = {"account": {"equity": "100000", "cash": "25000"}, "positions": []}
    monkeypatch.setattr(validate_order, "adapter", lambda cmd, *a: history if cmd == "orders" else account[cmd])

    def live_gate(command, argument, reservations=(), composition_waiver=None):  # reads the account itself
        return validate_mutation(command, argument, read=broker.read, now=NOW, binding=bind(os.environ),
                                 reservations=reservations, composition_waiver=composition_waiver)
    got = entry(store, broker, Clock(), check=live_gate)

    assert got.code == 4 and broker.posts == []


def test_drill_an_undelivered_coordinator_alert_is_reported_not_swallowed():
    outcome = Outcome(10, "store_unavailable", alerts=["STORE UNAVAILABLE: placed protection on uncovered SPY"])
    send_alerts(outcome, run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3))
    assert outcome.detail["alerts_delivered"] is False

    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    send_alerts(outcome, run=hung)
    assert outcome.detail["alerts_delivered"] is False


# --- the runbook names real tests and records every live drill ----------------------

import importlib  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "DRILLS.md"
SCENARIOS = ["Two writers simultaneously", "Cross-midnight retry", "Crash after cancel", "Lost POST response",
             "Partial fill", "Missing history", "Unavailable store", "Stale quote", "Missed monitor",
             "Failed alert delivery", "Version mismatch"]
MODES = {"CI stub", "drill account", "both"}


def table(heading):
    """Rows of the markdown table in the section under `heading`, as lists of cells."""
    lines = RUNBOOK.read_text(encoding="utf-8").split(heading + "\n", 1)[1].splitlines()
    end = next((i for i, line in enumerate(lines) if line.startswith("#")), len(lines))
    rows = [line for line in lines[:end] if line.startswith("|")]
    return [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows[2:]]


def test_the_catalogue_has_one_row_per_scenario_with_a_mode():
    rows = table("## Catalogue")
    assert [r[1] for r in rows] == SCENARIOS
    for r in rows:
        assert len(r) == 6 and all(r), r
        assert r[5].split(" (")[0] in MODES, r


def test_every_ci_drill_names_tests_that_exist():
    modes = {r[0]: r[5].split(" (")[0] for r in table("## Catalogue")}
    named = {r[0]: re.findall(r"`(tests/[\w/]+\.py)::(\w+)`", r[1]) for r in table("### CI tests")}
    for number, mode in modes.items():
        if mode != "drill account":
            assert named.get(number), f"drill {number} runs in CI but names no test"
    for refs in named.values():
        for path, name in refs:
            module = importlib.import_module(path[:-3].replace("/", "."))
            assert callable(getattr(module, name, None)), f"{path}::{name} does not exist"


def test_every_live_drill_has_a_recorded_result_and_a_red_one_names_its_ticket():
    modes = {r[0]: r[5].split(" (")[0] for r in table("## Catalogue")}
    results = {r[0]: r for r in table("### Verdicts by drill")}
    for number, mode in modes.items():
        if mode == "CI stub":
            continue
        assert number in results, f"live drill {number} has no recorded result"
        verdict = results[number][2]
        assert verdict in ("green", "red"), results[number]
        if verdict == "red":
            assert re.search(r"#\d+", results[number][3]), f"red drill {number} must name its child ticket"
