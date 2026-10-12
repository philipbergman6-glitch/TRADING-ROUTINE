"""Run records (ADR 0012): who ran, on what code, rulebook, instructions and
model, and what came of it, for every routine and protection-monitor run.

    python3 scripts/run_record.py start --routine market-open --trigger cloud \\
        --command-file routines/market-open.md --model <model id>
    python3 scripts/run_record.py finish --action "buy XLK 10" --intent en-20261013-XLK
    python3 scripts/run_record.py finish --monitor-report report.json   # protection monitor

A run is two lines of `kind: "run"` in the committed state store (ADR 0004):
`op: "start"` before the run does anything, `op: "finish"` at its end. `start`
mints the run id, writes it and the code/rulebook/command/model provenance,
and remembers the run id in the checkout's git directory so `finish` (or a
rerun of it) names the same run. A start without a finish is an unfinished
run: the run died or stopped before recording its outcome.

Runs before the first run record are unprovenanced. Nothing here backfills
them: there is no record of which model or commit they used, and inventing
one would be worse than the gap.

Hard-fails on any malformed record, here and for every reader (fold). Exit
codes: 0 recorded · 2 usage or a record that would be malformed · 10 store
unavailable or holding a malformed record (state_store.EXIT_STORE_UNAVAILABLE).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.state_store import (EXIT_STORE_UNAVAILABLE, GitError, StateStore,  # noqa: E402
                                 StoreUnavailable, local_store, new_event, validate)

EXIT_OK, EXIT_USAGE = 0, 2
# The run id `start` minted, kept in the checkout's git directory: never
# committed, and survives the routines' `git reset --hard`.
CURRENT_RUN = "trading-routine-run.json"

KIND = "run"
CLAUDE_ROUTINES = frozenset({"pre-market", "market-open", "midday", "daily-summary", "weekly-review"})
MONITOR = "protection-monitor"
ROUTINES = CLAUDE_ROUTINES | {MONITOR}
# Claude routines run in the cloud (scheduled or "run now"; the run cannot tell
# which) or locally as a slash command; the monitor runs on GitHub Actions.
TRIGGERS = {**{r: frozenset({"cloud", "local"}) for r in CLAUDE_ROUTINES},
            MONITOR: frozenset({"schedule", "workflow_dispatch"})}
MODEL_SOURCES = frozenset({"self-reported", "env:ANTHROPIC_MODEL", "unexposed", "not-applicable"})
OUTCOMES = ("incident", "actions", "refused", "no-trade")
LISTS = ("actions", "refusals", "incidents")
ENVELOPE = ("id", "kind", "at", "writer", "schema")
START_FIELDS = ("op", "run", "routine", "trigger", "code_sha", "code_subject", "code_dirty",
                "rulebook_version", "rulebook_sha256", "rulebook_pinned", "command_file",
                "command_sha256", "model_id", "model_source", "host_ref")
FINISH_FIELDS = ("op", "run", "outcome", *LISTS, "intents")

RUN_ID = re.compile(r"([a-z-]+)-(\d{8}T\d{6}Z)-([0-9a-f]{6})")
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"v\d+(?:\.\d+)?")
# Repo-relative instruction file: no leading slash, no parent hops.
COMMAND_FILE = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]{1,200}")
# ADR 0005 intent ids (en-/cl-) and ADR 0002 stop replace/restore ids (rs-/rr-).
INTENT_ID = re.compile(r"(?:en|cl)-\d{8}-[A-Z0-9]{1,10}(?:-[A-Za-z0-9]{1,8})?|r[sr]-[A-Za-z0-9-]{1,45}")
MAX_TEXT = 500


class MalformedRunRecord(ValueError):
    """A run line, or a sequence of them, that cannot be a true record."""


@dataclass(frozen=True)
class Run:
    run: str
    routine: str
    trigger: str
    started_at: str
    start: dict
    ended_at: str | None = None
    outcome: str | None = None
    actions: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    incidents: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()


def outcome_of(*, actions, refusals, incidents) -> str:
    """The one-word summary: an incident outranks actions, which outrank refusals."""
    if incidents:
        return "incident"
    if actions:
        return "actions"
    if refusals:
        return "refused"
    return "no-trade"


def _bad(event: dict, msg: str):
    raise MalformedRunRecord(f"run record {event.get('id', '?')} ({event.get('run', '?')}): {msg}")


def _texts(event: dict, field: str, pattern: re.Pattern | None = None) -> tuple[str, ...]:
    value = event[field]
    if not isinstance(value, list):
        _bad(event, f"{field!r} must be a list, got {type(value).__name__}")
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_TEXT:
            _bad(event, f"{field!r} entries must be non-empty strings of at most {MAX_TEXT} chars: {item!r}")
        if pattern is not None and not pattern.fullmatch(item):
            _bad(event, f"{field!r} entry {item!r} is not a valid id")
    return tuple(value)


def validate_line(event: dict) -> dict:
    """Return a run line if its fields are exactly right for its op, else raise."""
    op = event.get("op")
    fields = {"start": START_FIELDS, "finish": FINISH_FIELDS}.get(op)
    if fields is None:
        _bad(event, f"'op' must be start or finish, got {op!r}")
    keys, want = set(event), set(ENVELOPE) | set(fields)
    if keys != want:
        _bad(event, f"fields missing {sorted(want - keys)}, unexpected {sorted(keys - want)}")
    run = event["run"]
    m = RUN_ID.fullmatch(run) if isinstance(run, str) else None
    if m is None:
        _bad(event, f"'run' must be <routine>-<YYYYMMDDTHHMMSSZ>-<6 hex>, got {run!r}")
    if event["writer"] != run:
        _bad(event, f"writer {event['writer']!r} is not the run id")
    if op == "finish":
        lists = {f: _texts(event, f) for f in LISTS}
        _texts(event, "intents", INTENT_ID)
        if event["outcome"] != outcome_of(**lists):
            _bad(event, f"outcome {event['outcome']!r} contradicts its lists "
                        f"(expected {outcome_of(**lists)!r})")
        return event

    routine, trigger = event["routine"], event["trigger"]
    if routine not in ROUTINES:
        _bad(event, f"unknown routine {routine!r}")
    if m.group(1) != routine:
        _bad(event, f"run id names {m.group(1)!r}, line names {routine!r}")
    if trigger not in TRIGGERS[routine]:
        _bad(event, f"trigger {trigger!r} is not one of {sorted(TRIGGERS[routine])} for {routine}")
    checks = [
        ("code_sha", lambda v: isinstance(v, str) and SHA1.fullmatch(v)),
        ("code_subject", lambda v: isinstance(v, str) and v.strip() and len(v) <= MAX_TEXT),
        ("code_dirty", lambda v: type(v) is bool),
        ("rulebook_version", lambda v: isinstance(v, str) and VERSION.fullmatch(v)),
        ("rulebook_sha256", lambda v: isinstance(v, str) and SHA256.fullmatch(v)),
        ("rulebook_pinned", lambda v: type(v) is bool),
        ("command_file", lambda v: isinstance(v, str) and COMMAND_FILE.fullmatch(v)),
        ("command_sha256", lambda v: isinstance(v, str) and SHA256.fullmatch(v)),
        ("model_source", lambda v: v in MODEL_SOURCES),
        ("host_ref", lambda v: v is None or (isinstance(v, str) and v.strip() and len(v) <= 200)),
    ]
    for field, ok in checks:
        if not ok(event[field]):
            _bad(event, f"invalid {field!r}: {event[field]!r}")
    model, source = event["model_id"], event["model_source"]
    has_model = isinstance(model, str) and bool(model.strip()) and len(model) <= 100
    if source in ("self-reported", "env:ANTHROPIC_MODEL") and not has_model:
        _bad(event, f"model_source {source!r} needs a model_id, got {model!r}")
    if source in ("unexposed", "not-applicable") and model is not None:
        _bad(event, f"model_source {source!r} must carry model_id null, got {model!r}")
    if (routine == MONITOR) != (source == "not-applicable"):
        _bad(event, f"model_source {source!r} is wrong for {routine}: only the monitor runs no model")
    return event


def fold(events: list[dict]) -> list[Run]:
    """Fold the store's events into runs, in start order. Other kinds are
    ignored. Raises MalformedRunRecord on any bad line or impossible sequence."""
    runs: dict[str, Run] = {}
    for event in events:
        if event.get("kind") != KIND:
            continue
        validate_line(event)
        run_id = event["run"]
        current = runs.get(run_id)
        if event["op"] == "start":
            if current is not None:
                _bad(event, "run started twice")
            runs[run_id] = Run(run_id, event["routine"], event["trigger"], event["at"], event)
            continue
        if current is None:
            _bad(event, "finish with no start")
        if current.ended_at is not None:
            _bad(event, "run finished twice")
        if datetime.fromisoformat(event["at"]) < datetime.fromisoformat(current.started_at):
            _bad(event, "finish is earlier than its start")
        runs[run_id] = Run(current.run, current.routine, current.trigger, current.started_at,
                           current.start, event["at"], event["outcome"],
                           *(tuple(event[f]) for f in (*LISTS, "intents")))
    return list(runs.values())


# --- the writer -----------------------------------------------------------------

class Usage(ValueError):
    """The caller asked for a record that cannot be written."""


def _git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Usage(f"git {args[0]}: {exc}") from None
    if done.returncode != 0:
        raise Usage(f"git {args[0]} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise Usage(f"cannot hash {path}: {exc}") from None


def _rulebook(root: Path) -> tuple[str, str, bool]:
    """(declared version, sha256 of the file, whether the pin matches). An
    unpinned rulebook is recorded as such; strategy_version.py is the gate."""
    from scripts.strategy_version import declared_version, rulebook_sha256
    try:
        text = (root / "memory" / "TRADING-STRATEGY.md").read_text(encoding="utf-8")
        pins = json.loads((root / "docs" / "rulebook-pins.json").read_text(encoding="utf-8"))
        version = declared_version(text)
    except (OSError, ValueError) as exc:
        raise Usage(f"rulebook unreadable: {exc}") from None
    digest = rulebook_sha256(text)
    pin = pins.get(version) if isinstance(pins, dict) else None
    return version, digest, isinstance(pin, dict) and pin.get("sha256") == digest


def _model(routine: str, flag: str | None, environ: Mapping[str, str]) -> tuple[str | None, str]:
    """No environment we run in is known to expose the model id (ADR 0012):
    a Claude routine reports the id from its own system prompt."""
    if routine == MONITOR:
        if flag is not None:
            raise Usage("the protection monitor runs no model; drop --model")
        return None, "not-applicable"
    if flag is not None:
        return flag, "self-reported"
    if environ.get("ANTHROPIC_MODEL"):
        return environ["ANTHROPIC_MODEL"], "env:ANTHROPIC_MODEL"
    return None, "unexposed"


def _host_ref(environ: Mapping[str, str]) -> str | None:
    if environ.get("GITHUB_RUN_ID"):
        return f"github-actions:{environ['GITHUB_RUN_ID']}/{environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    if environ.get("CLAUDE_CODE_SESSION_ID"):
        return f"claude-code-session:{environ['CLAUDE_CODE_SESSION_ID']}"
    return None


def monitor_lists(path: Path) -> dict[str, list[str]]:
    """Actions, refusals and incidents from scripts/protection_monitor.py's JSON
    report. A report that is missing or unreadable is recorded as the incident:
    the finish must still land, and the job fails on the monitor's own exit."""
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(report, dict) or type(report.get("exit")) is not int:
            raise ValueError("not a monitor report object with an integer exit")
        actions = [f"{r['kind']} {r['symbol']} -> {r['state']}" for r in report.get("results", [])]
        refusals = [str(h) for h in report.get("holds", [])]
        incidents = [str(i) for i in report.get("coverage", {}).get("issues", [])]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"actions": [], "refusals": [], "incidents": [f"monitor wrote no readable report: {exc}"[:MAX_TEXT]]}
    if "coverage" not in report and report.get("state"):
        incidents.append(str(report["state"]))
    if report["exit"] != 0:
        incidents.append(f"monitor exit {report['exit']}")
    # A record that fails validation would leave the run unfinished; cut long text.
    return {k: [t[:MAX_TEXT] for t in v]
            for k, v in (("actions", actions), ("refusals", refusals), ("incidents", incidents))}


def _current_file(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--absolute-git-dir").strip()) / CURRENT_RUN


def _checked(line: dict, prior: list[dict]) -> dict:
    """Validate the line as every reader will, against what is already stored."""
    try:
        fold(prior + [validate(line)])
    except ValueError as exc:
        raise Usage(str(exc)) from None
    return line


def _stored(store: StateStore) -> tuple:
    snap = store.fetch()
    try:
        fold(snap.events)
    except MalformedRunRecord as exc:
        raise StoreUnavailable(f"store holds a malformed run record: {exc}") from None
    return snap


def start(store: StateStore, repo: Path, *, routine: str, trigger: str, command_file: str,
          model: str | None, environ: Mapping[str, str]) -> dict:
    if routine not in ROUTINES:
        raise Usage(f"unknown routine {routine!r}; one of {sorted(ROUTINES)}")
    if not COMMAND_FILE.fullmatch(command_file):
        raise Usage(f"--command-file must be a repo-relative path, got {command_file!r}")
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = f"{routine}-{stamp}-{secrets.token_hex(3)}"
    version, digest, pinned = _rulebook(root)
    model_id, source = _model(routine, model, environ)
    line = new_event(KIND, run, op="start", run=run, routine=routine, trigger=trigger,
                     code_sha=_git(repo, "rev-parse", "HEAD").strip(),
                     code_subject=_git(repo, "log", "-1", "--format=%s").strip(),
                     code_dirty=bool(_git(repo, "status", "--porcelain").strip()),
                     rulebook_version=version, rulebook_sha256=digest, rulebook_pinned=pinned,
                     command_file=command_file, command_sha256=_sha256(root / command_file),
                     model_id=model_id, model_source=source, host_ref=_host_ref(environ))
    snap = _stored(store)
    store.commit(snap, [_checked(line, snap.events)], writer=run, intent="run-start")
    _current_file(repo).write_text(json.dumps({"run": run}), encoding="utf-8")
    return line


def finish(store: StateStore, repo: Path, *, run: str | None, actions: list[str],
           refusals: list[str], incidents: list[str], intents: list[str]) -> dict:
    current = _current_file(repo)
    if run is None:
        try:
            run = json.loads(current.read_text(encoding="utf-8"))["run"]
        except FileNotFoundError:
            raise Usage("no run started in this checkout; pass --run <id>") from None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Usage(f"unreadable {current}: {exc}") from None
    line = new_event(KIND, run, op="finish", run=run,
                     outcome=outcome_of(actions=actions, refusals=refusals, incidents=incidents),
                     actions=actions, refusals=refusals, incidents=incidents, intents=intents)
    snap = _stored(store)
    store.commit(snap, [_checked(line, snap.events)], writer=run, intent="run-finish")
    current.unlink(missing_ok=True)
    return line


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="the run's checkout; its origin is the store")
    parser.add_argument("--local", action="store_true",
                        help="write through the dedicated local clone (ADR 0004 section 3)")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="record that a run began, before it does anything")
    s.add_argument("--routine", required=True)
    s.add_argument("--trigger", required=True)
    s.add_argument("--command-file", required=True, help="repo-relative instruction file the run follows")
    s.add_argument("--model", help="model id, as the agent's own system prompt states it")
    f = sub.add_parser("finish", help="record what the run did; outcome is derived")
    f.add_argument("--run", help="run id (default: the one start remembered in this checkout)")
    f.add_argument("--action", action="append", default=[], help="broker mutation done (repeatable)")
    f.add_argument("--refusal", action="append", default=[], help="action the rules refused (repeatable)")
    f.add_argument("--incident", action="append", default=[], help="something that went wrong (repeatable)")
    f.add_argument("--intent", action="append", default=[], help="intent id this run created (repeatable)")
    f.add_argument("--monitor-report", help="protection monitor JSON report to derive the lists from")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    try:
        if args.local:
            store = local_store(_git(repo, "remote", "get-url", "origin").strip())
        else:
            store = StateStore(repo)
        if args.command == "start":
            line = start(store, repo, routine=args.routine, trigger=args.trigger,
                         command_file=args.command_file, model=args.model, environ=environ)
        else:
            lists = {"actions": args.action, "refusals": args.refusal, "incidents": args.incident}
            if args.monitor_report:
                report = monitor_lists(Path(args.monitor_report))
                lists = {k: lists[k] + report[k] for k in LISTS}
            line = finish(store, repo, run=args.run, intents=args.intent, **lists)
        print(json.dumps({"state": "recorded", "op": line["op"], "run": line["run"],
                          **({"outcome": line["outcome"]} if "outcome" in line else {})}))
        return EXIT_OK
    except StoreUnavailable as exc:
        print(json.dumps({"state": "store_unavailable", "exit": EXIT_STORE_UNAVAILABLE,
                          "reason": str(exc)}), file=sys.stderr)
        return EXIT_STORE_UNAVAILABLE
    except (Usage, ValueError, GitError) as exc:
        print(json.dumps({"state": "usage", "exit": EXIT_USAGE, "reason": str(exc)}), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
