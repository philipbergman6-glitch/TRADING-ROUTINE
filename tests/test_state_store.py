"""Committed state store (ADR 0004): append-only JSONL on `main`, git push is
the compare-and-swap, and every failure to reach or trust the store fails
closed. Offline: a local bare repository plays `origin`."""
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

from scripts.state_store import (EXIT_STORE_UNAVAILABLE, EXIT_USAGE, PUSH_BUDGET, STATE_FILE, WITHDRAW_KIND, ClaimLost,
                                 CorruptState, StateStore, StoreUnavailable, local_store, main, new_event,
                                 replay, validate)


def line(**over):
    event = {"id": "e1", "kind": "test", "at": "2026-10-12T14:00:00Z",
             "writer": "pytest/1", "schema": 1}
    event.update(over)
    return json.dumps(event)


def test_replay_of_an_empty_file_is_no_events():
    assert replay("") == []


def test_replay_returns_events_in_file_order():
    text = line(id="a") + "\n" + line(id="b", symbol="XLK") + "\n"
    assert [e["id"] for e in replay(text)] == ["a", "b"]
    assert replay(text)[1]["symbol"] == "XLK"


@pytest.mark.parametrize("bad", [
    "not json",
    "[1, 2]",
    line(id=""),
    line(kind=None),
    line(writer=""),
    line(schema="1"),
    line(schema=True),
    line(schema=0),
    line(at="2026-10-12T14:00:00"),        # naive
    line(at="2026-10-12T10:00:00-04:00"),  # not UTC
    line(at="yesterday"),
    "",                                    # blank line inside the file
])
def test_replay_hard_fails_on_a_corrupt_line(bad):
    text = line(id="ok") + "\n" + bad + "\n" + line(id="later") + "\n"
    with pytest.raises(CorruptState, match="line 2"):
        replay(text)


@pytest.mark.parametrize("missing", ["id", "kind", "at", "writer", "schema"])
def test_replay_hard_fails_when_an_envelope_field_is_missing(missing):
    event = json.loads(line())
    del event[missing]
    with pytest.raises(CorruptState, match=missing):
        replay(json.dumps(event) + "\n")


def test_replay_hard_fails_on_a_duplicate_id():
    with pytest.raises(CorruptState, match="duplicate"):
        replay(line(id="a") + "\n" + line(id="a") + "\n")


def test_replay_hard_fails_on_a_missing_final_newline():
    # A torn write; appending to it would glue two events onto one line.
    with pytest.raises(CorruptState, match="newline"):
        replay(line(id="a"))


def test_corrupt_state_is_a_store_failure():
    assert issubclass(CorruptState, StoreUnavailable)


# --- git fixtures: a bare `origin` and writers that clone it -----------------

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def workdir(tmp_path, origin, name):
    """A normal clone with an identity, as a cloud routine's checkout has."""
    path = tmp_path / name
    git("clone", "-q", str(origin), str(path), cwd=tmp_path)
    git("config", "user.name", name, cwd=path)
    git("config", "user.email", f"{name}@example.invalid", cwd=path)
    return path


def push_file(clone, rel, text, subject):
    """Another writer (or a routine's memory/ commit) moving the tip of main."""
    git("pull", "-q", "--rebase", "origin", "main", cwd=clone)
    (clone / rel).parent.mkdir(parents=True, exist_ok=True)
    (clone / rel).write_text(text)
    git("add", rel, cwd=clone)
    git("commit", "-q", "-m", subject, cwd=clone)
    git("push", "-q", "origin", "HEAD:main", cwd=clone)


@pytest.fixture
def origin(tmp_path):
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    git("config", "user.name", "seed", cwd=seed)
    git("config", "user.email", "seed@example.invalid", cwd=seed)
    (seed / "README.md").write_text("seed\n")
    git("add", ".", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", str(bare), "HEAD:main", cwd=seed)
    return bare


def origin_file(origin):
    return git("show", f"main:{STATE_FILE}", cwd=origin)


def subjects(origin):
    return git("log", "--format=%s", "main", cwd=origin).splitlines()


def test_fetch_with_no_state_file_on_main_is_no_events(tmp_path, origin):
    snap = StateStore(workdir(tmp_path, origin, "a")).fetch()
    assert snap.events == []


def test_fetch_reads_main_on_origin_not_the_stale_checkout(tmp_path, origin):
    reader = workdir(tmp_path, origin, "reader")
    push_file(workdir(tmp_path, origin, "other"), STATE_FILE, line(id="fresh") + "\n", "other")
    (reader / STATE_FILE).parent.mkdir()
    (reader / STATE_FILE).write_text(line(id="stale") + "\n")
    assert [e["id"] for e in StateStore(reader).fetch().events] == ["fresh"]


def test_fetch_hard_fails_on_a_corrupt_file_on_origin(tmp_path, origin):
    push_file(workdir(tmp_path, origin, "other"), STATE_FILE, "garbage\n", "corrupt")
    with pytest.raises(CorruptState, match="line 1"):
        StateStore(workdir(tmp_path, origin, "a")).fetch()


def test_fetch_failure_is_store_unavailable(tmp_path, origin):
    reader = workdir(tmp_path, origin, "a")
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=reader)
    with pytest.raises(StoreUnavailable, match="fetch"):
        StateStore(reader).fetch()


def test_new_event_mints_a_valid_envelope():
    event = new_event("test", "pytest/1", symbol="XLK")
    assert validate(event) is event
    assert event["symbol"] == "XLK" and event["at"].endswith("+00:00")
    assert new_event("test", "pytest/1")["id"] != new_event("test", "pytest/1")["id"]


def test_commit_lands_the_lines_on_main_with_a_skip_ci_subject(tmp_path, origin):
    a = workdir(tmp_path, origin, "a")
    head, status = git("rev-parse", "HEAD", cwd=a), git("status", "--porcelain", cwd=a)
    store = StateStore(a)
    claim = new_event("test", "pytest/1", symbol="XLK")

    done = store.commit(store.fetch(), [claim], writer="pytest/1", intent="intent-1")

    assert done.subject == "state: pytest/1 intent-1 [skip ci]"
    assert subjects(origin)[0] == done.subject
    assert replay(origin_file(origin)) == [claim]
    assert done.attempts == 1 and done.events == [claim]
    # The checkout the writer runs in is never touched.
    assert git("rev-parse", "HEAD", cwd=a) == head
    assert git("status", "--porcelain", cwd=a) == status


def test_commit_appends_to_existing_events(tmp_path, origin):
    store = StateStore(workdir(tmp_path, origin, "a"))
    first, second = new_event("test", "w/1"), new_event("test", "w/1")
    store.commit(store.fetch(), [first], writer="w/1", intent="i1")
    store.commit(store.fetch(), [second], writer="w/1", intent="i2")
    assert replay(origin_file(origin)) == [first, second]


@pytest.mark.parametrize("kwargs", [
    {"lines": []},
    {"lines": [{"id": "x"}]},
    {"writer": "two words"},
    {"intent": ""},
    {"budget": 0},
])
def test_commit_refuses_invalid_input_before_touching_origin(tmp_path, origin, kwargs):
    store = StateStore(workdir(tmp_path, origin, "a"))
    args = {"lines": [new_event("test", "w/1")], "writer": "w/1", "intent": "i1", **kwargs}
    with pytest.raises(ValueError):
        store.commit(store.fetch(), args.pop("lines"), **args)
    assert subjects(origin) == ["seed"]


def first_claim_wins(symbol, claim_id):
    """A stand-in for the coordinator's replay rule (#99): the earliest
    unreleased claim on a symbol owns it."""
    def still_wins(events):
        released = {i for e in events if e["kind"] == WITHDRAW_KIND for i in e["withdraws"]}
        claims = [e for e in events if e["kind"] == "test" and e.get("symbol") == symbol
                  and e["id"] not in released]
        return bool(claims) and claims[0]["id"] == claim_id
    return still_wins


def test_unrelated_tip_move_is_rejected_then_rebased_and_retried(tmp_path, origin):
    store = StateStore(workdir(tmp_path, origin, "a"))
    snap = store.fetch()
    push_file(workdir(tmp_path, origin, "routine"), "memory/TRADE-LOG.md", "log\n", "midday log")
    claim = new_event("test", "a/1", symbol="XLK")

    done = store.commit(snap, [claim], writer="a/1", intent="i1",
                        still_wins=first_claim_wins("XLK", claim["id"]))

    assert done.attempts == 2
    assert subjects(origin)[:2] == ["state: a/1 i1 [skip ci]", "midday log"]
    assert replay(origin_file(origin)) == [claim]


def test_concurrent_appends_from_one_base_both_survive_in_push_order(tmp_path, origin):
    a = StateStore(workdir(tmp_path, origin, "a"))
    b = StateStore(workdir(tmp_path, origin, "b"))
    snap_a, snap_b = a.fetch(), b.fetch()
    ea, eb = new_event("test", "a/1", symbol="XLK"), new_event("test", "b/1", symbol="XLP")
    b.commit(snap_b, [eb], writer="b/1", intent="ib")
    done = a.commit(snap_a, [ea], writer="a/1", intent="ia")
    assert done.attempts == 2
    assert replay(origin_file(origin)) == [eb, ea]


def test_competing_claim_withdraws_and_fails_closed(tmp_path, origin):
    a = StateStore(workdir(tmp_path, origin, "a"))
    b = StateStore(workdir(tmp_path, origin, "b"))
    snap_a, snap_b = a.fetch(), b.fetch()
    ca, cb = new_event("test", "a/1", symbol="XLK"), new_event("test", "b/1", symbol="XLK")
    b.commit(snap_b, [cb], writer="b/1", intent="ib", still_wins=first_claim_wins("XLK", cb["id"]))

    with pytest.raises(ClaimLost):
        a.commit(snap_a, [ca], writer="a/1", intent="ia", still_wins=first_claim_wins("XLK", ca["id"]))

    events = replay(origin_file(origin))
    assert [e["id"] for e in events[:2]] == [cb["id"], ca["id"]]
    withdraw = events[2]
    assert withdraw["kind"] == WITHDRAW_KIND == "withdraw" and withdraw["withdraws"] == [ca["id"]]
    assert withdraw["writer"] == "a/1" and withdraw["intent"] == "ia"
    # The winner is unaffected.
    assert first_claim_wins("XLK", cb["id"])(events)


def test_push_budget_is_five_per_adr_0010():
    assert PUSH_BUDGET == 5


def install_reject_hook(origin):
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)


def test_push_rejected_beyond_the_budget_fails_closed(tmp_path, origin):
    store = StateStore(workdir(tmp_path, origin, "a"))
    snap = store.fetch()
    install_reject_hook(origin)
    with pytest.raises(StoreUnavailable, match="budget of 2 exhausted.*rejected by test hook"):
        store.commit(snap, [new_event("test", "a/1")], writer="a/1", intent="i1", budget=2)
    assert subjects(origin) == ["seed"]


def test_fetch_failure_after_a_rejected_push_fails_closed(tmp_path, origin):
    a = workdir(tmp_path, origin, "a")
    store = StateStore(a)
    snap = store.fetch()
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=a)
    with pytest.raises(StoreUnavailable, match="fetch"):
        store.commit(snap, [new_event("test", "a/1")], writer="a/1", intent="i1")


def test_a_push_whose_response_was_lost_is_not_appended_twice(tmp_path, origin):
    a = StateStore(workdir(tmp_path, origin, "a"))
    snap = a.fetch()
    event = new_event("test", "a/1")
    a.commit(snap, [event], writer="a/1", intent="i1")
    # Retrying from the stale snapshot (as after a lost push response) is
    # rejected, finds its lines already on main, and verifies instead.
    done = a.commit(snap, [event], writer="a/1", intent="i1")
    assert done.attempts == 1
    assert replay(origin_file(origin)) == [event]


def test_local_mode_writes_from_a_dedicated_bare_clone(tmp_path, origin):
    cache = tmp_path / "cache" / "state.git"
    store = local_store(str(origin), cache)
    store.commit(store.fetch(), [new_event("test", "trade/local")], writer="trade/local", intent="i1")
    again = local_store(str(origin), cache)  # reused, not recloned
    assert len(again.fetch().events) == 1
    assert git("rev-parse", "--is-bare-repository", cwd=cache).strip() == "true"


def test_local_mode_refuses_a_cache_pointing_at_another_remote(tmp_path, origin):
    cache = tmp_path / "state.git"
    local_store(str(origin), cache)
    with pytest.raises(StoreUnavailable, match="remote"):
        local_store(str(tmp_path / "elsewhere.git"), cache)


def test_cli_append_then_replay(tmp_path, origin, capsys):
    a = str(workdir(tmp_path, origin, "a"))
    assert main(["--repo", a, "append", "--writer", "daily-summary/1", "--intent", "run-1",
                 "--kind", "test", "--fields", '{"note": "x"}']) == 0
    assert json.loads(capsys.readouterr().out)["subject"] == "state: daily-summary/1 run-1 [skip ci]"
    assert main(["--repo", a, "replay"]) == 0
    (event,) = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert event["note"] == "x" and event["writer"] == "daily-summary/1"


def test_cli_exits_store_unavailable_when_origin_is_unreachable(tmp_path, origin, capsys):
    a = workdir(tmp_path, origin, "a")
    git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=a)
    assert EXIT_STORE_UNAVAILABLE == 10
    assert main(["--repo", str(a), "replay"]) == EXIT_STORE_UNAVAILABLE
    assert json.loads(capsys.readouterr().err)["state"] == "store_unavailable"


def test_cli_exits_store_unavailable_on_a_corrupt_file(tmp_path, origin, capsys):
    push_file(workdir(tmp_path, origin, "other"), STATE_FILE, "garbage\n", "corrupt")
    a = str(workdir(tmp_path, origin, "a"))
    assert main(["--repo", a, "append", "--writer", "w/1", "--intent", "i1", "--kind", "test"]) \
        == EXIT_STORE_UNAVAILABLE
    assert subjects(origin)[0] == "corrupt"


@pytest.mark.parametrize("fields", ["[1]", "not json", '{"id": "mine"}'])
def test_cli_rejects_bad_fields_as_usage(tmp_path, origin, fields):
    a = str(workdir(tmp_path, origin, "a"))
    assert main(["--repo", a, "append", "--writer", "w/1", "--intent", "i1", "--kind", "test",
                 "--fields", fields]) == EXIT_USAGE
    assert subjects(origin) == ["seed"]


def test_repo_marks_the_state_file_union_merge_so_plain_rebases_do_not_conflict(tmp_path, origin):
    # Writers that commit state/ through ordinary git (git pull --rebase)
    # must not hit a textual conflict on concurrent appends (ADR 0004 §2).
    seed = workdir(tmp_path, origin, "seed2")
    push_file(seed, ".gitattributes", (REPO / ".gitattributes").read_text(), "attributes")
    push_file(seed, STATE_FILE, line(id="base") + "\n", "base")
    a, b = workdir(tmp_path, origin, "a"), workdir(tmp_path, origin, "b")
    with open(b / STATE_FILE, "a") as f:
        f.write(line(id="from-b") + "\n")
    git("commit", "-qam", "b", cwd=b)
    git("push", "-q", "origin", "HEAD:main", cwd=b)
    with open(a / STATE_FILE, "a") as f:
        f.write(line(id="from-a") + "\n")
    git("commit", "-qam", "a", cwd=a)
    git("pull", "-q", "--rebase", "origin", "main", cwd=a)
    assert [e["id"] for e in replay((a / STATE_FILE).read_text())] == ["base", "from-b", "from-a"]


def test_protection_monitor_workflow_may_push_state():
    text = (REPO / ".github/workflows/protection-monitor.yml").read_text()
    assert "permissions:\n  contents: write\n" in text
