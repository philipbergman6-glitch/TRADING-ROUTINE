"""Execution identity shared by the entry and close helpers (ADR 0005).

An **intent** is one requested action on one symbol, named
`<kind>-<YYYYMMDD>-<SYM>[-<seq>]` where the day is when it was minted, not what
it is: a rerun on a later day that names the intent (`--intent`) resolves the
same one. Each POST is an **attempt** whose client order id is the intent id,
then `<intent>-r1` .. `-r<MAX_RETRIES>`. A new attempt is made only after the
broker confirms the previous one dead; an attempt id is never reused.

Without an explicit intent the resolver probes today and yesterday (UTC):
a live attempt from either day is adopted, so a rerun after midnight finds the
order instead of submitting again. Terminal attempts from yesterday are
history. Otherwise the latest intent minted today is resolved, or a fresh one
is minted.

The state store (ADR 0004) also records intents, including ones that never
reached the broker (refused, or dead before a POST). Callers pass those ids as
`known` so the family walk and the next free intent skip past them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re

KINDS = frozenset({"en", "cl"})
LIVE = frozenset({"new", "accepted", "pending_new", "held", "accepted_for_bidding", "partially_filled"})
DEAD = frozenset({"canceled", "expired", "rejected"})
MAX_RETRIES = 5
MAX_SEQ = 9

_SEQ = re.compile(r"[A-Za-z0-9]{1,8}")
_ATTEMPT_SUFFIX = re.compile(r"[rR]\d+")
_INTENT = re.compile(r"([a-z]{2})-(\d{8})-([A-Z0-9]{1,10})(?:-([A-Za-z0-9]+))?")
_BROKER_SAFE = re.compile(r"[A-Za-z0-9-]{1,48}")


@dataclass(frozen=True)
class Resolution:
    """Where one intent stands at the broker.

    `order` is its live or filled attempt (authoritative) and `client_order_id`
    that attempt's id; with no such attempt, `client_order_id` is the next free
    attempt id, or None when every attempt is dead (exhausted).
    """
    intent: str
    client_order_id: str | None
    order: dict | None = None
    dead: list = field(default_factory=list)

    @property
    def live(self) -> bool:
        return self.order is not None and self.order.get("status") in LIVE

    @property
    def filled(self) -> bool:
        return self.order is not None and self.order.get("status") == "filled"

    @property
    def exhausted(self) -> bool:
        return self.client_order_id is None

    @property
    def submitted(self) -> bool:
        """True when any attempt of this intent ever reached the broker."""
        return self.order is not None or bool(self.dead)


def _check_seq(seq: str) -> str:
    if not _SEQ.fullmatch(seq):
        raise ValueError(f"intent seq/tag {seq!r} must be 1-8 alphanumerics")
    if _ATTEMPT_SUFFIX.fullmatch(seq):
        raise ValueError(f"intent seq/tag {seq!r} reads as an attempt suffix (r<digits>)")
    return seq


def mint_intent(kind: str, symbol: str, day: date, seq: str | None = None) -> str:
    if kind not in KINDS:
        raise ValueError(f"intent kind {kind!r} is not one of {sorted(KINDS)}")
    intent = f"{kind}-{day:%Y%m%d}-{symbol.upper()}" + (f"-{_check_seq(seq)}" if seq is not None else "")
    attempt_id(intent, MAX_RETRIES)  # the longest attempt id must be broker-safe too
    return intent


def attempt_id(intent: str, n: int) -> str:
    cid = intent + (f"-r{n}" if n else "")
    if not _BROKER_SAFE.fullmatch(cid):
        raise ValueError(f"client_order_id {cid!r} is not broker-safe")
    return cid


def parse_intent(intent: str, kind: str, symbol: str, today: date | None = None) -> tuple[str, date, str, str | None]:
    """Validate an intent id named by the caller for this helper and symbol (and not minted after `today`)."""
    m = _INTENT.fullmatch(intent or "")
    if not m:
        raise ValueError(f"intent {intent!r} has the wrong format; expected <kind>-<YYYYMMDD>-<SYM>[-<seq>]")
    got_kind, day_text, got_symbol, seq = m.groups()
    if got_kind != kind:
        raise ValueError(f"intent {intent!r} has kind {got_kind!r}; this helper resolves {kind!r}")
    if got_symbol != symbol.upper():
        raise ValueError(f"intent {intent!r} names symbol {got_symbol}, not {symbol.upper()}")
    try:
        day = datetime.strptime(day_text, "%Y%m%d").date()
    except ValueError:
        raise ValueError(f"intent {intent!r} has an invalid date {day_text}") from None
    if today is not None and day > today:
        raise ValueError(f"intent {intent!r} is dated in the future")
    if seq is not None:
        if _ATTEMPT_SUFFIX.fullmatch(seq):
            raise ValueError(f"{intent!r} is an attempt id, not an intent id; pass the intent without -r<n>")
        _check_seq(seq)
    return got_kind, day, got_symbol, seq


def _walk(read, intent: str, dead: frozenset) -> Resolution:
    """Attempts in order: live or filled is authoritative, dead is skipped, anything else hard-fails."""
    seen = []
    for n in range(MAX_RETRIES + 1):
        cid = attempt_id(intent, n)
        prior = read("order-by-client", cid)
        if not isinstance(prior, dict):
            return Resolution(intent, cid, None, seen)
        status = prior.get("status")
        if status in LIVE or status == "filled":
            return Resolution(intent, cid, prior, seen)
        if status in dead:
            seen.append({"client_order_id": cid, "status": status})
            continue
        raise ValueError(f"attempt {cid} has unexpected status {status!r}")
    return Resolution(intent, None, None, seen)


def walk_attempts(read, intent: str, dead=DEAD) -> Resolution:
    """Where one known intent stands at the broker (the shared attempt walk)."""
    return _walk(read, intent, frozenset(dead))


def _family(read, kind, symbol, day, dead, tag=None, known=frozenset()) -> list[Resolution]:
    """Every intent of this kind and symbol minted on `day` (just the tagged one with a tag)."""
    seqs = [tag] if tag is not None else [None] + [str(s) for s in range(2, MAX_SEQ + 1)]
    found = []
    for seq in seqs:
        got = _walk(read, mint_intent(kind, symbol, day, seq), dead)
        if not got.submitted and got.intent not in known:
            break
        found.append(got)
    return found


def resolve_intent(read, kind: str, symbol: str, now: datetime, *, intent: str | None = None,
                   tag: str | None = None, dead=DEAD, known=frozenset()) -> Resolution:
    """The intent this run works under, and where it stands at the broker."""
    dead = frozenset(dead)
    if intent is not None:
        if tag is not None:
            raise ValueError("pass either --intent or --tag, not both")
        parse_intent(intent, kind, symbol, now.date())
        return _walk(read, intent, dead)
    today = now.date()
    yesterday = _family(read, kind, symbol, today - timedelta(days=1), dead, tag, known)
    todays = _family(read, kind, symbol, today, dead, tag, known)
    live = [r for r in yesterday + todays if r.live]
    if len(live) > 1:
        raise ValueError(f"several live attempts for {kind} {symbol}: {[r.client_order_id for r in live]}")
    if live:
        return live[0]
    if todays:
        return todays[-1]
    fresh = mint_intent(kind, symbol, today, tag)
    return Resolution(fresh, fresh)


def next_free_intent(read, kind: str, symbol: str, now: datetime, *, dead=DEAD,
                     known=frozenset()) -> str | None:
    """The next unminted untagged intent of today, or None when the sequence is spent."""
    seq = len(_family(read, kind, symbol, now.date(), frozenset(dead), known=known)) + 1
    if seq > MAX_SEQ:
        return None
    return mint_intent(kind, symbol, now.date(), str(seq) if seq > 1 else None)
