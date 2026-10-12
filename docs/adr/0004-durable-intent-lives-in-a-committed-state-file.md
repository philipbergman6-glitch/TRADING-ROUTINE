# 0004. Durable intent lives in a committed state file; git push is the lock

Date: 2026-10-12. Status: accepted. Resolves
[#97](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/97)
on map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93).

## Context

The v1 audit (`docs/audits/2026-10-12/V1-FOUNDATION.md`, package 2) requires
one durable, account-wide owner that "serializes competing writers, reserves
capacity, persists intent before submission and reconciles outcomes", and
says a process-local lock is insufficient. Today nothing is shared across
runs: no lock, lease, reservation or intent store exists. The only cross-run
protection is deterministic client order IDs (`ARCHITECTURE.md`: "not a
durable intent store"), the pending-buy gate in `scripts/validate_mutation.py`
and the stop-floor check.

The writers that must share the store, and what each can reach today:

| Writer | Runs where | Alpaca | git push to `main` | Postgres |
|---|---|---|---|---|
| 5 cloud routines (pre-market, market-open, midday, daily-summary, weekly-review) | Claude cloud, disposable checkout, egress through a proxy that rewrites commit SHAs (`routines/market-open.md`, step 8) | yes | yes, observed daily (`market-open trades 2026-10-12` is on `main`) | **no** — no `DATABASE_URL`; raw TCP through the proxy is unverified |
| protection monitor (`protection-monitor.yml`) | GitHub Actions | yes | yes with `permissions: contents: write` (the dashboard workflow already pushes this way) | would need a new secret |
| local `/trade` | owner's machine | yes | yes | would need a local `DATABASE_URL` |
| CI (`tests.yml`) | GitHub Actions | no | no | yes, a throwaway service container |

Only market-open, midday, the monitor and `/trade` mutate the broker. All
five routines and the monitor will write run records
([#108](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/108)),
so the store must be reachable from every row above except CI.

Facts this decision leans on:

- Research 0007 (`research/alpaca-client-order-id`): Alpaca rejects a
  duplicate `client_order_id` with 422 and lookups reach back to account
  creation, but it publishes no visibility window after a lost response and
  cannot record a refusal or an intent that never submitted.
- The ledger's default idempotency key is `live-<uuid4>`
  (`ledger/live_path.py`), so its UNIQUE constraint prevents nothing today,
  and only CI sets `DATABASE_URL`. PR #65 once made the ledger mandatory and
  stopped the cloud routines from trading, because the dependency was not
  provisioned where the routines run.
- Every writer already uses `git push origin HEAD:main || { git pull --rebase
  origin main && git push origin HEAD:main; }` and verifies by commit
  subject because the cloud proxy rewrites SHAs. Push rejection on a moved
  tip is therefore an already-exercised path, not a new assumption.

## Decision

### 1. Fail-closed semantics come first

"Store unreachable" means any of: `git fetch origin main` fails; the push
budget is exhausted (the push is rejected more than N times, N chosen by
[#99](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/99));
the state file fails schema validation; or, after a rebase, replay shows the
writer's own claim is no longer the winning one.

When the store is unreachable, a writer **refuses every broker mutation that
adds risk or removes protection**: buys, sells and closes, cancels of a
protective order, and cancel-then-place stop replacements (renew, convert,
tighten). It exits with a distinct non-zero code and alerts. Refusal is
silent-failure-proof by construction: there is no "continue without the
store" flag.

One exception, chosen because the alternative is worse: **placing a new
protective stop on a position that has none** may proceed without the store.
Coverage is derived from broker state (ADR 0003, and
[#95](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/95)),
so this action is idempotent against the broker and the next run reconciles
it. Refusing it would leave a position unprotected to protect a record. The
writer still alerts that it acted without the store.

### 2. The store is an append-only file committed to `main`

Durable intent lives in `state/` on `main` as newline-delimited JSON, one
event per line, never rewritten. Current state is a replay of the file.
`git push` to `main` is the compare-and-swap: GitHub rejects a push whose
base is no longer the branch tip, so two writers cannot both land a claim on
the same base.

Write protocol, mandatory for every writer:

1. `git fetch origin main`; read the file from `FETCH_HEAD` (never from a
   stale checkout).
2. Replay, decide, append one or more lines.
3. Commit with subject `state: <writer> <intent id> [skip ci]` and push to
   `main`.
4. On rejection: fetch, rebase, **replay again** and confirm the claim is
   still the winning one under the replay rules
   [#99](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/99)
   defines. If it is, push again; if not, append a release line, push, and
   fail closed. Give up after the push budget and fail closed.
5. Only after the push is verified by subject on `origin/main` may the
   writer send the broker request the intent describes.

Fixed by this ADR; the record shapes are
[#99](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/99)
(intent, reservation, lease) and
[#108](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/108)
(run record):

- Location `state/`, not `memory/`: `memory/**` triggers the dashboard
  workflow and is the human narrative; `state/` is machine-written only.
- Every line carries `id`, `kind`, `at` (UTC ISO-8601), `writer` (routine
  or workflow name plus run id) and `schema` (integer). A line that fails
  validation is a hard failure for every reader.
- `.gitattributes` marks the file `merge=union` so concurrent appends rebase
  without textual conflict. Union merge is why step 4 must replay: two
  claims can both survive the merge, and only replay says which one won.
- The Postgres ledger stays optional and additive, exactly as today. It is
  not the intent store.

### 3. What each writer does

- **Cloud routines**: already fetch, reset and push `main`; they gain the
  protocol above and nothing else. No new environment variables.
- **Protection monitor**: `protection-monitor.yml` gains
  `permissions: contents: write`. Pushes made with `GITHUB_TOKEN` do not
  trigger other workflows, so there is no recursion.
- **Local `/trade`**: writes `state/` from a dedicated clone (for example
  under `~/.cache/trading-routine/`) and pushes straight to `main`. This is
  a deliberate exception to
  [#71](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/71),
  which has local runs commit `memory/` on a `log/<routine>-<date>` branch:
  an intent that waits in a pull request coordinates nothing. The owner's
  development checkout is never touched.
- **CI**: reads nothing from `state/`; tests use a local bare repository as
  `origin`.

### 4. Revisit triggers

Move to hosted Postgres (option a below) if any of these is observed:
more than two fail-closed aborts a week caused by push contention rather than
real conflicts; the state file exceeds 5 MB; a reader needs queries that
replay cannot answer in well under a second; or the proxy is shown to break
non-fast-forward rejection (the concurrency drill in
[#112](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/112)
checks this). The ledger schema and its 21 integration tests are kept
current for that day.

## Alternatives considered

- **(a) Hosted Postgres as the ledger-becomes-store.** Best primitives
  (transactions, row locks, UNIQUE), the schema and tests already exist, and
  it is the long-run direction of map #19. Rejected for v1 because it fails
  the reachability test today: the cloud routines have no `DATABASE_URL`,
  their egress goes through a proxy whose support for raw Postgres TCP is
  unverified, and every run would `pip install` the ledger extra before it
  could trade. It also costs money, adds six secret placements (five
  routines plus Actions) and adds a third-party outage mode to the trading
  path. The record of PR #65 shows what an unprovisioned mandatory ledger
  does: it stops the bot. It stays the revisit target.
- **(b) The broker as the store, via `client_order_id`.** Reachable from
  everyone and free, and research 0007 confirms it is a sound recovery
  index. Rejected as the *store* because it cannot hold anything that never
  reached Alpaca: a refusal, a reservation, a lease, a run record, or an
  intent whose POST was never sent. The audit requires intent persisted
  before submission. Kept as the recovery index: every intent records the
  client order id it will use, and recovery looks that id up.
- **(d) A GitHub-native primitive: repository variable, issue or Actions
  cache.** Repository variables have no compare-and-swap (last writer wins);
  an issue comment is append-only but gives no claim semantics; the Actions
  cache does refuse a duplicate key but is only writable from inside
  Actions, so the cloud routines could not use it. All three need a GitHub
  API token the routines do not have today. Rejected.
- **Process-local lock or lockfile in the checkout.** Named insufficient by
  the audit; every cloud run is a fresh checkout.
- **A committed SQLite file.** Binary, so no union merge and no readable
  diff of what two writers claimed. Rejected in favour of JSONL.

## Consequences

- Zero new cost and zero new secrets. The only configuration change is
  `permissions: contents: write` on the monitor workflow.
- `main` gains a few small `state:` commits per trading day. `tests.yml`
  runs on every push to `main`, which is why the subject carries
  `[skip ci]`; the dashboard workflow filters on `memory/**` and the
  heartbeat on workflow failures, so neither sees `state/` writes.
- The cloud proxy's SHA rewriting means verification is always by commit
  subject, never by SHA, and every write starts with a fetch. The
  concurrency drill in #112 must show one of two simultaneous writers being
  rejected and failing closed.
- A writer that dies after pushing its claim leaves the claim on `main`;
  lease expiry and stale-intent recovery are
  [#99](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/99)'s
  to define, and every writer runs recovery at start.
- Run records ([#108](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/108))
  use the same file and protocol; read-only routines write run records but
  never take a lease.
- `#28` on map #19 ("ledger authoritative") is narrowed, not answered: for
  v1 the committed state file is the authoritative execution record; the
  Postgres ledger's promotion to authority waits on a provisioned, reachable
  database and is out of this map's scope.
- Local `/trade` pushes `state/` to `main` directly, unlike its `memory/`
  writes. This is the one place the #71 local-branch rule is overridden.
