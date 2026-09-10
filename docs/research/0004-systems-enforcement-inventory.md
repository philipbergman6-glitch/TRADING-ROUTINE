# Systems enforcement inventory — enforced vs claimed vs unguarded vs deferred

**Ticket:** [#56](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/56)  
**Parent map:** [#55](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/55)  
**Collected:** 2026-09-10  
**Sources:** repo code/docs; box evidence `/workspace/trading-routine-systems-evidence.md`; reviewer Phase 2 majors (via matt); companion `docs/research/0003-systems-grade-alpaca-gates-and-callers.md`.  
**Scope:** systems inventory only — **no grades** (those are #57–#60 + Philip).

---

## A) Enforced in callable code (non-test callers)

| Mechanism | Where | Notes |
|---|---|---|
| `validate_order` | `scripts/validate_order.py` (~162); instructed by `.claude/commands/trade.md` | Sole production CLI boundary for buys/sells that go through the engine |
| Paper hard-fail (shell) | `scripts/alpaca.sh` — refuse if endpoint lacks `paper-api.alpaca.markets` unless `ALPACA_ALLOW_LIVE=1` (`exit 4`) | Runs before credentials |
| Paper re-check (engine) | `risk_engine/engine.py` ~107–115 (`portfolio.is_paper`) | Independent of shell; `validate_order.py` `_is_paper()` from endpoint string |
| Mechanised order rules | `risk_engine/engine.py` via `validate_order` | paper-only · stocks-only · max 6 · 20% · 3 trades/week · cash · 85% deploy · stop required on buy · min 3% stop distance |

**Tests:** `uv run --with pytest pytest tests/test_risk_engine.py -q` → **57 passed** (2026-09-10).

---

## B) Claimed / tested but not called (claimed-looking)

| Symbol | Non-test callers | Tracking |
|---|---|---|
| `validate_stop_change` | **None** (definition + `__init__` + `tests/test_risk_engine.py` + docs) | [#32](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/32) OPEN |
| `required_trail_percent` / `_TRAIL_LADDER` | **None** outside tests | #32; midday still prose ladder |

ARCHITECTURE.md already warns: listing uncalled validators as “enforced” is the damaging doc error. Prefer ARCHITECTURE over README when they diverge (reviewer).

---

## C) Unguarded routine / order paths

Grep of `routines/*.md` for `validate_order` / `risk_engine` / `validate_stop` / `required_trail`: **no matches**.

| Path | Places/modifies orders? | Engine? |
|---|---|---|
| `routines/pre-market.md` | No (research / reads) | N/A |
| `routines/market-open.md` | Yes — `alpaca.sh order` buy + trailing stop | **No** — STEP 3 prose checklist; misses cash + 85% vs engine; no `validate_order` (reviewer) |
| `routines/midday.md` | Yes — close / cancel+replace trail | **No** — prose ladder; close-then-cancel cluster [#38](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/38) |
| `routines/daily-summary.md` | Reads via `alpaca.sh` | N/A |
| `routines/weekly-review.md` | Reads via `alpaca.sh` | N/A |
| `.claude/commands/trade.md` | Yes (HITL) | **Yes** — `validate_order.py` |

Related open: [#15](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/15) (bypass), [#18](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/18) (Bash blanket), [#26](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/26) (validate≠submit), [#39](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/39) (`curl -f`).

---

## D) Named deliberate deferrals (ARCHITECTURE)

From `ARCHITECTURE.md` “Deliberate deferrals” (+ ledger reality):

1. **Markdown still operational store** — Postgres ledger exists (`ledger/migrations/001_init.sql`: orders, validations, broker_responses, audit_events) but **execution path does not mandatorily write it**; `ledger.record_decision` / store usage is **tests-oriented** (reviewer: tests-only on live path). See [#28](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/28), map [#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19).
2. **Buy/stop gap** — market-open (and historical `/trade` shape) still two calls; engine requires protection on the *proposal*, orchestration/idempotency/reconcile not built. ADR 0002 / research 0001–0003.
3. **No reconciliation loop** — nothing compares local vs broker / alerts naked stops.
4. **Five routines unguarded** — deliberate sequencing; only `/trade` calls engine.
5. **Single user, paper only** — no multi-tenancy/RBAC/live.

**UNMECHANISED** (judgments, not predicates): sector momentum, catalyst quality, sector-exit-after-2, patience, min-deploy backstop, cut-losers-at-−7% — see `risk_engine.engine.UNMECHANISED`.

**CI:** `.github/workflows/tests.yml` (risk-engine pure + ledger integration); `dashboard.yml` rebuilds dashboard data.

---

## E) Inventory notes (not grades)

- **STOCKS_ONLY used for sell coherence** (reviewer) — inventory flag; may be wrong rule signal vs dedicated check; do not grade here.
- **README vs ARCHITECTURE** — README “deploying” / production language overclaims relative to ARCHITECTURE’s mid-evolution honesty; prefer ARCHITECTURE for chief.
- **Proposed gap tickets** (from box evidence; **cutoff is #60**, not auto-implement): wire midday trail through validators; market-open → `validate_order.py` before `alpaca.sh`; CLI for `validate_stop_change`; close cancel→replace window (#40); mandatory ledger on execution path; protection as part of validated buy not post-fill hope.

---

## F) Handoff

This file **closes #56**. Grilling #57–#60 may proceed (quant rubric on map #55). Keep implement destination [#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19) separate from assessment map #55.
