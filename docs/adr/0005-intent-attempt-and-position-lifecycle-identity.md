# 0005. Execution identity: intent, attempt and position lifecycle

Date: 2026-10-12. Status: accepted. Amends ADR 0003 §3 (deterministic client
order IDs are kept as *attempt* IDs; they stop being the unit of identity or
the evidence of completion).

Resolves wayfinder ticket
[#94](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/94) on
map #93. Implementation is ticket #96; the durable store is ADR 0004 (`state/`
JSONL on `main`, resolving #97); the
account-wide coordinator is #99. Those tickets build on the names and rules
fixed here and must not redefine them.

## Context

Recovery identity today is a UTC day plus a symbol. `scripts/close_position.py`
submits `cl-<YYYYMMDD>-<SYM>` (`-r1`…`-r5` after a dead attempt) and
`scripts/submit_entry.py` submits `en-<YYYYMMDD>-<SYM>[-<tag>]`. Three defects
follow from that choice:

1. **A filled close is taken as proof the position is gone.** The close helper
   returns `already_closed` as soon as any filled `cl-` order for today exists,
   before reading holdings. V1 permits a same-day re-entry, so a second close
   request on the re-entered position is wrongly reported complete (audit
   defect 1, `docs/audits/2026-10-12/V1-FOUNDATION.md`).
2. **An entry has no retry identity.** After a cancelled, rejected or expired
   attempt the entry helper resubmits the same `en-` id. Alpaca rejects a
   duplicate `client_order_id` with HTTP 422 "client_order_id must be unique"
   and never de-duplicates (research 0007 §1), so one dead attempt blocks the
   symbol for the rest of the UTC day unless a human invents a `--tag`.
3. **Identity rolls at 00:00 UTC.** A rerun after midnight derives a new id,
   finds nothing, and submits again. This is not theoretical: the evening
   monitor and heartbeat runs cluster 21:01–00:28Z (research 0008) and
   after-hours trading ends at 00:00Z in winter.

Constraints that shape the fix: the durable store is an append-only JSONL
file on `main` written before any POST (ADR 0004), but a crashed writer's
intent must also be recoverable from the broker alone, since the store holds
the claim and the broker holds the outcome; research 0007 says an id must
never be reused, a duplicate 422 is proof the order exists, a 404 after a POST
means *unknown* until a wait budget elapses, and `scripts/alpaca.sh` caps ids
at 48 chars of `[A-Za-z0-9-]`. The pure engine (`risk_engine/`) must stay free
of I/O; `risk_engine/blotter.py` already reconstructs *round trips*
(flat → long → flat) from fills.

## Decision

Three concepts replace "the client order id":

| Concept | Minted by | Identified by | Lives where |
|---|---|---|---|
| **Intent** | the caller, before any broker call | intent ID, e.g. `cl-20261012-AMD`, `en-20261012-AMD-2` | the intent record: lines in `state/` keyed by `id` (ADR 0004), recoverable from the broker by prefix walk |
| **Attempt** | the helper, one per POST | `client_order_id` = intent ID, then `<intent>-r1`, `-r2`… | the broker |
| **Position lifecycle** | nobody; derived from fills and holdings | the opening buy fill of the episode | broker state; becomes a blotter round trip once flat |

### 1. The unit of identity is the intent

An **intent** is one requested action on one symbol: enter, close, or
replace-stop. It is minted by the caller and recorded *before* the first
submission. Everything that must be idempotent keys on the intent ID; the
coordinator (#99) uses it as the key of its lease and reservation; the store
(#97) uses it as the primary key of the intent record.

**Intent ID format**: `<kind>-<YYYYMMDD>-<SYM>[-<seq>]`.

- `kind` ∈ `en` (entry), `cl` (close). `rs`/`rr` (stop replace / restore,
  ADR 0002) already key on the replaced broker order id and are unchanged.
- `YYYYMMDD` is the UTC day the intent was **minted**. It is a human hint and
  a bound on how far recovery has to enumerate. **It is not identity**: a
  rerun on a later day that resolves to this intent keeps this ID.
- `seq` distinguishes a second intent of the same kind, symbol and day. It is
  `2`, `3`, … when minted automatically (the next free integer, found by
  lookup), or the caller's `--tag` (1–8 alphanumerics, as today). A tag
  matching `r<digits>` is rejected, so a tag can never be confused with an
  attempt suffix.
- Minting is the caller's act. A helper mints only when the caller passes no
  `--intent`; it prints the chosen intent ID in its JSON output and in the
  "rerun this exact command" text, and the printed rerun command carries
  `--intent <id>` so a human or routine retrying later resolves the same
  intent regardless of date.

**Why not a random intent ID?** A random ID is only findable through the
store; the deterministic form is also recoverable from the broker alone by
walking the known prefix, which is what recovery needs when the store and the
broker disagree about whether a POST happened. The same string is the store
key (ADR 0004) and the broker prefix.

**Why keep the date at all?** Dropping it (`cl-AMD-<n>`) makes `seq` a
forever-monotonic counter per symbol, which needs either a store or a scan of
the whole order history to mint safely. The date bounds the enumeration to one
day's ids and keeps the ids readable in broker dashboards and logs.

### 2. An attempt is one POST; attempt IDs are never reused

Each intent has an ordered list of **attempts**. Attempt *n* carries
`client_order_id` = intent ID for *n* = 0 and `<intent>-r<n>` for *n* ≥ 1.
`MAX_RETRIES` stays 5; exhausting it is a hard failure, never a silent stop.

A new attempt is minted **only** when the broker confirms the previous one
dead (`canceled`, `expired`, `rejected`, and for entries `replaced`). After a
lost response (POST returned nothing usable and lookup gives 404) the helper
re-POSTs the **same** attempt ID within the wait budget, so a landed order
answers 422 "must be unique" and converts ambiguity into proof (research 0007
§3). A duplicate 422 is resolved by lookup, never by minting a new attempt.

Entries adopt exactly the close helper's walk: live or filled attempt →
authoritative (`already_submitted` / `already_filled`), dead attempt → skip
to the next suffix, unexpected status → hard fail. The walk is shared code
(one resolver used by both helpers), not two copies.

### 3. A position lifecycle is derived, and only holdings end it

A **position lifecycle** is one episode of holding a symbol: it opens with
the buy fill that takes reconciled quantity from zero to positive, includes
every add and every protective-stop replacement in between, and ends when
reconciled quantity returns to zero. It is not minted and has no record of its
own; it is read from broker fills and current holdings, and once flat it is
exactly a blotter round trip.

**Completion predicate for a close intent.** A close is complete, and a close
helper may return exit 0 with a terminal state, **only when**

1. the fresh `positions` snapshot shows **no** holding of the symbol, and
2. no **buy** order for the symbol is live (`accepted`, `new`,
   `partially_filled`, `pending_new`, `held`).

A filled close *attempt* is never by itself evidence of completion. It only
proves that **an earlier lifecycle** ended. Concretely:

- The `already_closed` short-circuit is removed. Finding a filled `cl-`
  attempt means "that intent is history": continue to the holdings check. If
  the symbol is still held, this is a new lifecycle and a **new intent**
  (`-2`) is minted; the old attempts are reported, not reused.
- A live close attempt (`already_closing`) is adopted only while the symbol is
  still held. A resting sell with zero holdings is an anomaly and reported as
  such with a non-zero exit, not as success.
- `position_gone` and `stop_filled_position_gone` apply the same predicate: a
  filled stop proves nothing about quantity added after the stop was sized, so
  holdings are re-read and any remainder is still sold under the same intent.
- Holdings zero but a buy live: the position is gone, nothing to sell, but
  another writer is re-entering. Report it as a distinct state with the buy's
  client ids so the coordinator can see the interleaving. Exit code
  classification of this and every other state is owned by #95/#96, not here.

**Completion predicate for an entry intent.** Terminal when its attempt is
`filled` (position lifecycle opened or added to) or confirmed dead with
retries exhausted. A resting OTO entry is *pending*, never complete.

### 4. Midnight: keep the date, resolve across it

Identity does not roll at 00:00 UTC because identity is the intent ID, not
the day. Two mechanisms make a cross-midnight rerun resolve the right intent:

- **Explicit**: `--intent <id>` (printed in every rerun instruction) resolves
  that intent and nothing else, on any day.
- **Default**: when no `--intent` is given, the helper probes **today and
  yesterday** (UTC) for the kind/symbol prefix and adopts a **live**
  (non-terminal) attempt from either day. Terminal attempts from yesterday
  are history and never adopted; a filled entry yesterday does not block a
  deliberate new entry today, and a filled close yesterday says nothing about
  today's holdings.

UTC stays the calendar for the day field because Alpaca timestamps are UTC
and both helpers already use it. The lookback is one day because no helper
leaves an intent pending across two sessions: entries are day orders or OTO
legs that fill or die within a session, and a close is a market order.

### 5. The intent record (for #97 and #99)

In the `state/` file (ADR 0004) an intent is a line whose `id` is the intent
ID, with the mandatory `kind`, `at`, `writer`, `schema` fields, carrying at
least:

```
intent_id, kind, symbol, minted_at (UTC), minted_by (routine/run id),
requested: {qty, protection or reason},
attempts: [{client_order_id, submitted_at, last_status, broker_order_id}],
state: recorded | submitted | acknowledged | filled | dead | lost | complete
```

The intent line is pushed **before** the first POST (ADR 0004 §2 write
protocol) and followed by one line per attempt confirmation. Until #96 and
#99 wire the writers, "recorded" means printed to the run output before the
POST and recoverable from the broker by the walk above.
The coordinator's reservation and lease (#99) key on `intent_id`; the state
names here are a floor, #99 may refine the transitions.

## Considered and rejected

- **Keep client order id as identity, add `-rN` to entries.** Fixes defect 2
  only; `already_closed` and the midnight roll remain.
- **Random UUID intent ID persisted only in the store.** A UUID is
  unrecoverable from the broker, so a writer that dies between the store
  push and the POST, or whose push is lost, cannot find its own order. The
  deterministic ID is both the store key and the broker prefix.
- **Drop the date entirely.** Needs an unbounded order scan or a store to
  mint the next sequence safely; loses readability.
- **Declare a close complete when the close order fills.** This is defect 1.
  Fill of one order is evidence about one attempt, not about the lifecycle.

## Consequences

- `already_closed` disappears as a state; `already_closing` requires holdings.
- `submit_entry.py` gains the shared resolver and loses the manual-`--tag`
  requirement for retries; `--tag` remains for a deliberate second entry.
- Both helpers gain `--intent` and print it; routine text that says "rerun
  this exact command" must quote the printed command (edit both routine
  copies while #78 is open).
- `ARCHITECTURE.md` lines describing idempotency "per deterministic client id"
  are reworded to intent/attempt; ADR 0003 §3 is amended by this ADR.
- The audit probe `repro_v1_foundation.py:31` becomes a normal regression test
  in #96, alongside: repeated close, same-day re-entry then close, entry retry
  after a dead attempt, and a cross-midnight rerun with `--intent` and without.
