# TRADING-ROUTINE systems grade — Alpaca reconcile + gates + callers

Research note for matt PHASE 2 (systems grade). Researched 2026-09-10.
Primary sources only: current Alpaca docs/SDK, GitHub issue #32, this repo's
code and docs. **No trading judgment. No new live broker tests** (0001/0002
empirical results are cited as prior primary observation, not re-run).

Companion notes:
- `docs/research/0001-alpaca-atomic-entry-plus-protective-stop.md` (2026-08-11)
- `docs/research/0002-alpaca-share-reservation-and-qty-available.md` (2026-08-11)

---

## 1) Alpaca atomic entry+stop / `qty_available` — reconcile 0001 & 0002 vs current docs

### 1a — Atomic entry + protective stop (OTO / bracket)

| Claim in 0001 | Status vs current primary docs (2026-09-10) |
|---|---|
| OTO/bracket places entry + protective leg in one request; legs activate after entry completely filled | **Still stated.** Docs: bracket is OTOCO; OTO is entry + one of take-profit/stop-loss; "second and third orders won't be active until the first order is completely filled." ([Orders at Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca)) |
| `stop_loss` requires `stop_price` (optional `limit_price`) | **Still stated.** Same page: stop_loss needs mandatory `stop_price`. Official SDK: `StopLossRequest(*, stop_price: float, limit_price: float | None = None)` — no trail fields. ([SDK requests](https://alpaca.markets/sdks/python/api_reference/trading/requests.html)) |
| Trailing stop **cannot** be the protective leg of bracket/OCO; single orders only; "in the future" for bracket/OCO legs | **Still stated verbatim.** "Trailing stop orders are currently supported only with single orders. However, we plan to support trailing stop as the stop loss leg of bracket/OCO orders in the future." ([Orders at Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca) section Trailing Stop Orders) |
| Extended hours unsupported for advanced orders; TIF day/gtc only | **Still stated.** |
| Silent downgrade when both `stop_price` and `trail_percent` sent in `stop_loss` | **Still undocumented in prose.** Remains empirical-only from 0001 (PAPER, 2026-08-11). Docs still do not describe this failure mode. |
| PDT fields gone; PDT rejection moot | **Still primary.** Changelog: PDT/DTBP fields deprecated, removal **2026-07-06**. ([changelog](https://docs.alpaca.markets/us/changelog/2026-06-03-pdt-651df23); [end of PDT](https://docs.alpaca.markets/us/docs/understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt)). Today is after that date; 0001's "fields absent on GET /v2/account" observation is consistent with the changelog. |

**Reconcile verdict for 0001:** Doc-backed claims remain accurate. No primary-source reversal of "atomicity XOR trailing protective leg." Open gaps named in 0001 (partial-fill terminal behaviour for OTO entry; IMD vs bracket) remain **unsettled by docs**; this note did not re-test.

### 1b — `qty_available` / share reservation

| Claim in 0002 | Status vs current primary docs |
|---|---|
| `qty_available` = shares available minus open orders / locked for covered call | **Still the schema gloss.** ([GET all open positions](https://docs.alpaca.markets/reference/getallopenpositions) OpenAPI `Position.qty_available`) |
| Prose does not explain that open sell/trailing stops hold shares | **Still true.** No new prose sentence found on docs.alpaca.markets explaining reservation mechanics beyond the schema string. |
| Engine `_validate_sell` uses `held.qty` not `qty_available`; `Position` has no `qty_available` | **Still true in code today** (see section 3). `risk_engine/models.py` `Position` fields: `symbol`, `qty`, `market_value` only. `scripts/validate_order.py` `read_portfolio` still drops `qty_available` when building `Position`. |

**Reconcile verdict for 0002:** Schema definition unchanged. Code gap (`qty` vs `qty_available`) still present. Empirical 403 / cancel-then-sell / midday order-bug findings were not re-run; they remain prior observation, not re-verified on 2026-09-10.

---

## 2) GitHub issue #32 — `validate_stop_change` uncalled

**Issue:** [#32 How is a trail tightening validated?](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/32)  
**State (2026-09-10 via `gh issue view 32`):** **OPEN**

Issue body already asserts: `validate_stop_change` speaks in stop **prices**, not `_TRAIL_LADDER`; `required_trail_percent` has no validation attached; both have zero non-test callers.

### Callers search (repo, 2026-09-10)

`grep -rn validate_stop_change` (excluding `.venv` / `__pycache__`):

| Path | Role |
|---|---|
| `risk_engine/engine.py` | definition |
| `risk_engine/__init__.py` | re-export |
| `tests/test_risk_engine.py` | unit tests |
| `ARCHITECTURE.md` | documentation mention |

**No production / routine / script callers.** Confirms #32's claim.

Same pattern for `required_trail_percent`: definition + `__init__` + tests only.

---

## 3) Who calls `risk_engine` / `validate_order` — `/trade`-only vs routines

### Production / operator entry points that invoke `validate_order`

| Caller | How |
|---|---|
| `scripts/validate_order.py` | imports and calls `validate_order(proposal, state)` |
| `.claude/commands/trade.md` | Instructs: `python3 scripts/validate_order.py` before order |
| `README.md` / `ARCHITECTURE.md` | Document the boundary; not executable callers |

### Tests / ledger (not trade submission)

| Caller | How |
|---|---|
| `tests/test_risk_engine.py` | direct `validate_order` / `validate_stop_change` |
| `tests/test_ledger.py` | `validate_order` to build ledger fixtures |
| `ledger/store.py` | imports `OrderProposal`, `ValidationResult` types only |

### Routines — do not call the engine

`grep` of `routines/*.md` and `.claude/commands/*.md` for `validate_order` / `risk_engine`:

- **Only** `.claude/commands/trade.md` references `validate_order.py` / `risk_engine`.
- Scheduled/prose routines (`routines/market-open.md`, `midday.md`, `pre-market.md`, `daily-summary.md`, `weekly-review.md` and `.claude/commands/` mirrors) call `bash scripts/alpaca.sh` directly — **no** `validate_order.py` step.

Matches `ARCHITECTURE.md`: "The five routines are unguarded. Only `/trade` currently calls the risk engine."

**Prove `/trade`-only vs routines:** True for `validate_order` as an enforceable boundary. Routines are prose + `alpaca.sh` only.

---

## 4) Paper dual-gate — `alpaca.sh` + engine account-mode

Documented in `ARCHITECTURE.md` section "Paper-only posture" as two independent guards.

### Gate A — `scripts/alpaca.sh` (transport)

- Default: `API="${ALPACA_ENDPOINT:-https://paper-api.alpaca.markets/v2}"` (`scripts/alpaca.sh`).
- Hard-fail **before credentials** if endpoint string does not contain `paper-api.alpaca.markets` unless `ALPACA_ALLOW_LIVE=1` (exit 4).
- Env load: `scripts/_env.sh` — process env wins over `.env`.

### Gate B — `risk_engine` account mode (validation)

- `PortfolioState.is_paper: bool` — required, no default (`risk_engine/models.py`).
- `validate_order`: if `not portfolio.is_paper` then `Violation(Rule.PAPER_ACCOUNT_ONLY)` for buys and sells (`risk_engine/engine.py`).
- `scripts/validate_order.py` `_is_paper()`: `"paper-api.alpaca.markets" in` `ALPACA_ENDPOINT` (default paper URL).

**Dual-gate implication for routines:** Gate A applies to every `alpaca.sh` call. Gate B applies only when something calls `validate_order` — today **`/trade` via `scripts/validate_order.py`**, not the five routines. Routines have transport paper-guard only.

---

## Bottom line (facts only)

1. **0001/0002 vs Alpaca docs:** Core doc claims still hold (OTO/bracket atomic with fixed `stop_price` leg; trailing not allowed as advanced-order stop-loss leg; `qty_available` schema gloss unchanged; PDT removal changelog still primary). Silent-downgrade and reservation 403 behaviour remain empirical/undocumented as in the prior notes.
2. **#32 OPEN;** `validate_stop_change` / `required_trail_percent` still have **zero non-test callers**.
3. **`validate_order` is `/trade` (+ CLI script + tests/ledger), not routines.** Routines submit via `alpaca.sh` without the engine.
4. **Paper dual-gate exists as designed:** `alpaca.sh` endpoint refuse + engine `is_paper` — second gate only fires on the `/trade` path.

## Sources

- https://docs.alpaca.markets/docs/orders-at-alpaca — bracket/OTO/trailing stop (fetched 2026-09-10)
- https://docs.alpaca.markets/reference/getallopenpositions — `qty_available` schema (fetched 2026-09-10)
- https://alpaca.markets/sdks/python/api_reference/trading/requests.html — `StopLossRequest` / `TrailingStopOrderRequest` (fetched 2026-09-10)
- https://docs.alpaca.markets/us/changelog/2026-06-03-pdt-651df23 — PDT/DTBP removal 2026-07-06
- https://docs.alpaca.markets/us/docs/understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt
- https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/32 — OPEN
- Repo working tree: `risk_engine/engine.py`, `risk_engine/models.py`, `scripts/alpaca.sh`, `scripts/_env.sh`, `scripts/validate_order.py`, `ARCHITECTURE.md`, `routines/*.md`, `.claude/commands/*.md`, `tests/test_risk_engine.py`
- Prior notes: `docs/research/0001-…`, `docs/research/0002-…`

No blog posts or third-party forums used as authority.
