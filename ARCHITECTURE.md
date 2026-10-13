# Architecture

This system lets a language model trade a paper account. The interesting
engineering problem is not "how does the model pick stocks" — it is **how do you
stop a non-deterministic component from doing something irreversible**.

Everything below follows from that.

## The three-way split

The single most important structural decision here is keeping these apart.
Blur any two and you get a system where you cannot answer "why did this order
exist, and who allowed it."

| Component | Role | Where |
|---|---|---|
| **Risk engine** | The validation layer. Deterministic. Says no. | `risk_engine/` |
| **Working memory** | What the model reads to know what it is doing. | `memory/*.md` |
| **Ledger** | Immutable record: proposed → decided → submitted → broker response. | `ledger/` (Postgres) |

The risk engine does not remember. The memory does not decide. The ledger does
neither — it only records. This is deliberate: the original design had the
markdown logs serving as *both* live operational state and historical record,
which makes reconciliation and after-the-fact audit ambiguous.

## Control flow

```
Model proposes a trade
        ↓
scripts/validate_order.py        ← instructed pre-check (routines / commands)
        ↓
risk_engine.validate_order()     ← deterministic; returns every broken rule
        ↓   (refused → exit 3, nothing is sent)
        ↓   (approved → caller sets ALPACA_RISK_OK=1)
scripts/alpaca.sh                ← caller intent flag (exit 5 if absent)
        ↓
scripts/validate_mutation.py     ← re-check exact payload against broker state
        ↓
scripts/account_pin.py check     ← broker account_number == profile pin (exit 8)
        ↓
Alpaca paper API                 ← production or drill profile (docs/ACCOUNTS.md)
        ↓
ledger (Postgres)                ← preflight + response record when configured (T4)
```

When configured, `validate_order.py` persists every verdict via `ledger.live_path`; after
`alpaca.sh order`, callers record the broker response. Execution is not yet a durable transaction (#19).

The model may propose. Routines retain `validate_order.py` as a preflight and
ledger decision step. `ALPACA_RISK_OK=1` is only caller intent: `alpaca.sh` also
runs `scripts/validate_mutation.py` against the exact command/body it will send.
The mutation gate checks actual broker asset class and current portfolio;
buys require a fresh ask, no outstanding buy, a GTC OTO and compliant fixed
protection. Bulk `cancel-all` and `close-all` are refused.

This closes the old payload-versus-approval gap. It does not isolate credentials
from the agent or make cancel→place atomic.

### The coordinator (ADR 0010)

Every broker mutation is one **coordinated action** behind
`scripts/coordinator.py: coordinate(body, ...)`. The three mutation helpers
(`submit_entry.py`, `close_position.py`, `replace_stop.py`; the monitor acts
only through `replace_stop.py`) call it with their own logic as the body, so
the routines' one-line call sites are unchanged.

```
fetch + replay state/events.jsonl (ADR 0004)
        ↓   live holder → poll every 15 s, mutate nothing (bounded: expiry + skew)
        ↓   stale holder (expires_at + 2 min) → take over with `supersedes`
recover every non-terminal intent against the broker (ADR 0010 §4)
        ↓   only mutation: re-place a dead writer's canceled stop as rr-<id>, pushed first
body validates with PortfolioState.reservations from the store
        ↓   (attempt statuses read before account / positions)
push 1: acquire + recovery transitions + intent `recorded` (or `refused` + release)
        ↓
mutations via session.run / session.post   ← none after the 5-minute deadline;
        ↓                                     lost response → re-POST the same id
push 2: outcome settled from broker state + release
```

- **Store fit.** Intent lines carry `intent`, `state`, `lease` (the acquire
  line's id); the first line carries `action`, `symbol` and, for entries,
  `qty`/`price`/`sector` (the reservation) or, for closes and replacements, the
  stop ids it will cancel. Replay (`coordinator.fold`) keeps the lease head and
  holder; an intent line under a void or released lease is ignored; an illegal
  transition under the valid lease fails closed. A claim that lost after a
  rebase is withdrawn (`kind: withdraw`) and the writer waits again.
- **Reservations** are derived, never stored apart from their intent:
  `recorded`/`lost` entries reserve all their shares, `acknowledged` ones the
  unfilled part. `validate_order.py` and `validate_mutation.py` (inside
  `alpaca.sh`, excluding the attempt's own intent) read them too, and refuse
  buys when the store is unreachable. The pending-buy gate stays as defence in
  depth.
- **Outcome states**: `acknowledged`, `lost` (unknown after the re-POST budget;
  an entry keeps its reservation until the next 16:00 New York close), `filled`
  (a partly filled then dead buy counts at the filled quantity, as does
  `trades_this_week`), `complete`, `dead` (`attempts_dead`, `not_landed`,
  `holder_died`, `restored`). A close or replacement whose cancel left the
  position uncovered stays `recorded`, so the next recovery re-places the stop.
  Recovery resolves a `recorded` intent only once its writer is provably past
  its last POST (lease superseded, or expiry + skew since the line); before
  that it keeps its reservation and a rerun resumes the same intent. A POST
  whose lookup failed is `lost`, never `dead`. A restore that cannot verify
  coverage closes the dead intent, alerts, and makes the action exit 8, without
  blocking later actions.
- **Fail closed.** Store unreachable → every mutation refuses (exit 10) except
  a stop on a held position with none (ADR 0004 §1), which alerts. Lease wait
  exhausted → exit 11. Broker acted but push 2 failed → exit 12 and an alert;
  the lease goes stale and the next writer recovers the outcome.
- **Who recovers**: every coordinated action first; the protection monitor on
  every live run (`--dry-run` only reports); `python3 scripts/coordinator.py
  status` is the read-only view for run records.
- **Drill hooks** (#112): `COORDINATOR_FAULT=after_record | after_cancel |
  after_post | before_release | after_recovery_push` kills the helper (exit 97)
  at that point; `lose_response` drops the first POST answer and lookup so a
  landed order takes the lost-response path. Drill profile
  (`ALPACA_PROFILE=drill`) only; anywhere else it is a hard error. Local `/trade` writes through the dedicated clone with
  `TRADING_STATE_STORE=local`.

Stop replacement (trail tighten, fixed→trail conversion, expiry renewal) runs
only through `scripts/replace_stop.py`: validate the exact replacement while
the old stop still rests, cancel, confirm `canceled` from broker state, submit
with `client_order_id=rs-<old id>`, and on failure re-place the old level
(`rr-<old id>`). Every step is re-derived from the broker, so rerunning the
same command after a crash resumes without duplicates. The mutation gate reads
the replaced stop's `stop_price` via that client id (or any same-symbol stop
canceled in the last 15 minutes), so a canceled stop's floor still binds.

Entries and exits resume by *intent* (ADR 0005, amending ADR 0003 §3). An
intent `<en|cl>-<YYYYMMDD>-<SYM>[-<seq>]` names one requested action; each POST
is an attempt whose client order id is the intent id, then `-r1`..`-r5` once
the broker confirms the previous attempt dead. One shared resolver,
`scripts/execution_identity.py`, walks the attempts for both helpers (live or
filled is authoritative, dead is skipped, anything else hard-fails), adopts a
live attempt from today or yesterday so a rerun across UTC midnight finds it,
and honours an explicit `--intent` on any day; both helpers print the intent
and a `rerun` command carrying it. `scripts/submit_entry.py` submits the OTO
buy under the next free attempt, so a dead attempt no longer blocks the symbol.
`scripts/close_position.py` performs cancel→close: preflight while the stop
rests, cancel and poll to `canceled`, re-read holdings, sell, confirm. A close
is complete only when the symbol is not held and no buy is live; a filled close
attempt proves an earlier position lifecycle ended, so a same-day re-entry is
closed under a new intent (`-2`). An unconfirmed sell after a confirmed cancel
is exit 8 (naked incident).

All three scripts derive their exit code from **broker coverage, not from the
mutations this process made**. Before classifying a refusal (exit 3) or a
failed read (exit 4) they check the symbol's live coverage through
`risk_engine.reconciliation` — the same definition `doctor.py --broker` uses:
an unexpired GTC stop resting as `new` for the full held quantity. A held
position without that verified coverage is exit 8 whichever process removed
the stop, so a rerun after an earlier run cancelled and died never reports
"refused; the stop still protects". Exit 3 therefore means a verified stop
rests and nothing changed; exit 4 means nothing changed and no uncovered
position was observed.

Strategy constants are versioned in `risk_engine/versions.py` (`V1` frozen,
`V2`). The approved version is `"active"` in `docs/rulebook-pins.json`.
`scripts/strategy_version.bind()` binds a run to it when `STRATEGY_VERSION`
(required), the rulebook marker and the rulebook hash all agree. Each of the
following refuses to mutate when the run is unbound: `submit_entry.py`,
`close_position.py`, `replace_stop.py`, `validate_mutation.py` and the
monitor. The one exception is protective-stop restoration: `replace_stop`
resuming after an earlier run's cancel on a held position without verified
coverage. It places the `rs-`/`rr-` stop under the approved version, sends no
cancel, and alerts (ADR 0011). Protection also runs
without any Claude session: `.github/workflows/protection-monitor.yml` runs
`scripts/protection_monitor.py` (cron intent every 30 minutes; see
"Monitoring service level" for what is actually delivered), which plans with
the pure `risk_engine/monitor.py` (coverage, renew, convert, tighten, standing
holds) and acts only through `scripts/replace_stop.py`. It never reads the ledger.
Round trips, cooldown and sector streaks come from broker fills via
`risk_engine/blotter.py`, not from markdown.

## Why the risk engine is a pure module

`risk_engine/` performs no I/O: no network, no database, no clock. Consequences:

- Every rule is exhaustively testable, which is why 57 tests cost almost
  nothing to write and run in 0.03s.
- The rules can be reasoned about without a broker account.
- The dangerous, untestable part (network calls to a broker) is pushed to the
  edges where it belongs.

Money is `Decimal` throughout, and **floats are rejected at the boundary rather
than converted**. Accepting `0.1` as a float means storing
`0.1000000000000000055511151231257827021181583404541015625`, and a position-size
check that is off by a cent is a bug you find in production rather than review.

A refusal returns **every** violated rule, not the first one — so a refusal is
auditable, not a bare `False`.

## What is enforced in code vs. left to judgment

Enforced (`risk_engine/engine.py`, each with a passing and a failing test) and
reached on `/trade`, `market-open`, and `midday` via `scripts/validate_order.py`:

paper-account-only · stocks-only · max 6 positions · max 20% per position ·
max 3 new trades per week · sufficient cash · 85% deployment ceiling ·
unambiguous protection on every buy · fixed entry stop 9.5–10.5% below entry
or exactly 10% entry trail · non-equity symbol formats rejected

The position-count, position-size, weekly-trade, cash and deployment rules
(and v2's sector cap) also count **reservations**: the capacity an unfinished
entry intent holds until the broker shows it ([ADR 0010](docs/adr/0010-account-wide-lease-reservations-and-intent-recovery.md) §6).
`PortfolioState.reservations` is required, like `is_paper`, so a buy decision
cannot forget them. The engine counts them rule by rule rather than the caller
pre-subtracting them: a reserved new symbol takes one slot however many intents
reserve it; an add to a held name takes no slot; every non-fallback reservation
is a weekly trade; all reserved notional is deployed and not available cash;
the fallback is exempt from the counts, never from the money. Refusals name the
reserving intent ids, and `max_affordable_shares` uses the same view.
Every caller reads them from the state store through the coordinator (see
"The coordinator" above).

Enforced on midday trail/stop *changes* via `scripts/validate_stop_change.py`
(T2 / [issue #32](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/32)):

- **A stop never moves down**, and **never within 3% of price on a stop
  *change*** — `validate_stop_change` (`risk_engine/engine.py`).
- **The trail ladder** (10% → 7% at +15% → 5% at +20%) —
  `required_trail_percent` (`risk_engine/engine.py`). Midday asks the CLI for
  the required trail, then validates the proposed change; the CLI composes
  both functions (ladder floor + replacement stop prices against the actual broker stop_price so
  the old high-water-mark floor is preserved). Tightening runs through
  `scripts/replace_stop.py` (resumable cancel→place); making it atomic needs
  [#40](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/40)
  (OPEN — do not invent PATCH).

Deliberately **not** enforced, and named in `risk_engine.UNMECHANISED` rather
than quietly dropped:

- **Sector momentum**, **catalyst quality**, **patience over activity** —
  judgments, not predicates.
- **The minimum-deployment backstop.** A safety layer refuses orders; it never
  *compels* one. Enforcing a mandate to add risk belongs in the routines.
- **Cut losers at −7%** — an exit trigger evaluated against live prices, not a
  property of a proposed order.
- **Exit a sector after 2 failed trades** — mechanisable in principle, but
  `TRADE-LOG.md` records no sector field, so it cannot be computed. Add the
  field and this rule graduates into the engine.

Knowing which rules were deliberately left to a human is as much a design
decision as automating the rest.

## Deliberate deferrals

Named here because a system honestly described mid-evolution is more useful
than one described aspirationally.

- **Markdown is still the operational store.** Postgres is the ledger, not the
  system of record. Migrating the five routines to SQL is the end state; doing
  it half-way would stop the bot trading and destroy the track record, which is
  the asset this whole repo exists to build. **T4 (live path writes):** 
  `scripts/validate_order.py` mandatorily calls `ledger.live_path.persist_decision`
  (approved and refused; exit 6 if a configured ledger write fails; with
  `DATABASE_URL` unset the ledger is disabled and reported, not fatal — the cloud
  routines have no database), and mutating order
  paths instruct `scripts/record_broker_response.py` (`persist_broker_response` →
  existing `Ledger.record_submission` / `record_stop`). That makes the ledger
  *additive and mandatory on the execution path*, not yet *authoritative* —
  routines still read `memory/*.md` for operational state
  ([#28](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/28)).
  Validate↔submit token binding remains
  [#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19) /
  [#26](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/26).
- **OTO entry is wired; on-entry convergence is wired; conversion/sell windows remain.**
  `routines/market-open.md` and `/trade` submit buys as Alpaca `oto` with a fixed
  `stop_price` leg (`risk_engine.protection` / `scripts/build_oto_order.py`,
  ADR 0002), then convert cancel→trailing after a *complete* fill
  (`filled_qty != qty` is an incident / hard-fail). Market-open and midday also
  **scan open orders on entry** for leftover fixed legs and convert them
  via `scripts/replace_stop.py` — not wishful "next routine" prose. A
  sub-second, recoverable window remains on replacement and on
  `scripts/close_position.py` (cancel→close). Collapsing trail-tighten via `PATCH` needs
  [#40](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/40)
  (OPEN research — do not invent). Idempotency is per intent: recorded in the
  committed state store before any POST (ADR 0004, ADR 0010) and recoverable
  from the broker by walking deterministic client ids (`en-`, `cl-` intents
  with `-rN` attempts; `rs-`, `rr-` keyed on the replaced stop).
- **Read-only reconciliation, not a scheduled loop.** `scripts/doctor.py --broker`
  compares held quantities against current, unexpired GTC protective orders via
  `risk_engine.reconciliation`. It flags missing, excess and ambiguous coverage.
  The recovery scripts (`submit_entry`, `replace_stop`, `close_position`) read
  the same per-symbol coverage before classifying any refusal or read failure.
  `scripts/protection_monitor.py` on the `protection-monitor` workflow adds
  the scheduled loop with renew/convert/tighten and email on any issue;
  running since 2026-09-29, at the cadence measured under "Monitoring
  service level" below.
  `scripts/reconcile_equity.py` (pure logic in `risk_engine/accounting.py`)
  rebuilds cash, holdings and every past session's equity from broker
  activities and SIP closes and hard-fails `daily-summary` on an unexplained
  difference (ADR 0008).
- **Scheduled routine gates (T1 + T2).** `market-open` and `midday` (and `/trade`)
  instruct `scripts/validate_order.py` before every order-mutating `alpaca.sh`
  path; `alpaca.sh` hard-refuses `order`/`close`/`cancel` (and `*-all`) with
  **exit 5** unless `ALPACA_RISK_OK=1`. Midday trail/stop *changes* also go
  through `scripts/validate_stop_change.py` (`required_trail_percent` +
  `validate_stop_change`, issue #32 / T2) before cancel→replace. The wrapper additionally revalidates the exact mutation.
  The coordinator (ADR 0010) serializes the mutating writers and reserves capacity; validate↔submit token binding stays #19 / #26. Read-only subcommands stay ungated.
  Pre-market, daily-summary, and weekly-review are read-only.
- **Single user, paper only.** No multi-tenancy, no RBAC, no credential
  encryption, no live trading. There is one user and one paper account;
  building tenancy before a tenant is the expensive mistake.

## Monitoring service level

Decided in ADR 0007 from the run history in `docs/research/0008` and the
delivery survey in `docs/research/0009`.

| Term | Commitment |
|---|---|
| Protection check | One successful run of `scripts/protection_monitor.py` against live broker state (coverage verified, due actions done). A `dry_run=true` dispatch is not one. |
| Maximum protection-check delay | **90 minutes** while the exchange is open (09:30–16:00 ET, Alpaca trading days). Three cron slots: tolerates two consecutive dropped slots. |
| Who measures | `scripts/heartbeat.py`, once per session after the close, from the completion time of every successful live `protection-monitor` run (GitHub Actions run history; the workflow's `run-name` puts the mode in `display_title`: `protection-monitor live` or `protection-monitor dry run`). `scripts/protection_sla.py` holds the arithmetic. |
| Miss | A **stale window**. Reported as one heartbeat issue naming each window and the total stale minutes (exit 5, email). Not a trading refusal: the broker holds the stops. Market-open re-verifies coverage itself (`protection_monitor.py --dry-run`) before any buy and places none while coverage is short. |
| Alert delivery | `scripts/email.sh` captures the Resend id and reads `last_event` back. Exit 0 only when Resend accepted the message and has not reported a bounce or failure. A lost alert fails the calling job (exit 9) and the heartbeat workflow opens or comments a GitHub issue, the channel independent of Resend. |
| No-trade record | Market-open commits `market-open trades <date>` or `market-open no-trade <date>` every session, so the heartbeat distinguishes "did not run" from "nothing to do". |
| Dispatcher | `dispatcher/worker.js`, a Cloudflare Worker cron (`0,30 13-20 * * MON-FRI` UTC) that POSTs `workflow_dispatch` (`dry_run=false`) for `protection-monitor.yml` on `main` (ADR 0009). GitHub's own cron stays as a second source; the concurrency group serialises both. |
| Dispatcher credential | `GH_DISPATCH_TOKEN`: fine-grained PAT, this repository only, *Actions: read and write*. Stored as a Cloudflare Worker secret on `protection-dispatcher` — not in the repo, `.env` or GitHub secrets. Provisioned and rotated with `dispatcher/setup.sh`. |

**What GitHub's scheduler alone delivered (2026-09-29 to 2026-10-09):** two
scheduled runs per weekday, the first between 14:16 and 15:15 ET, none on
2026-10-05; the heartbeat cron fires 2.7–3.8 h late. That breaches the level
for roughly the first five hours of every session, which is why the monitor is
dispatched from outside GitHub's `schedule`: `workflow_dispatch` runs start
within seconds (research 0008, run 13). The dispatcher only starts runs; it
does not judge them. A dead worker, a failed dispatch or an expired PAT shows
up as the heartbeat's stale window, the same as a dropped cron slot. Until the
owner deploys it (`dispatcher/setup.sh`), the breach is reported every session.

## Paper-only posture

Two independent guards:

1. `scripts/alpaca.sh` defaults to the paper endpoint and **hard-fails** if
   `ALPACA_ENDPOINT` is anything else. No live override exists; the market-data
   endpoint is also exactly allowlisted.
2. `risk_engine` re-checks account mode itself rather than trusting that the
   upstream guard held, and refuses every order — buy *and* sell — on a
   non-paper account.

The second is not redundant. A safety property enforced in exactly one place is
one refactor away from being enforced in none.

## Testing

- `tests/test_risk_engine.py` — pure, no dependencies, always runs.
- `tests/test_ledger.py` — integration, against a **real Postgres**, skipped
  cleanly when `DATABASE_URL` is unset.
- `tests/test_t4_ledger_live_path.py` — seam tests for mandatory
  `persist_decision` / `persist_broker_response` on the live path (fake Ledger
  + one integration case when `DATABASE_URL` is set).

Splitting them means a Docker problem costs you the ledger tests and never the
safety tests.
