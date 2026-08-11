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
scripts/validate_order.py        ← the enforceable boundary
        ↓
risk_engine.validate_order()     ← deterministic; returns every broken rule
        ↓   (refused → exit 3, nothing is sent)
        ↓   (approved)
scripts/alpaca.sh                ← private broker adapter
        ↓
Alpaca paper API
        ↓
ledger (Postgres)                ← what was proposed, decided, sent, and returned
```

The model may propose. It may not bypass the engine on the paths the engine
guards. `scripts/alpaca.sh` used to be the public interface; it is now an
adapter *behind* the safety boundary, not the boundary itself.

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

Enforced (`risk_engine/engine.py`, each with a passing and a failing test):

paper-account-only · stocks-only · max 6 positions · max 20% per position ·
max 3 new trades per week · sufficient cash · 85% deployment ceiling ·
stop required on every buy · stop never lowered · stop never within 3% of price ·
the trail ladder (10% → 7% at +15% → 5% at +20%)

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
  the asset this whole repo exists to build.
- **The buy/stop gap.** `routines/market-open.md` and `/trade` submit the market
  buy and the protective stop as two separate calls. A failure between them
  leaves an unprotected position. The engine now refuses to *approve* an
  unprotected buy — protection is part of the order's definition — but closing
  the execution gap properly needs an orchestration layer with idempotency keys
  and a reconciliation pass. Not built.
- **No reconciliation loop.** Nothing yet compares local state against broker
  state or alerts when a position has no stop.
- **The five routines are unguarded.** Only `/trade` currently calls the risk
  engine. The scheduled routines still rely on prose instructions. This was a
  deliberate sequencing choice: staging the risky integration behind the manual
  path first, rather than changing an unattended flow that trades real orders
  every morning.
- **Single user, paper only.** No multi-tenancy, no RBAC, no credential
  encryption, no live trading. There is one user and one paper account;
  building tenancy before a tenant is the expensive mistake.

## Paper-only posture

Two independent guards:

1. `scripts/alpaca.sh` defaults to the paper endpoint and **hard-fails** if
   `ALPACA_ENDPOINT` is anything else, unless `ALPACA_ALLOW_LIVE=1` is set
   explicitly.
2. `risk_engine` re-checks account mode itself rather than trusting that the
   upstream guard held, and refuses every order — buy *and* sell — on a
   non-paper account.

The second is not redundant. A safety property enforced in exactly one place is
one refactor away from being enforced in none.

## Testing

- `tests/test_risk_engine.py` — pure, no dependencies, always runs.
- `tests/test_ledger.py` — integration, against a **real Postgres**, skipped
  cleanly when `DATABASE_URL` is unset.

Splitting them means a Docker problem costs you the ledger tests and never the
safety tests.
