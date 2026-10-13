"""Committed state store (ADR 0004): durable intent as append-only JSONL on
`main`, with `git push` as the compare-and-swap.

Every line is one event carrying the envelope `id`, `kind`, `at` (UTC
ISO-8601), `writer` (routine or workflow plus run id) and `schema` (integer).
Current state is a replay of the file. Record kinds and the rules that say
which claim wins are the coordinator's (ADR 0010, scripts/coordinator.py); this
module ships the envelope and the mechanics only.

Fail closed: a fetch that fails, a push budget that runs out, a line that fails
validation, or a claim that no longer wins after a rebase all raise
StoreUnavailable, and the CLI exits EXIT_STORE_UNAVAILABLE. There is no flag to
continue without the store.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

STATE_FILE = "state/events.jsonl"
EXIT_OK, EXIT_USAGE, EXIT_STORE_UNAVAILABLE = 0, 2, 10
ENVELOPE = ("id", "kind", "at", "writer", "schema")
GIT_TIMEOUT_S = 60
# Local mode (ADR 0004 §3): a dedicated bare clone, never the dev checkout.
LOCAL_CLONE = Path.home() / ".cache" / "trading-routine" / "state.git"
# Pushes tried before failing closed (ADR 0010 section 2).
PUSH_BUDGET = 5
# A claim that lost after a rebase is withdrawn by an event listing its line
# ids; replay ignores every listed line. Not a lease release (ADR 0010).
WITHDRAW_KIND = "withdraw"
TOKEN = re.compile(r"\S+")
# How far back on main a pushed subject is looked for when verifying.
VERIFY_DEPTH = 200
FALLBACK_IDENTITY = {"GIT_AUTHOR_NAME": "trading-routine state store",
                     "GIT_AUTHOR_EMAIL": "state-store@trading-routine.invalid",
                     "GIT_COMMITTER_NAME": "trading-routine state store",
                     "GIT_COMMITTER_EMAIL": "state-store@trading-routine.invalid"}


class StoreUnavailable(Exception):
    """The store cannot be reached or trusted; refuse the mutation (ADR 0004 §1)."""


class CorruptState(StoreUnavailable):
    """A line of the state file fails the envelope; a hard failure for every reader."""


class ClaimLost(StoreUnavailable):
    """After a rebase the caller's claim no longer wins; a withdraw line was
    pushed (if the budget allowed) and the writer must not act on the claim."""


def validate(event: object) -> dict:
    """Return `event` if it carries a valid envelope, else raise ValueError."""
    if not isinstance(event, dict):
        raise ValueError(f"event must be a JSON object, got {type(event).__name__}")
    for field in ENVELOPE:
        if field not in event:
            raise ValueError(f"missing envelope field {field!r}")
    for field in ("id", "kind", "writer"):
        value = event[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field!r} must be a non-empty string, got {value!r}")
    schema = event["schema"]
    if type(schema) is not int or schema < 1:
        raise ValueError(f"'schema' must be a positive integer, got {schema!r}")
    at = event["at"]
    try:
        stamp = datetime.fromisoformat(at) if isinstance(at, str) else None
    except ValueError:
        stamp = None
    if stamp is None or stamp.utcoffset() != timedelta(0):
        raise ValueError(f"'at' must be a UTC ISO-8601 timestamp, got {at!r}")
    return event


def new_event(kind: str, writer: str, **fields) -> dict:
    """A fresh event: unique id, `at` = now in UTC, schema 1, plus `fields`."""
    clash = set(fields) & set(ENVELOPE)
    if clash:
        raise ValueError(f"envelope fields are minted, not passed: {sorted(clash)}")
    return validate({"id": uuid.uuid4().hex, "kind": kind,
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "writer": writer, "schema": 1, **fields})


def encode(event: dict) -> str:
    return json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"


def replay(text: str) -> list[dict]:
    """Parse the state file into events, in file order. Any invalid line, a
    duplicate id or a torn final line raises CorruptState naming the line."""
    if text == "":
        return []
    if not text.endswith("\n"):
        raise CorruptState(f"{STATE_FILE}: missing final newline (torn write)")
    events: list[dict] = []
    seen: set[str] = set()
    for number, raw in enumerate(text[:-1].split("\n"), start=1):
        try:
            event = validate(json.loads(raw))
        except ValueError as exc:  # JSONDecodeError is a ValueError
            raise CorruptState(f"{STATE_FILE} line {number}: {exc}") from None
        if event["id"] in seen:
            raise CorruptState(f"{STATE_FILE} line {number}: duplicate id {event['id']!r}")
        seen.add(event["id"])
        events.append(event)
    return events


@dataclass(frozen=True)
class Snapshot:
    """The state file as `main` on origin held it at commit `base`."""
    base: str
    text: str
    events: list[dict]


@dataclass(frozen=True)
class Committed:
    """A verified write: `subject` is on origin's main and `events` is the
    replay that confirmed it, after `attempts` pushes."""
    subject: str
    attempts: int
    events: list[dict]


class GitError(Exception):
    pass


class StateStore:
    """The store as seen through one git repository whose `origin` is the
    shared remote. Reads and writes go through git plumbing against fetched
    commits, so the repository's HEAD, index and working tree are never
    touched; a bare clone (local mode) works the same as a routine checkout."""

    def __init__(self, repo: Path | str, remote: str = "origin", branch: str = "main"):
        self.repo = Path(repo)
        self.remote = remote
        self.branch = branch

    def _git(self, *args: str, stdin: str | None = None, env: dict | None = None) -> str:
        # Bytes in, strict UTF-8 out: no newline translation can hide a torn line.
        try:
            done = subprocess.run(
                ["git", *args], cwd=self.repo, capture_output=True, timeout=GIT_TIMEOUT_S,
                input=None if stdin is None else stdin.encode("utf-8"),
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError(f"git {args[0]}: {exc}") from None
        if done.returncode != 0:
            raise GitError(f"git {args[0]} exited {done.returncode}: "
                           f"{done.stderr.decode('utf-8', 'replace').strip()}")
        try:
            return done.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitError(f"git {args[0]}: output is not UTF-8: {exc}") from None

    def fetch(self) -> Snapshot:
        """`git fetch <remote> <branch>`, then replay the state file at FETCH_HEAD."""
        try:
            self._git("fetch", "-q", self.remote, self.branch)
            base = self._git("rev-parse", "--verify", "FETCH_HEAD^{commit}").strip()
        except GitError as exc:
            raise StoreUnavailable(f"fetch {self.remote}/{self.branch} failed: {exc}") from None
        text = self._read(base)
        return Snapshot(base, text, replay(text))

    def _read(self, commit: str) -> str:
        try:
            listed = self._git("ls-tree", commit, "--", STATE_FILE)
            if not listed.strip():
                return ""
            return self._git("cat-file", "blob", f"{commit}:{STATE_FILE}")
        except GitError as exc:
            raise StoreUnavailable(f"reading {STATE_FILE} at {commit[:12]}: {exc}") from None

    def commit(self, snapshot: Snapshot, lines: list[dict], *, writer: str, intent: str,
               still_wins: Callable[[list[dict]], bool] = lambda events: True,
               budget: int = PUSH_BUDGET) -> Committed:
        """Append `lines` on top of `snapshot.base` and push to main (ADR 0004 §2).

        The push is the compare-and-swap: it is rejected if main moved since
        the snapshot. On rejection the store refetches, rebases the lines onto
        the new tip and asks `still_wins(replayed events + lines)` again. When
        the claim no longer wins, a withdraw line is appended, pushed, and
        ClaimLost is raised. After `budget` pushes, or on any fetch failure,
        StoreUnavailable is raised. Success is verified by subject on main."""
        if not lines:
            raise ValueError("nothing to commit")
        for value, name in ((writer, "writer"), (intent, "intent")):
            if not isinstance(value, str) or not TOKEN.fullmatch(value):
                raise ValueError(f"{name} must be one whitespace-free token, got {value!r}")
        if type(budget) is not int or budget < 1:
            raise ValueError(f"budget must be a positive integer, got {budget!r}")
        ours = [validate(dict(e)) for e in lines]
        ids = [e["id"] for e in ours]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate ids in lines")
        if set(ids) & {e["id"] for e in snapshot.events}:
            raise ValueError("lines already present in the snapshot")
        subject = f"state: {writer} {intent} [skip ci]"

        snap, lost = snapshot, False
        for attempt in range(1, budget + 1):
            if not lost and not still_wins(snap.events + ours):
                lost = True
                ours = ours + [new_event(WITHDRAW_KIND, writer, intent=intent, withdraws=ids)]
            try:
                commit = self._build(snap, ours, subject)
            except GitError as exc:
                raise StoreUnavailable(f"building the state commit: {exc}") from None
            try:
                self._push(commit)
            except GitError as exc:
                rejection = str(exc)
                snap = self.fetch()
                if not self._landed(snap, ours):
                    continue
            else:
                snap = self.fetch()
            self._verify(snap, ours, subject)
            if lost:
                raise ClaimLost(f"{intent}: claim lost to a concurrent writer; withdraw pushed")
            return Committed(subject, attempt, snap.events)
        raise StoreUnavailable(f"{intent}: push budget of {budget} exhausted; last: {rejection}")

    def _build(self, snap: Snapshot, lines: list[dict], subject: str) -> str:
        blob = self._git("hash-object", "-w", "--stdin",
                         stdin=snap.text + "".join(encode(e) for e in lines)).strip()
        with tempfile.TemporaryDirectory() as tmp:
            index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self._git("read-tree", snap.base, env=index)
            self._git("update-index", "--add", "--cacheinfo", f"100644,{blob},{STATE_FILE}", env=index)
            tree = self._git("write-tree", env=index).strip()
        try:
            self._git("var", "GIT_COMMITTER_IDENT")
            ident = None
        except GitError:
            ident = FALLBACK_IDENTITY
        return self._git("commit-tree", tree, "-p", snap.base, "-m", subject, env=ident).strip()

    def _push(self, commit: str) -> None:
        self._git("push", "-q", self.remote, f"{commit}:refs/heads/{self.branch}")

    @staticmethod
    def _landed(snap: Snapshot, lines: list[dict]) -> bool:
        """True if every line is on main (a push whose response was lost)."""
        present = {e["id"] for e in snap.events}
        landed = [e["id"] in present for e in lines]
        if any(landed) and not all(landed):
            raise StoreUnavailable("only part of the commit is on main; refusing to guess")
        return all(landed)

    def _verify(self, snap: Snapshot, lines: list[dict], subject: str) -> None:
        """By subject, never SHA: the cloud proxy rewrites commit SHAs."""
        try:
            recent = self._git("log", f"-n{VERIFY_DEPTH}", "--format=%s", snap.base).splitlines()
        except GitError as exc:
            raise StoreUnavailable(f"verifying push: {exc}") from None
        if subject not in recent or not self._landed(snap, lines):
            raise StoreUnavailable(f"push not verified: {subject!r} is not on {self.branch}")


def local_store(remote_url: str, path: Path | str = LOCAL_CLONE) -> StateStore:
    """The store for local `/trade`: a dedicated bare clone at `path` whose
    origin is `remote_url`, created on first use. Writes push straight to
    main (the one exception to #71); the development checkout is not used."""
    path = Path(path)
    store = StateStore(path)
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True,
                           capture_output=True, timeout=GIT_TIMEOUT_S)
            store._git("remote", "add", "origin", remote_url)
        current = store._git("remote", "get-url", "origin").strip()
    except (OSError, subprocess.SubprocessError, GitError) as exc:
        raise StoreUnavailable(f"local clone {path}: {exc}") from None
    if current != remote_url:
        raise StoreUnavailable(f"local clone {path} has remote {current!r}, expected {remote_url!r}")
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="git repository whose origin is the store")
    parser.add_argument("--local", action="store_true",
                        help=f"write through the dedicated clone at {LOCAL_CLONE} (local /trade)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("replay", help="fetch main and print every event as JSONL")
    append = sub.add_parser("append", help="append one event and push it to main")
    append.add_argument("--writer", required=True, help="routine or workflow plus run id")
    append.add_argument("--intent", required=True, help="id named in the commit subject")
    append.add_argument("--kind", required=True)
    append.add_argument("--fields", default="{}", help="JSON object of extra fields")
    args = parser.parse_args(argv)

    try:
        if args.local:
            try:
                url = StateStore(args.repo)._git("remote", "get-url", "origin").strip()
            except GitError as exc:
                raise StoreUnavailable(f"no origin to clone for local mode: {exc}") from None
            store = local_store(url)
        else:
            store = StateStore(args.repo)
        if args.command == "replay":
            for event in store.fetch().events:
                sys.stdout.write(encode(event))
            return EXIT_OK
        fields = json.loads(args.fields)
        if not isinstance(fields, dict):
            raise ValueError("--fields must be a JSON object")
        event = new_event(args.kind, args.writer, **fields)
        done = store.commit(store.fetch(), [event], writer=args.writer, intent=args.intent)
        print(json.dumps({"state": "committed", "subject": done.subject, "id": event["id"],
                          "attempts": done.attempts}))
        return EXIT_OK
    except StoreUnavailable as exc:
        print(json.dumps({"state": "store_unavailable", "exit": EXIT_STORE_UNAVAILABLE,
                          "reason": str(exc)}), file=sys.stderr)
        return EXIT_STORE_UNAVAILABLE
    except ValueError as exc:
        print(json.dumps({"state": "usage", "exit": EXIT_USAGE, "reason": str(exc)}), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
