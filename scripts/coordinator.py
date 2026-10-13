#!/usr/bin/env python3
"""The coordinator (ADR 0010): one account-wide lease, intents recorded before
the broker sees them, reservations derived from those intents, and recovery
that only restores coverage.

Every broker mutation goes through `coordinate(body, ...)`. The entry, exit and
stop-change helpers (`submit_entry.py`, `close_position.py`,
`replace_stop.py`; the protection monitor acts only through `replace_stop.py`)
call it with their own logic as `body(session)`. One call is one
**coordinated action**:

  1. Acquire. Fetch and replay `state/events.jsonl`. A live holder is waited
     on (poll every 15 s, never mutating meanwhile); a lease past
     `expires_at` + 2 min is taken over with `supersedes`.
  2. Recover every non-terminal intent against the broker (section 4 table).
     The only mutation allowed is restoring a canceled stop with
     `rr-<canceled id>`; that result is pushed before anything else.
  3. The body validates with `session.reservations()` (attempt statuses are
     read before account and positions), then `session.record()` pushes
     acquire + recovery + the intent as `recorded`, or `session.refuse()`
     pushes it as `refused`.
  4. The body submits through `session.run` / `session.post`, which refuse any
     mutation after the 5-minute deadline. `session.post` owns the
     lost-response budget (research 0007): re-POST the same attempt id, a
     422 "must be unique" proves the order exists.
  5. Push 2: the intent's outcome, settled from broker state, plus `release`.
     A failed push 2 after the broker acted exits EXIT_NOT_RECORDED and alerts.

Fail closed (ADR 0004 section 1): with the store unreachable every mutation is
refused (EXIT_STORE_UNAVAILABLE) except placing a stop on a held position that
has none (`record(..., restoration=True)`), which proceeds and alerts.

    python3 scripts/coordinator.py status    # read-only: lease, non-terminal intents, takeovers
    python3 scripts/coordinator.py recover   # one recovery-only coordinated action

Exit codes (JSON on stdout): 0 ok · 8 recovery could not restore coverage ·
10 store unavailable · 11 lease wait exhausted · 12 acted, outcome not recorded.

Fault injection for drills (#112): COORDINATOR_FAULT=<point> kills the process
(exit 97) at that point; honoured only with ALPACA_PROFILE=drill and a hard
failure anywhere else. Points: FAULT_POINTS. `lose_response` does not kill:
it discards the first POST's answer and the first lookup, so a real landed
order goes through the lost-response path (re-POST, 422, adopt).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from typing import Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine import Reservation  # noqa: E402
from risk_engine.reconciliation import reconcile_protection  # noqa: E402
from scripts.execution_identity import walk_attempts  # noqa: E402
from scripts.state_store import (EXIT_STORE_UNAVAILABLE, ClaimLost, CorruptState, StateStore,  # noqa: E402
                                 StoreUnavailable, WITHDRAW_KIND, local_store, new_event, validate)

ROOT = Path(__file__).resolve().parent.parent
EMAIL = Path(__file__).resolve().parent / "email.sh"
LEASE_KIND, INTENT_KIND = "lease", "intent"
MUTATION_DEADLINE = timedelta(minutes=5)
LEASE_TTL = timedelta(minutes=10)
SKEW = timedelta(minutes=2)
POLL_S = 15
# Expiry plus skew bounds one wait; one extra poll covers a takeover race.
MAX_WAIT = LEASE_TTL + SKEW + timedelta(seconds=POLL_S)
PUSH_BUDGET = 5
# Lost-response budget (research 0007 leaves it to the repo): re-POSTs of the
# same attempt id, LOST_WAIT_S apart, before the intent is recorded `lost`.
LOST_REPOSTS, LOST_WAIT_S = 3, 5
EXIT_OK, EXIT_UNPROTECTED = 0, 8
EXIT_LEASE_WAIT, EXIT_NOT_RECORDED = 11, 12
EXIT_FAULT = 97
RESTORE_PREFIX = "rr-"
REPLACE_PREFIX = "rs-"

ACTIONS = frozenset({"entry", "close", "replace_stop"})
NON_TERMINAL = frozenset({"recorded", "acknowledged", "lost"})
STATES = NON_TERMINAL | {"refused", "filled", "complete", "dead"}
TRANSITIONS = {
    None: frozenset({"recorded", "refused"}),
    "recorded": frozenset({"acknowledged", "lost", "filled", "complete", "dead"}),
    "acknowledged": frozenset({"filled", "complete", "dead"}),
    "lost": frozenset({"acknowledged", "filled", "complete", "dead"}),
    "filled": frozenset({"complete"}),
}
DEAD_REASONS = frozenset({"attempts_dead", "not_landed", "holder_died", "restored"})
ENTRY_DEAD = frozenset({"canceled", "expired", "rejected", "replaced"})
CLOSE_DEAD = frozenset({"canceled", "expired", "rejected"})
STOP_OPEN = frozenset({"new", "accepted", "pending_new", "held", "accepted_for_bidding"})
STOP_LIVE = frozenset({"new", "accepted", "pending_new"})
BUY_LIVE = frozenset({"accepted", "new", "partially_filled", "pending_new", "held"})
FAULT_POINTS = frozenset({"after_recovery_push", "after_record", "after_cancel", "after_post", "before_release",
                          "lose_response"})
NY = ZoneInfo("America/New_York")
SESSION_CLOSE = dtime(16, 0)


class Outcome(Exception):
    """How a helper ended: exit code, state and JSON detail."""

    def __init__(self, code, state, **detail):
        super().__init__(state)
        self.code, self.state, self.detail = code, state, detail


class _Contended(Exception):
    """Our acquire turned void after a rebase: wait for the lease again."""


# --- replay: the lease head, the holder, and every intent's state ----------------

def _bad(event, msg):
    raise CorruptState(f"{event.get('kind')} line {event.get('id')}: {msg}")


def _utc(text, event, name):
    try:
        stamp = datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        stamp = None
    if stamp is None or stamp.utcoffset() != timedelta(0):
        _bad(event, f"{name} must be a UTC ISO-8601 timestamp, got {text!r}")
    return stamp


def _text(event, name, *, optional=False):
    value = event.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        _bad(event, f"{name!r} must be a non-empty string, got {value!r}")
    return value


def _positive(event, name):
    value = _text(event, name)
    try:
        number = Decimal(value)
    except InvalidOperation:
        _bad(event, f"{name!r} is not a number: {value!r}")
    if not number.is_finite() or number <= 0:
        _bad(event, f"{name!r} must be positive, got {value!r}")
    return number


@dataclass
class IntentView:
    intent: str
    action: str
    symbol: str
    state: str
    lines: list = field(default_factory=list)

    @property
    def first(self) -> dict:
        return self.lines[0]

    @property
    def last(self) -> dict:
        return self.lines[-1]

    @property
    def lease(self) -> str:
        return self.last["lease"]


@dataclass
class View:
    """The store's execution state after replay (ADR 0010 section 2)."""
    head: str | None = None
    holder: dict | None = None
    intents: dict = field(default_factory=dict)
    valid: set = field(default_factory=set)
    void: set = field(default_factory=set)
    takeovers: list = field(default_factory=list)
    superseded: set = field(default_factory=set)

    def non_terminal(self) -> list[IntentView]:
        return [iv for iv in self.intents.values() if iv.state in NON_TERMINAL]

    def state_of(self, intent: str) -> str | None:
        iv = self.intents.get(intent)
        return iv.state if iv else None

    def _lease(self, e):
        op = e.get("op")
        if op not in ("acquire", "release"):
            _bad(e, f"op must be acquire or release, got {op!r}")
        lease = _text(e, "lease")
        if "prev" not in e or not (e["prev"] is None or isinstance(e["prev"], str)):
            _bad(e, "prev must be a lease line id or null")
        if op == "release":
            if self.holder is not None and lease == self.holder["id"]:
                self.head, self.holder = e["id"], None
                self.valid.add(e["id"])
            else:
                self.void.add(e["id"])
            return
        if lease != e["id"]:
            _bad(e, "an acquire names itself as the lease")
        if _utc(e.get("expires_at"), e, "expires_at") <= _utc(e["at"], e, "at"):
            _bad(e, "expires_at must be after at")
        supersedes = _text(e, "supersedes", optional=True)
        if e["prev"] == self.head and (self.holder is None or supersedes == self.holder["id"]):
            if self.holder is not None:
                self.takeovers.append(e)
                self.superseded.add(self.holder["id"])
            self.head, self.holder = e["id"], e
            self.valid.add(e["id"])
        else:
            self.void.add(e["id"])

    def _intent(self, e):
        intent, lease, state = _text(e, "intent"), _text(e, "lease"), e.get("state")
        if state not in STATES:
            _bad(e, f"unknown intent state {state!r}")
        if self.holder is None or lease != self.holder["id"]:
            self.void.add(e["id"])
            return
        iv = self.intents.get(intent)
        before = iv.state if iv else None
        if state not in TRANSITIONS.get(before, ()):
            _bad(e, f"illegal transition {before} -> {state} for {intent}")
        if iv is None:
            action = e.get("action")
            if action not in ACTIONS:
                _bad(e, f"action must be one of {sorted(ACTIONS)}, got {action!r}")
            iv = IntentView(intent, action, _text(e, "symbol"), state)
            if state == "recorded" and action == "entry":
                _positive(e, "qty"), _positive(e, "price")
                _text(e, "sector", optional=True)
            if state == "recorded" and action != "entry":
                cancels = e.get("cancels")
                if not isinstance(cancels, list) or not all(isinstance(c, str) and c for c in cancels):
                    _bad(e, "cancels must be a list of broker order ids")
            if state == "refused":
                reasons = e.get("reasons")
                if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) for r in reasons):
                    _bad(e, "a refusal lists its reasons")
            self.intents[intent] = iv
        elif state == "complete" and before == "filled":
            if iv.action != "close" or iv.lease != lease:
                _bad(e, "filled -> complete is a close's, in the same push")
        if state == "dead" and e.get("reason") not in DEAD_REASONS:
            _bad(e, f"dead needs a reason in {sorted(DEAD_REASONS)}, got {e.get('reason')!r}")
        iv.state = state
        iv.lines.append(e)
        self.valid.add(e["id"])


def fold(events: list[dict]) -> View:
    """Replay lease, intent and withdraw lines; every other kind is ignored.
    Replay never reads a clock: staleness is the taker's judgement."""
    withdrawn: set[str] = set()
    for e in events:
        if e["kind"] == WITHDRAW_KIND:
            ids = e.get("withdraws")
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                _bad(e, "withdraws must list line ids")
            withdrawn |= set(ids)
    view = View()
    for e in events:
        if e["kind"] not in (LEASE_KIND, INTENT_KIND):
            continue
        if e["id"] in withdrawn:
            view.void.add(e["id"])
        elif e["kind"] == LEASE_KIND:
            view._lease(e)
        else:
            view._intent(e)
    return view


def stale(holder: dict, now: datetime) -> bool:
    return now > datetime.fromisoformat(holder["expires_at"]) + SKEW


# --- broker views shared by recovery, settlement and the validators ----------

def live_coverage(read, symbol: str, now: datetime, positions=None, orders=None):
    """Held-vs-verified-protection for one symbol from current broker snapshots.

    Returns (position, report) or (None, None) when the symbol is not held. The
    report is risk_engine.reconciliation's: ok only when unexpired GTC stops resting
    as `new` cover the full held quantity. A stop that is held, pending, expired,
    short, or malformed does not certify coverage -- nor does a truncated order list.
    Snapshots already read by the caller may be passed in to avoid a second read.
    """
    positions = read("positions") if positions is None else positions
    orders = read("orders", "open") if orders is None else orders
    if not isinstance(positions, list):
        raise ValueError("positions snapshot is not a list")
    if not isinstance(orders, list):
        raise ValueError("open-order snapshot is not a list")
    mine = [p for p in positions if isinstance(p, dict) and str(p.get("symbol", "")).upper() == symbol]
    if not mine:
        return None, None
    return mine[0], reconcile_protection(mine, orders, now)


def live_buys(orders, symbol):
    return [o for o in orders if isinstance(o, dict) and str(o.get("symbol", "")).upper() == symbol
            and o.get("side") == "buy" and o.get("status") in BUY_LIVE]


def _qty(value) -> Decimal:
    return Decimal(str(value or 0))


def entry_unfilled(read, iv: IntentView) -> Decimal:
    """Shares a non-terminal entry intent still reserves, from its attempts at the
    broker: all of them when no attempt is found, the unfilled part of a live one,
    none once anything filled (the broker's own state then carries it)."""
    res = walk_attempts(read, iv.intent, ENTRY_DEAD)
    qty = _qty(iv.first["qty"])
    if res.order is not None:
        if res.order.get("status") == "filled":
            return Decimal(0)
        return max(qty - _qty(res.order.get("filled_qty")), Decimal(0))
    if any(_qty((read("order-by-client", d["client_order_id"]) or {}).get("filled_qty")) > 0 for d in res.dead):
        return Decimal(0)
    return qty


def reservations_of(view: View, unfilled: dict, exclude: str | None = None) -> tuple[Reservation, ...]:
    out = []
    for iv in view.non_terminal():
        if iv.action != "entry" or iv.intent == exclude:
            continue
        qty = unfilled[iv.intent]
        if qty > 0:
            out.append(Reservation(intent_id=iv.intent, symbol=iv.symbol, qty=qty,
                                   price=iv.first["price"], sector=iv.first.get("sector")))
    return tuple(out)


def store_reservations(store: StateStore, read, exclude: str | None = None) -> tuple[Reservation, ...]:
    """Reservations for a buy decision outside a coordinated action
    (validate_order.py, validate_mutation.py). Attempt statuses are read here,
    so call this before account and positions (ADR 0010 section 6). Raises
    StoreUnavailable when the store cannot be read: buys are then refused."""
    view = fold(store.fetch().events)
    unfilled = {iv.intent: entry_unfilled(read, iv) for iv in view.non_terminal()
                if iv.action == "entry" and iv.intent != exclude}
    return reservations_of(view, unfilled, exclude)


def intent_of_attempt(client_order_id: str) -> str:
    """en-20261012-AMD-r2 -> en-20261012-AMD (ADR 0005 attempt suffix)."""
    return re.sub(r"-r\d+$", "", client_order_id)


def session_closed_since(at: datetime, now: datetime) -> bool:
    """True once a regular session close (16:00 New York, weekdays) has passed
    since `at`. Exchange holidays and early closes are not modelled: a holiday
    makes this fire one session early for a POST lost outside market hours."""
    day = at.astimezone(NY).date()
    while True:
        close = datetime.combine(day, SESSION_CLOSE, NY)
        if close > at and day.weekday() < 5:
            return now >= close
        day += timedelta(days=1)


# --- reconciliation: one intent against the broker ----------------------------

@dataclass(frozen=True)
class Transition:
    state: str
    fields: dict = field(default_factory=dict)
    restore: tuple = ()        # recovery only: canceled stop ids to re-place first


def _protective_gap(read, iv, now, seen=None):
    """(held, uncovered, canceled stop ids) for a close or replace-stop intent.
    An uncovered symbol is added to `seen` (drives ADR 0006 classification)."""
    held, coverage = live_coverage(read, iv.symbol, now)
    if held is not None and not coverage["ok"] and seen is not None:
        seen.add(iv.symbol)
    canceled = []
    for sid in iv.first.get("cancels", []):
        old = read("order-info", sid)
        if isinstance(old, dict) and old.get("status") == "canceled":
            canceled.append(sid)
    return held is not None, held is not None and not coverage["ok"], canceled


def _close_done(read, symbol, now) -> bool:
    """ADR 0005 section 3: not held and no buy for the symbol live."""
    orders = read("orders", "open")
    held, _ = live_coverage(read, symbol, now, orders=orders)
    return held is None and not live_buys(orders, symbol)


def reconcile(iv: IntentView, read, now: datetime, *, sent: str | None = None, recovering: bool,
              unfilled: dict | None = None, holder_gone: bool = True, seen: set | None = None) -> Transition | None:
    """The state `iv` moves to given broker state, or None to stay.

    `recovering` is True when another writer reconciles `iv` (ADR 0010
    section 4); `holder_gone` says whether the writer that recorded it is
    provably past its last possible POST (lease superseded, or expiry + skew
    elapsed since the line); until then "no attempt found" proves nothing and
    a `recorded` intent stays as it is. False when the live writer settles its
    own intent, with `sent` describing its last POST: None (nothing sent),
    "refused" (proven not to have landed) or "unknown" (sent, outcome unseen)."""
    if iv.action == "entry":
        res = walk_attempts(read, iv.intent, ENTRY_DEAD)
        found = {"client_order_id": res.client_order_id} if res.order is not None else {}
        if res.order is not None and res.order.get("status") == "filled":
            return Transition("filled", {**found, "filled_qty": str(res.order.get("filled_qty"))})
        if res.order is not None:
            if unfilled is not None:
                unfilled[iv.intent] = max(_qty(iv.first["qty"]) - _qty(res.order.get("filled_qty")), Decimal(0))
            return None if iv.state == "acknowledged" else Transition(
                "acknowledged", {**found, "filled_qty": str(res.order.get("filled_qty") or "0")})
        for d in res.dead:
            filled = _qty((read("order-by-client", d["client_order_id"]) or {}).get("filled_qty"))
            if filled > 0:  # partly filled, then dead: filled at the filled quantity
                return Transition("filled", {"client_order_id": d["client_order_id"], "filled_qty": str(filled)})
        if unfilled is not None:
            unfilled[iv.intent] = _qty(iv.first["qty"])
        return _not_landed(iv, res, now, sent=sent, recovering=recovering, gap=None, holder_gone=holder_gone)

    if iv.action == "close":
        res = walk_attempts(read, iv.intent, CLOSE_DEAD)
        if res.order is not None and res.order.get("status") == "filled":
            done = _close_done(read, iv.symbol, now)
            return Transition("complete" if done else "filled", {"client_order_id": res.client_order_id})
        if res.order is not None:
            return None if iv.state == "acknowledged" else Transition(
                "acknowledged", {"client_order_id": res.client_order_id})
        return _not_landed(iv, res, now, sent=sent, recovering=recovering, gap=_protective_gap(read, iv, now, seen),
                           holder_gone=holder_gone)

    # replace_stop: one replacement attempt rs-<old>; rr-<old> is its restore.
    old_id = iv.first["cancels"][0]
    for cid, state in ((REPLACE_PREFIX + old_id, "complete"), (RESTORE_PREFIX + old_id, "dead")):
        placed = read("order-by-client", cid)
        if isinstance(placed, dict) and placed.get("status") in STOP_OPEN | {"filled"}:
            return Transition(state, {"client_order_id": cid, **({"reason": "restored"} if state == "dead" else {})})
    return _not_landed(iv, None, now, sent=sent, recovering=recovering, gap=_protective_gap(read, iv, now, seen),
                       holder_gone=holder_gone)


def _not_landed(iv, res, now, *, sent, recovering, gap, holder_gone=True):
    """No attempt of `iv` is live or filled."""
    exhausted = res is not None and res.exhausted
    if not recovering:
        if sent == "unknown":
            return None if iv.state == "lost" else Transition("lost")
        if gap is not None and gap[1]:
            # Held and uncovered after our own cancel: stay `recorded` so recovery
            # (the next action or the monitor) restores the canceled stop.
            return None
        if res is not None and res.dead and sent == "refused" and res.dead[-1].get("status") == "rejected":
            return Transition("dead", {"reason": "attempts_dead"})
        return Transition("dead", {"reason": "not_landed"})
    if iv.state == "lost":
        if session_closed_since(datetime.fromisoformat(iv.last["at"]), now):
            return Transition("dead", {"reason": "not_landed"})
        return None
    if iv.state == "acknowledged" or exhausted:
        return Transition("dead", {"reason": "attempts_dead"})
    if not holder_gone:  # released, not stale: its POST may still be invisible
        return None
    # recorded under a lease that is gone
    if gap is not None and gap[1] and gap[2]:
        return Transition("dead", {"reason": "restored"}, restore=tuple(gap[2]))
    return Transition("dead", {"reason": "holder_died"})


# --- the coordinated action -----------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def env_fault(environ=None) -> Callable[[str], None]:
    """The drill hook: COORDINATOR_FAULT=<point> exits 97 at that point, on the
    drill profile only. Set anywhere else it is a hard failure, never ignored."""
    environ = os.environ if environ is None else environ
    point = environ.get("COORDINATOR_FAULT")
    if not point:
        return lambda name: None
    if point not in FAULT_POINTS:
        raise ValueError(f"COORDINATOR_FAULT={point!r} is not one of {sorted(FAULT_POINTS)}")
    if environ.get("ALPACA_PROFILE") != "drill":
        raise ValueError("COORDINATOR_FAULT is honoured only with ALPACA_PROFILE=drill")

    dropped = []

    def fault(name):
        if point == "lose_response":
            if name == "drop_response" and not dropped:
                dropped.append(name)
                print("COORDINATOR_FAULT: dropping the POST response and first lookup", file=sys.stderr, flush=True)
                return True
            return None
        if name == point:
            print(f"COORDINATOR_FAULT: dying at {name}", file=sys.stderr, flush=True)
            os._exit(EXIT_FAULT)
        return None
    return fault


def writer_id(script: str, repo: Path = ROOT, environ=None) -> str:
    """The run id from scripts/run_record.py when a run is open in this checkout,
    else `<script>-<UTC stamp>-<pid>`. One whitespace-free token."""
    environ = os.environ if environ is None else environ
    if environ.get("TRADING_RUN_ID"):
        return environ["TRADING_RUN_ID"]
    try:
        git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo, capture_output=True,
                                 text=True, timeout=30, check=True).stdout.strip()
        run = json.loads((Path(git_dir) / "trading-routine-run.json").read_text(encoding="utf-8"))["run"]
        if isinstance(run, str) and re.fullmatch(r"\S+", run):
            return run
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return f"{script}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}"


def open_store(environ=None) -> StateStore:
    """The store for this process: TRADING_STATE_STORE=local writes through the
    dedicated clone (local /trade, ADR 0004 section 3); otherwise this checkout's
    origin. TRADING_STATE_REPO points at another checkout (tests, drills)."""
    environ = os.environ if environ is None else environ
    repo = Path(environ.get("TRADING_STATE_REPO") or ROOT)
    mode = environ.get("TRADING_STATE_STORE", "")
    if mode not in ("", "checkout", "local"):
        raise ValueError(f"TRADING_STATE_STORE={mode!r} must be checkout or local")
    if mode == "local":
        try:
            url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True,
                                 text=True, timeout=30, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise StoreUnavailable(f"no origin to clone for local mode: {exc}") from None
        return local_store(url)
    return StateStore(repo)


class Session:
    """One coordinated action as the helper's body sees it."""

    def __init__(self, *, store, writer, read, run, clock, sleep, fault, binding, snapshot=None, view=None,
                 storeless=None):
        self.store, self.writer, self.read, self._run = store, writer, read, run
        self.clock, self.sleep, self.fault, self.binding = clock, sleep, fault, binding
        self.snapshot, self.storeless = snapshot, storeless
        self.events = list(snapshot.events) if snapshot else []
        self.view = view or View()
        self.started = clock()
        self.acquire = None if storeless else self._acquire_line()
        self.deadline = self.started + MUTATION_DEADLINE
        self.pending: list[dict] = []       # lines for the next push, after the acquire
        self.established = False            # our acquire is on main
        self.storeless_ok = False           # ADR 0004 section 1 exception taken
        self.intent: str | None = None      # the intent this action recorded
        self.sent: str | None = None        # last POST: None / "landed" / "refused" / "unknown"
        self.acted = False
        self.recovery: list[dict] = []
        self.uncovered: set = set()          # symbols recovery saw held without verified coverage
        self.restore_failed: list[str] = []
        self.last_sent = False
        self.unfilled: dict = {}
        self.alerts: list[str] = []
        self.notes: list[str] = []

    # lines --------------------------------------------------------------------
    def _line(self, kind, **fields) -> dict:
        event = new_event(kind, self.writer, **fields)
        event["at"] = _iso(self.clock())
        return validate(event)

    def _acquire_line(self) -> dict:
        holder = self.view.holder
        fields = {"op": "acquire", "prev": self.view.head,
                  "expires_at": _iso(self.started + LEASE_TTL)}
        if holder is not None:
            fields["supersedes"] = holder["id"]
        event = self._line(LEASE_KIND, **fields)
        event["lease"] = event["id"]
        return validate(event)

    def _intent_line(self, intent, state, **fields) -> dict:
        return self._line(INTENT_KIND, intent=intent, state=state, lease=self.acquire["id"], **fields)

    def _release_line(self) -> dict:
        return self._line(LEASE_KIND, op="release", lease=self.acquire["id"], prev=self.acquire["id"])

    def current(self) -> View:
        """The store as it will read once our pending lines land (empty when unreachable)."""
        if self.storeless:
            return View()
        ours = ([] if self.established else [self.acquire]) + self.pending
        return fold(self.events + ours)

    def _push(self, lines, label):
        """Commit `lines` (acquire first while not yet established)."""
        ours = ([] if self.established else [self.acquire]) + lines
        ids = {e["id"] for e in ours} | ({self.acquire["id"]} if self.established else set())

        def still_wins(events):
            return ids <= fold(events).valid

        snap = self.snapshot if not self.established else self.store.fetch()
        done = self.store.commit(snap, ours, writer=self.writer, intent=label, still_wins=still_wins,
                                 budget=PUSH_BUDGET)
        self.events = list(done.events)
        self.established = True
        self.pending = []
        return done

    # recovery -----------------------------------------------------------------
    def recover(self):
        """Reconcile every non-terminal intent (ADR 0010 section 4). Read-only
        transitions wait for push 1; a needed restoration pushes the acquire
        first, re-places the canceled stops, then records `dead (restored)`."""
        now = self.clock()
        restores = []
        superseded = self.current().superseded
        for iv in self.view.non_terminal():
            gone = iv.lease in superseded or now >= datetime.fromisoformat(iv.last["at"]) + LEASE_TTL + SKEW
            step = reconcile(iv, self.read, now, recovering=True, unfilled=self.unfilled, holder_gone=gone,
                             seen=self.uncovered)
            if step is None:
                self.recovery.append({"intent": iv.intent, "state": iv.state, "action": "none"})
                continue
            if step.restore:
                restores.append((iv, step))
                continue
            self.pending.append(self._intent_line(iv.intent, step.state, **step.fields))
            self.recovery.append({"intent": iv.intent, "from": iv.state, "to": step.state, **step.fields})
            if iv.action == "entry" and step.state not in NON_TERMINAL:
                self.unfilled.pop(iv.intent, None)
        if not restores:
            return
        try:
            self._push(self.pending, f"recover-{self.acquire['id'][:12]}")
        except ClaimLost:
            raise _Contended() from None
        except StoreUnavailable as exc:  # nothing was mutated; the gap stays for the next writer
            raise Outcome(EXIT_UNPROTECTED, "recovery_store_unavailable_position_unprotected",
                          symbols=sorted({iv.symbol for iv, _ in restores}), store_error=str(exc)) from None
        self.fault("after_recovery_push")
        for iv, step in restores:
            restored = self._restore(iv, step.restore)
            if not restored:
                # Do not block every later action on one gap a restore cannot close (e.g. the
                # position grew after the stop was sized): the dead writer's intent is over,
                # the gap is an incident, and protective actions must still be able to run.
                self.restore_failed.append(iv.symbol)
                self.pending.append(self._intent_line(iv.intent, "dead", reason="holder_died",
                                                      restore_failed=list(step.restore)))
                self.recovery.append({"intent": iv.intent, "from": iv.state, "to": "dead", "reason": "holder_died",
                                      "restore_failed": list(step.restore)})
                self.alerts.append(f"RECOVERY COULD NOT RESTORE {iv.symbol}: re-placing {list(step.restore)} did "
                                   f"not verify coverage; {iv.intent} closed as holder_died. A human must check.")
                continue
            self.pending.append(self._intent_line(iv.intent, "dead", reason="restored", restored=restored))
            self.recovery.append({"intent": iv.intent, "from": iv.state, "to": "dead", "reason": "restored",
                                  "restored": restored})
            if self.binding is not None and self.binding.error:
                self.alerts.append(
                    f"VERSION BINDING INCIDENT: recovery restored {iv.symbol} protective stop(s) {restored} under "
                    f"approved {self.binding.approved} while the run was unbound ({self.binding.error}).")

    def _restore(self, iv, stop_ids) -> list[str] | None:
        """Re-place each canceled stop as a fixed stop at its own level (rr-<id>),
        then verify coverage. Returns the restore ids, or None when not covered."""
        done = []
        for sid in stop_ids:
            rid = RESTORE_PREFIX + sid
            prior = self.read("order-by-client", rid)
            if not (isinstance(prior, dict) and prior.get("status") in STOP_OPEN | {"filled"}):
                old = self.read("order-info", sid)
                qty = _qty(old.get("qty")) - _qty(old.get("filled_qty"))
                body = {"symbol": iv.symbol, "qty": str(qty), "side": "sell", "type": "stop",
                        "time_in_force": "gtc", "stop_price": str(old["stop_price"]), "client_order_id": rid}
                self.run("order", json.dumps(body))
                prior = self.read("order-by-client", rid)
            if isinstance(prior, dict) and prior.get("status") in STOP_OPEN | {"filled"}:
                done.append(rid)
        held, coverage = live_coverage(self.read, iv.symbol, self.clock())
        return done if held is None or coverage["ok"] else None

    # what the body uses ---------------------------------------------------------
    def reservations(self, exclude: str | None = None) -> tuple[Reservation, ...]:
        view = self.current()
        for iv in view.non_terminal():
            if iv.action == "entry" and iv.intent not in self.unfilled:
                self.unfilled[iv.intent] = entry_unfilled(self.read, iv)
        return reservations_of(view, self.unfilled, exclude)

    def known_intents(self) -> frozenset[str]:
        return frozenset(self.current().intents)

    def state_of(self, intent: str) -> str | None:
        return self.current().state_of(intent)

    def refuse(self, intent, outcome: Outcome, *, action, symbol, reasons):
        """Record `intent` as refused (with acquire, recovery and release in the
        same push: a refusal changes nothing), then raise `outcome`."""
        if self.storeless:
            outcome.detail.update(refusal_recorded=False, store_error=self.storeless)
            raise outcome
        known = self.state_of(intent)
        if known is not None:  # an unfinished intent refused on a rerun keeps its state
            outcome.detail.update(refusal_recorded=False, intent_state=known)
            raise outcome
        line = self._intent_line(intent, "refused", action=action, symbol=symbol,
                                 reasons=[str(r) for r in reasons])
        try:
            self._push(self.pending + [line, self._release_line()], intent)
        except ClaimLost:
            raise _Contended() from None
        except StoreUnavailable as exc:
            outcome.detail.update(refusal_recorded=False, store_error=str(exc))
            raise outcome from None
        self.acquire = None  # released
        outcome.detail["refusal_recorded"] = True
        raise outcome

    def record(self, intent, *, action, symbol, refuse: Callable[..., Outcome], restoration=False, **fields):
        """Push 1: acquire + recovery + the intent as `recorded`. An intent already
        non-terminal in the store (a `lost` one being re-POSTed) is continued: no
        new line, push 1 carries the acquire. `refuse(code, state, **detail)` builds
        the helper's Outcome when the coordinator itself must refuse."""
        self.intent = intent
        if self.storeless:
            if not restoration:
                raise refuse(EXIT_STORE_UNAVAILABLE, "store_unavailable", reason=self.storeless)
            self.storeless_ok = True
            self.alerts.append(f"STORE UNAVAILABLE: placed protection on uncovered {symbol} without the state "
                               f"store ({self.storeless}); ADR 0004 section 1 exception.")
            return
        lines = list(self.pending)
        state = self.state_of(intent)
        if state is None:
            lines.append(self._intent_line(intent, "recorded", action=action, symbol=symbol, **fields))
        elif state not in NON_TERMINAL:
            raise ValueError(f"intent {intent} is already {state} in the store")
        try:
            self._push(lines, intent)
        except ClaimLost:
            raise _Contended() from None
        except StoreUnavailable as exc:
            raise refuse(EXIT_STORE_UNAVAILABLE, "store_unavailable", reason=str(exc)) from None
        self.fault("after_record")

    def run(self, command, argument):
        """The broker mutation, refused after the deadline (ADR 0010 section 1)."""
        if not (self.established or self.storeless_ok):
            raise AssertionError("broker mutation before the lease and intent are on main")
        self.last_sent = False
        if self.clock() > self.deadline:
            self.notes.append(f"mutation deadline passed; {command} not sent")
            return False, "000", "", "REFUSED: coordinator mutation deadline passed"
        self.acted = True
        self.last_sent = True
        result = self._run(command, argument)
        if command == "cancel":
            self.fault("after_cancel")
        return result

    def post(self, cid: str, body_json: str):
        """POST one attempt and confirm it by client id, owning the lost-response
        budget: on an unknown outcome, re-POST the same id; a 422 "must be
        unique" proves the order exists. Returns (order|None, http, error, sent)."""
        ok, http, out, err = self.run("order", body_json)
        if self.last_sent:
            self.sent = "unknown"  # until a lookup or a refusal says otherwise
        self.fault("after_post")
        if self.fault("drop_response") is True:  # drill: the answer and first lookup are lost
            ok, http, out, err, placed = False, "000", "", "COORDINATOR_FAULT: response dropped", None
        else:
            placed = self.read("order-by-client", cid)
        if isinstance(placed, dict):
            self.sent = "landed"
            return placed, http, err or out, "landed"
        if _refused(ok, http, out, err):
            self.sent = "refused"
            return None, http, err or out, "refused"
        for _ in range(LOST_REPOSTS):
            self.sleep(LOST_WAIT_S)
            # Re-POST before looking again: a landed order answers 422 at once.
            ok, http2, out2, err2 = self.run("order", body_json)
            placed = self.read("order-by-client", cid)
            if isinstance(placed, dict):
                break
            if "must be unique" in f"{out2} {err2}":
                self.notes.append(f"{cid}: re-POST answered duplicate; the order exists but is not yet visible")
        if isinstance(placed, dict):
            self.sent = "landed"
            return placed, http, err or out, "landed"
        self.sent = "unknown"
        return None, http, err or out, "unknown"

    # push 2 -------------------------------------------------------------------
    def finish(self, outcome: Outcome):
        detail = outcome.detail
        if self.recovery:
            detail.setdefault("recovery", self.recovery)
        if self.notes:
            detail.setdefault("coordinator_notes", self.notes)
        if self.storeless:
            detail.setdefault("store_error", self.storeless)
            if self.storeless_ok:
                detail["store_exception"] = "protective stop placed without the store (ADR 0004 section 1)"
            self._alerts(detail)
            return
        if self.acquire is None:  # a refusal already released
            self._alerts(detail)
            return
        if not self.established:
            if self.pending:
                try:
                    self._push(self.pending + [self._release_line()], f"recover-{self.acquire['id'][:12]}")
                except StoreUnavailable as exc:  # ClaimLost included: nothing was mutated
                    detail["recovery_recorded"] = False
                    print(f"recovery transitions not recorded: {exc}", file=sys.stderr)
            self._alerts(detail)
            return
        lines = []
        iv = self.current().intents.get(self.intent) if self.intent else None
        if iv is not None:  # None: push 1 never landed, nothing to settle
            try:
                step = reconcile(iv, self.read, self.clock(), sent=self.sent, recovering=False)
            except (SystemExit, ValueError, TypeError, KeyError) as exc:
                # Unsettled: the intent stays non-terminal and the next recovery settles it.
                step = None
                detail["intent_state_unsettled"] = str(exc)
            if step is not None:
                lines.append(self._intent_line(self.intent, step.state, **step.fields))
            detail["intent_state"] = step.state if step else iv.state
        lines.append(self._release_line())
        self._still_uncovered(outcome)
        self.fault("before_release")
        try:
            self._push(self.pending + lines, f"{self.intent or 'release'}")
        except StoreUnavailable as exc:
            if self.acted:
                detail.update(outcome_recorded=False, store_error=str(exc), helper_state=outcome.state,
                              helper_exit=outcome.code)
                if outcome.code not in (EXIT_UNPROTECTED, 7):
                    outcome.code, outcome.state = EXIT_NOT_RECORDED, "acted_outcome_not_recorded"
                self.alerts.append(f"ACTED, OUTCOME NOT RECORDED: {self.intent} ({detail['helper_state']}); "
                                   f"the lease goes stale and the next writer recovers it. {exc}")
            else:
                detail.update(outcome_recorded=False, store_error=str(exc))
        self._alerts(detail)

    def _still_uncovered(self, outcome: Outcome):
        """ADR 0006: a symbol recovery could not restore that is still held without
        verified coverage makes the action an incident, whatever the body did."""
        for symbol in self.restore_failed:
            try:
                held, coverage = live_coverage(self.read, symbol, self.clock())
            except (SystemExit, ValueError, TypeError, KeyError):
                held, coverage = True, {"ok": False}
            if held is not None and not coverage["ok"] and outcome.code != EXIT_UNPROTECTED:
                outcome.detail.update(helper_state=outcome.state, helper_exit=outcome.code)
                outcome.code, outcome.state = EXIT_UNPROTECTED, "recovery_restore_failed_position_unprotected"

    def abandon(self, exc: BaseException):
        """An unexpected exception escaped after our acquire landed: release so the
        next writer need not wait for expiry; the intent stays for recovery."""
        if self.storeless or self.acquire is None or not self.established:
            return
        try:
            self._push(self.pending + [self._release_line()], f"abandon-{self.acquire['id'][:12]}")
        except StoreUnavailable as push_exc:
            print(f"release after {type(exc).__name__} not recorded: {push_exc}", file=sys.stderr)

    def _alerts(self, detail):
        if self.alerts:
            detail["alerts"] = list(self.alerts)


def _refused(ok, http, out, err) -> bool:
    """Proven not to have landed: a 4xx other than a duplicate id, or refused by
    the local validation gate before transport."""
    text = f"{out} {err}"
    if http.startswith("4"):
        return "must be unique" not in text
    return http == "000" and not ok and "REFUSED" in err


def coordinate(body: Callable[[Session], None], *, store: StateStore | None, writer: str, read, run,
               clock=_now, sleep=time.sleep, fault=None, binding=None, poll_s=POLL_S,
               storeless_error: str | None = None):
    """Run `body(session)` as one coordinated action. The body ends by raising its
    Outcome; push 2 happens on the way out and may change the code to
    EXIT_NOT_RECORDED. A void claim re-enters the wait; the whole action reruns."""
    if fault is None:
        try:
            fault = env_fault()
        except ValueError as exc:  # a misplaced drill hook stops everything, as a usage error
            raise Outcome(2, "usage", reason=str(exc)) from None
    started = clock()
    while True:
        error = storeless_error
        if error is None and store is not None:
            try:
                snap = store.fetch()
                view = fold(snap.events)
            except StoreUnavailable as exc:
                error = str(exc)
        elif store is None and error is None:
            error = "no store configured"
        if error is not None:
            session = Session(store=None, writer=writer, read=read, run=run, clock=clock, sleep=sleep,
                              fault=fault, binding=binding, storeless=error)
            _run_body(body, session)
        holder = view.holder
        if holder is not None and not stale(holder, clock()):
            if clock() - started >= MAX_WAIT:
                raise Outcome(EXIT_LEASE_WAIT, "lease_wait_exhausted", holder=holder["writer"],
                              lease=holder["id"], expires_at=holder["expires_at"],
                              waited_s=int((clock() - started).total_seconds()))
            print(f"lease held by {holder['writer']} until {holder['expires_at']}; waiting {poll_s}s",
                  file=sys.stderr, flush=True)
            sleep(poll_s)
            continue
        session = Session(store=store, writer=writer, read=read, run=run, clock=clock, sleep=sleep,
                          fault=fault, binding=binding, snapshot=snap, view=view)
        if holder is not None:
            print(f"lease {holder['id']} of {holder['writer']} is stale; taking over", file=sys.stderr)
        try:
            _run_body(body, session)
        except _Contended:
            print("lease claim lost to a concurrent writer; waiting again", file=sys.stderr, flush=True)
            sleep(random.uniform(1, 5))
            if clock() - started >= MAX_WAIT:
                raise Outcome(EXIT_LEASE_WAIT, "lease_wait_exhausted", waited_s=int((clock() - started).total_seconds()))


def _run_body(body, session):
    try:
        if not session.storeless:
            try:
                session.recover()
            except SystemExit as exc:
                code = EXIT_UNPROTECTED if session.acted or session.uncovered else 4
                raise Outcome(code, "broker_state_unavailable_in_recovery", adapter_exit=exc.code,
                              uncovered=sorted(session.uncovered)) from None
            except (ValueError, TypeError, KeyError) as exc:
                code = EXIT_UNPROTECTED if session.acted or session.uncovered else 4
                raise Outcome(code, "unreadable_broker_state_in_recovery", error=str(exc),
                              uncovered=sorted(session.uncovered)) from None
        body(session)
    except Outcome as outcome:
        session.finish(outcome)
        raise
    except _Contended:
        raise
    except BaseException as exc:
        session.abandon(exc)
        raise
    raise AssertionError("a coordinated body must end in an Outcome")


def recover_only(*, store, writer, read, run, clock=_now, sleep=time.sleep, fault=None, binding=None) -> dict:
    """Recovery without a new intent (the protection monitor, every run). Pushes
    nothing when no non-terminal intent changes; skips while a live holder works."""
    try:
        view = fold(store.fetch().events)
    except StoreUnavailable as exc:
        return {"exit": EXIT_STORE_UNAVAILABLE, "state": "store_unavailable", "reason": str(exc)}
    if view.holder is not None and not stale(view.holder, clock()):
        return {"exit": EXIT_OK, "state": "lease_held", "holder": view.holder["writer"],
                "non_terminal": [iv.intent for iv in view.non_terminal()]}
    if not view.non_terminal():
        return {"exit": EXIT_OK, "state": "nothing_to_recover"}

    def body(session):
        if session.storeless:  # the store went away between the two fetches: nothing recovered
            raise Outcome(EXIT_STORE_UNAVAILABLE, "store_unavailable", reason=session.storeless)
        raise Outcome(EXIT_OK, "recovered")
    try:
        coordinate(body, store=store, writer=writer, read=read, run=run, clock=clock, sleep=sleep,
                   fault=fault, binding=binding)
    except Outcome as outcome:
        return {"exit": outcome.code, "state": outcome.state, **outcome.detail}
    except SystemExit as exc:
        return {"exit": 4, "state": "broker_state_unavailable", "adapter_exit": exc.code}
    except StoreUnavailable as exc:
        return {"exit": EXIT_STORE_UNAVAILABLE, "state": "store_unavailable", "reason": str(exc)}
    raise AssertionError("recovery must end in an Outcome")


def status(store: StateStore, now: datetime | None = None) -> dict:
    """Read-only summary for run records (ADR 0012): holder, non-terminal intents, takeovers."""
    now = now or _now()
    view = fold(store.fetch().events)
    holder = view.holder
    return {"holder": None if holder is None else {"writer": holder["writer"], "lease": holder["id"],
                                                   "expires_at": holder["expires_at"],
                                                   "stale": stale(holder, now)},
            "non_terminal": [{"intent": iv.intent, "action": iv.action, "symbol": iv.symbol, "state": iv.state}
                             for iv in view.non_terminal()],
            "takeovers": [{"lease": t["id"], "writer": t["writer"], "supersedes": t["supersedes"], "at": t["at"]}
                          for t in view.takeovers]}


def send_alerts(outcome: Outcome, run=subprocess.run) -> None:
    """Email every coordinator alert; records whether delivery was verified."""
    alerts = outcome.detail.get("alerts")
    if not alerts:
        return
    try:
        delivered = run(["bash", str(EMAIL), "\n".join(alerts)], check=False, timeout=120).returncode == 0
    except subprocess.TimeoutExpired:
        delivered = False
    outcome.detail["alerts_delivered"] = delivered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("status", "recover"))
    args = parser.parse_args(argv)
    try:
        store = open_store()
        if args.command == "status":
            print(json.dumps(status(store), indent=2))
            return EXIT_OK
        from scripts.replace_stop import mutate  # noqa: E402  (local: replace_stop imports this module)
        from scripts.strategy_version import VersionBindingError, bind  # noqa: E402
        from scripts.validate_order import adapter  # noqa: E402
        try:
            binding = bind(os.environ)
        except VersionBindingError:
            binding = None
        report = recover_only(store=store, writer=writer_id("recover"), read=adapter, run=mutate, binding=binding)
    except StoreUnavailable as exc:
        print(json.dumps({"state": "store_unavailable", "exit": EXIT_STORE_UNAVAILABLE, "reason": str(exc)}))
        return EXIT_STORE_UNAVAILABLE
    except ValueError as exc:
        print(json.dumps({"state": "usage", "exit": 2, "reason": str(exc)}))
        return 2
    if report.get("alerts"):
        holder = Outcome(report["exit"], report["state"], **report)
        send_alerts(holder)
        report = holder.detail
    print(json.dumps(report, indent=2, default=str))
    return report["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
