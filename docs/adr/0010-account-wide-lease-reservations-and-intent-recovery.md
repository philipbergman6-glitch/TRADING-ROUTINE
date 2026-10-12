# 0010. The coordinator: one account-wide lease, reservations derived from intents, recovery that only restores coverage

Date: 2026-10-12. Status: accepted. Resolves
[#99](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/99)
on map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93).
Builds on ADR 0004 (store: append-only `state/` JSONL on `main`, push is the
compare-and-swap, fail closed) and ADR 0005 (identity: intent, attempt,
position lifecycle). Neither is redefined here. Implementation is
[#100](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/100)
on the store mechanics of
[#115](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/115).

## Context

The v1 audit (`docs/audits/2026-10-12/V1-FOUNDATION.md`, package 2) requires
one owner that "serializes competing writers, reserves capacity, persists
intent before submission and reconciles outcomes". ADR 0004 left four things
to this ticket: the push budget N, the replay rule that says whose claim won,
lease expiry, and stale-intent recovery.

Facts the decision leans on:

- **Writers that mutate the broker**: market-open, midday, the protection
  monitor and local `/trade` (ADR 0004 table). All four run a handful of
  mutations a day at most; throughput is not a constraint.
- **Each mutation is a short deterministic helper**, not LLM time:
  `submit_entry.py`, `close_position.py` and `replace_stop.py` poll at most
  20 × 1 s per confirmation, every broker call is capped at 30 s
  (`scripts/alpaca.sh:87`) and `replace_stop.py` caps a subprocess at 90 s.
  One intent's broker work is therefore bounded at a few minutes.
- **Capacity the broker does not show until a fill**: `PortfolioState` is
  built from `account.cash`, `positions` and filled buys since Monday
  (`scripts/validate_order.py:130-190`). An accepted but unfilled buy changes
  none of them, so two buys validated back to back can both pass rules 2, 3,
  8 and 13. Today the only guard is the pending-buy gate in
  `scripts/validate_mutation.py` ("pending buy exists; wait for
  reconciliation").
- **Capacity rules in the engine** (`risk_engine/engine.py:158-247`; numbering
  from `memory/TRADING-STRATEGY.md`): rule 3 slots (5–6 positions, adding to a
  held symbol opens no slot) and size (20% of equity, measured on the
  resulting position); rule 2 deployment upper bound; rule 8 three new trades
  a week; rule 13 settled cash only. The rule-12 fallback is exempt from
  slots and the weekly count, never from sizing. (The ticket's "rule 1 slots"
  is rule 3; rule 1 is no options.)
- **Research 0007**: a duplicate `client_order_id` answers 422, lookups reach
  back to account creation, and Alpaca publishes no visibility window after a
  lost POST, so "not found" means *unknown* until a budget the repo chooses.

## Decision

### 1. One account-wide lease, held for one coordinated action

A **lease** is the exclusive, expiring right to change execution state for the
whole account. There is exactly one. A writer holds it for one **coordinated
action**: recovery of stale intents, then one intent's validation, submission
and outcome. It is taken inside the helper process, never across LLM
reasoning between two orders.

Per-symbol leases were rejected: the capacity being protected (cash, slots,
deployment, weekly count) is account-wide, so a per-symbol lease still needs a
second account-wide mechanism; recovery sweeps every symbol; and there is no
throughput to gain at a few mutations a day.

**Timing** (all UTC, measured from the acquire line's `at`):

| Bound | Value | Rule |
|---|---|---|
| Mutation deadline | 5 min | the holder sends no new broker mutation (POST or cancel) after it; reads and the release push may continue |
| `expires_at` | 10 min | written in the acquire line |
| Skew allowance | 2 min | another writer treats the lease as stale only when its clock reads past `expires_at` + 2 min |

There is no renewal. The deadline sits well under the expiry, so an expired
lease means its holder died or overran, never that it is still mid-mutation.
A holder that reaches the deadline stops, records what it observed, and
releases.

**A writer that finds the lease held** polls (`git fetch`, replay) every 15 s
until it is released or stale. The wait is bounded by expiry plus skew, at
most 12 minutes. It does not mutate in the meantime, **including** placing a
stop on an uncovered position: a live holder may be inside a deliberate,
bounded unprotected window (cancel-then-sell, cancel-then-place), and a
second stop would hold the shares the holder is about to sell. The ADR 0004
§1 exception (place a stop on a position with none, without the store)
applies when the **store is unreachable**, not when the lease is held.

**A stale lease is taken over, never silently stolen**: the taker appends an
acquire line with `supersedes: <stale lease id>`, then runs recovery on the
dead holder's intents (§4) before anything else.

### 2. Lease lines and the replay rule (the "winning claim" of ADR 0004 §2)

Lines of `kind: "lease"` carry, beyond the ADR 0004 envelope:
`op` (`acquire` | `release`), `lease` (the lease id, `<writer>-<at>`),
`prev` (the id of the last valid lease line the writer replayed),
`expires_at`, and for a takeover `supersedes`.

Replay walks the file in order and keeps the **lease head** (last valid lease
line) and the **holder**:

- `acquire` is **valid** iff `prev` equals the current head **and** either
  there is no holder or `supersedes` names the holder. Otherwise it is
  **void**: replay ignores it.
- `release` is valid iff it names the current holder.
- Replay never reads a clock. Staleness is judged by the writer at its own
  clock before it writes `supersedes`; replay only checks that the
  superseded lease was the holder.
- Every `intent` line carries `lease`. An intent line under a void or
  released lease is void. An intent line under the valid lease that makes an
  illegal transition (§3) is a schema failure: hard fail, fail closed.

This is a compare-and-swap on the lease head, so two writers can both survive
a union merge and replay still names exactly one winner. **The claim
predicate #115 calls after a rebase is: my acquire line is valid.** Because
every capacity-changing line requires the lease, a valid acquire also proves
nothing changed the reservations the writer validated against. A void claim
re-enters the wait loop of §1; it fails closed only when that wait or the push
budget is spent.

**Push budget N = 5** attempts per push (fetch, rebase, replay, push), with
1–5 s random backoff. Spent → fail closed with #115's exit code. Unrelated tip
moves (log and dashboard commits) cost one retry each and never void a claim.

**Two pushes per intent**, so a normal action adds two `state:` commits:

1. `acquire` (with `supersedes` if taking over) + recovery transitions + the
   new intent as `recorded` with its reservation, or as `refused`.
2. The intent's outcome + `release`.

A recovery that must mutate the broker (§4) pushes its result before the new
intent is recorded. If push 2 fails after the broker acted, the helper exits
non-zero with "acted, outcome not recorded" and alerts; the lease goes stale
and the next writer recovers the outcome from the broker. That is not a
fail-closed refusal: the broker action already happened.

### 3. Intent states

ADR 0005 §5 gave the floor. Refined:

| State | Persisted | Meaning | Reservation counts |
|---|---|---|---|
| `recorded` | push 1 | validated, reserved, pushed; no attempt yet confirmed | yes |
| *submitted* | **never** | a POST is in flight; process-local only | — |
| `acknowledged` | push 2 or recovery | an attempt is live at the broker (`new`, `accepted`, `pending_new`, `held`, `partially_filled`) | unfilled part |
| `lost` | push 2 or recovery | a POST got no usable answer and its id is still not found after the helper's lost-response budget | yes |
| `refused` | push 1 | the validator refused before any POST; reasons recorded | never taken |
| `filled` | push 2 or recovery | entry: attempt filled (partly filled then dead counts as `filled` at the filled qty). close: the sell filled but ADR 0005's completion predicate does not hold, so the intent is history and a new one is minted | no |
| `complete` | push 2 or recovery | close: ADR 0005 §3 predicate holds. replace-stop: replacement is verified coverage | no |
| `dead` | push 2 or recovery | no attempt landed or all are dead; `reason` ∈ `attempts_dead`, `not_landed`, `holder_died`, `restored` | no |

Non-terminal: `recorded`, `acknowledged`, `lost`. `submitted` is never
written because a push before every POST would double the commits and add
nothing: a crash after the push and before or during the POST looks the same
in the store as `recorded`, and recovery resolves both the same way, by
walking the intent's attempt ids at the broker (ADR 0005 §1).

Legal transitions: `recorded → acknowledged | lost | filled | complete | dead`;
`acknowledged → filled | complete | dead`; `lost → acknowledged | filled |
complete | dead`; `filled → complete` (close only, same push). `refused` is
only ever a first line. Anything else is a schema failure.

### 4. Recovery: what each state needs when its writer dies

**Recovery** is the reconciliation of every non-terminal intent against the
broker. It runs inside every coordinated action, after acquire and before the
new intent, so **no new intent is accepted while any intent is non-terminal
and unreconciled**. Each non-terminal intent costs one or a few
`order-by-client` GETs.

The one mutation recovery may make is **restoring verified coverage**. It
never submits, completes or cancels a trade on a dead writer's behalf: the
decision died with the process and the next routine run re-decides.

| Died in | Broker shows | Recovery action → new state |
|---|---|---|
| `recorded` (holder's lease stale) | an attempt live / filled | adopt → `acknowledged` / `filled`, then the kind's completion check |
| | no attempt, symbol covered or not held | → `dead (holder_died)` |
| | no attempt, held and uncovered (died between cancel and sell or place) | re-place each canceled stop as a fixed stop at its own level with `rr-<canceled id>` (ADR 0002 restore identity), verify coverage → `dead (restored)` |
| `acknowledged` | still live | none, stays `acknowledged` |
| | filled / dead | → `filled` (then `complete` check for closes) / `dead (attempts_dead)` |
| `lost` | the attempt id now found | adopt as above |
| | still not found, before the session close | stays `lost`, reservation held |
| | still not found after the session close | → `dead (not_landed)` |

Holding a `lost` entry's reservation until the close is deliberately
conservative: it can only refuse buys, and by the close any landed day order
has filled or expired and is visible. Close and replace-stop intents reserve
nothing, so `lost` costs them nothing.

A stale `recorded` intent can only be found after expiry plus skew, at least
7 minutes after the holder's last possible POST. That is the repo's chosen
visibility budget for "no attempt found means not sent" (research 0007 left
it to us).

### 5. Who runs recovery

- **Every mutating helper**, as the first step of each coordinated action
  (§4). This is what ADR 0004's "every writer runs recovery at start" means:
  it is part of acquiring, not a separate routine step that can be skipped.
- **The protection monitor, every run**, even when it has nothing to mutate,
  so a dead writer's intents do not wait for the next trading routine. With
  #115 it has `contents: write`.
- **Read-only routines** (pre-market, daily-summary, weekly-review) never take
  the lease and never recover. They report non-terminal intents and lease
  takeovers in their run record ([#108](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/108)).

### 6. Reservations, and how they reach the engine

A **reservation** is the capacity a non-terminal entry intent holds against
rules 2, 3, 8 and 13 until the broker's own state shows it. It is not a
separate record: it is derived from the intent line (`symbol`, `qty`, the
validated `price`, `sector`) and its state. So no reservation can be orphaned
from its intent.

- **Taken** in push 1, only after validation passes. A refusal never takes
  one.
- **Counts** while the intent is `recorded`, `acknowledged` or `lost`, for
  the **unfilled** quantity × the validated price. Close and replace-stop
  intents reserve nothing (they reduce risk; expected sale proceeds are never
  credited).
- **Released** when the intent reaches `filled`, `complete`, `dead` or
  `refused`. A fill is the point at which `cash`, `positions` and the weekly
  fill count begin to carry it, so counting both would double it.
- **Read order**: whether a reservation still counts is decided from the
  attempt status read at the broker **before** `account` and `positions` are
  read. A fill landing between the two reads is then counted twice (refuses
  too much) rather than not at all (permits too much).
- **Rule 13 uses the validated price**, not a buffered one; adding a slippage
  buffer would be a policy change and needs a rulebook bump.

**Engine boundary: `PortfolioState` gains `reservations`**, a tuple of
`Reservation(intent_id, symbol, qty, price, sector)`, with **no default**
(like `is_paper`, a caller that forgets must fail loudly). The pure engine
counts them, rule by rule: a reserved symbol not held and not the fallback
takes a slot and a weekly trade; reserved notional adds to the symbol's
resulting position, to deployment and to the sector count, and is subtracted
from cash. `max_affordable_shares` uses the same view. Refusal messages name
the reserving intent ids.

Pre-subtracting in the coordinator was rejected: faking pending positions and
lowering cash would put rule logic (the fallback exemptions, add-to-held opens
no slot) in a second place where it would drift from the engine, and would
turn `PortfolioState`, documented as "a snapshot of the account, as read from
the broker", into a mix of broker fact and intent with no way to explain a
refusal.

Every reader that builds a `PortfolioState` for a buy decision, including
`validate_order.py --dry-run`, reads reservations from the store; if the store
is unreachable, buys are refused (ADR 0004 §1).

The pending-buy gate in `validate_mutation.py` stays in v1 as defence in
depth. Reservations make it redundant; retiring it is a v2 decision.

## Considered and rejected

- **Per-symbol leases.** See §1.
- **No lease, reservations only (pure optimistic concurrency).** Reservations
  plus push-as-CAS do serialize capacity, but nothing then stops two writers
  acting on one symbol at once (midday's close against the monitor's
  cancel-then-place), or two recoverers handling one stale intent.
- **A renewable lease.** Renewal is a push per renewal from a process that is
  supposed to be done in seconds; a fixed deadline under a fixed expiry gives
  the same guarantee with no extra writes.
- **Steal on expiry without recovery.** The taker would accept new intents
  while the dead holder's order might still be live, which is the duplicate
  this coordinator exists to prevent.
- **Recovery completes the dead writer's action.** A sell or a tighten
  decided before a crash may be wrong minutes later; the routine re-decides.
  Only restoring coverage is safe to automate, and it is already the ADR 0004
  exception.
- **A push before every POST (`submitted` persisted).** See §3.

## Consequences

- Two `state:` commits per mutating action, a few per day.
- Worst-case unprotected window after a holder dies mid-close or mid-replace
  is expiry plus skew (12 min) plus the time to the next coordinated action or
  monitor run. With the external dispatcher of
  [#123](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/123)
  that adds at most one 30-minute monitor interval; on GitHub's own schedule
  it is bounded only by the next run GitHub does not drop, which is #123's
  problem, not this ADR's.
- Exit codes for "lease wait exhausted" and "acted, outcome not recorded" are
  new; #100 assigns them alongside #115's fail-closed code, without reusing
  ADR 0006's coverage codes.
- `PortfolioState` construction sites and test fixtures must pass
  `reservations`.
- The concurrency drill of
  [#112](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/112)
  should include a killed holder: kill a helper after push 1, check the next
  writer waits, takes over after expiry plus skew, and recovers before acting.
- I am not certain Alpaca sets `filled_at` on a buy that partly filled and was
  then canceled; `trades_this_week` counts only orders with `filled_at`. #100
  must check this against the broker and make the weekly count and the
  `filled` state agree.
