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
