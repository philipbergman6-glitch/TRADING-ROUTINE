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
Alpaca paper API
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
from the agent, serialize independent routines, reserve cross-process capacity,
or make cancel→place atomic. Durable execution remains #19/#26.

Stop replacement (trail tighten, fixed→trail conversion, expiry renewal) runs
only through `scripts/replace_stop.py`: validate the exact replacement while
the old stop still rests, cancel, confirm `canceled` from broker state, submit
with `client_order_id=rs-<old id>`, and on failure re-place the old level
(`rr-<old id>`). Every step is re-derived from the broker, so rerunning the
same command after a crash resumes without duplicates. The mutation gate reads
the replaced stop's `stop_price` via that client id (or any same-symbol stop
canceled in the last 15 minutes), so a canceled stop's floor still binds.

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
  sub-second, recoverable window remains on replacement; cancel→close exits
  still have an unrecovered window. Collapsing trail-tighten via `PATCH` needs
  [#40](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/40)
  (OPEN research — do not invent). Idempotency keys + reconciliation loop still
  not built.
- **Read-only reconciliation, not a scheduled loop.** `scripts/doctor.py --broker`
  compares held quantities against current, unexpired GTC protective orders via
  `risk_engine.reconciliation`. It flags missing, excess and ambiguous coverage.
  Independent scheduling, incident delivery and automatic recovery remain open.
- **Scheduled routine gates (T1 + T2).** `market-open` and `midday` (and `/trade`)
  instruct `scripts/validate_order.py` before every order-mutating `alpaca.sh`
  path; `alpaca.sh` hard-refuses `order`/`close`/`cancel` (and `*-all`) with
  **exit 5** unless `ALPACA_RISK_OK=1`. Midday trail/stop *changes* also go
  through `scripts/validate_stop_change.py` (`required_trail_percent` +
  `validate_stop_change`, issue #32 / T2) before cancel→replace. The wrapper additionally revalidates the exact mutation.
  A durable execution coordinator remains open (see #19 / #26). Read-only subcommands stay ungated.
  Pre-market, daily-summary, and weekly-review are read-only.
- **Single user, paper only.** No multi-tenancy, no RBAC, no credential
  encryption, no live trading. There is one user and one paper account;
  building tenancy before a tenant is the expensive mistake.

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
