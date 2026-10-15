# Trading Routine

An AI-assisted paper-trading system that runs itself every market day. A
Claude agent researches the market, proposes trades, and writes the reports.
A deterministic Python risk engine decides whether any order is allowed to
reach the broker. Nothing trades without passing the engine.

**[Live dashboard](https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/)** ·
[Architecture](ARCHITECTURE.md) · [Strategy spec](docs/STRATEGY-SPEC.md) ·
[Results audit](docs/research/0006-paper-results-reconciliation.md) ·
[Decision records](docs/adr/)

## At a glance

| | |
|---|---|
| Running since | 2026-04-27 on an Alpaca paper account ($100,000 start) |
| Scheduled routines | Four per trading day, every trading day, plus a Friday review |
| Risk engine | Pure Python, no I/O, every money value a `Decimal` |
| Tests | 979 (958 offline, 21 against a real Postgres in CI) |
| Monitoring | Independent protection monitor plus a daily heartbeat that emails on any miss |
| Execution | One coordinator: account-wide lease, intents recorded before the broker sees them, recovery that only restores coverage |
| Broker safety | Paper endpoints only, hard-coded; every mutation re-validated against its exact payload |

## How a trading day runs

Each routine is a markdown instruction file the cloud agent reads fresh on
every run. The agent proposes. The scripts decide.

1. **Pre-market** (`routines/pre-market.md`): catalysts, macro context, two or
   three candidate ideas. Default answer is HOLD.
2. **Market open** (`routines/market-open.md`): each candidate goes through
   `validate_order.py` and, if accepted, `submit_entry.py`. A buy is always a
   bracket: market entry plus a fixed protective stop in one atomic order.
3. **Midday** (`routines/midday.md`): cut losers at the rule threshold, tighten
   stops on winners through `replace_stop.py`, re-check each thesis.
4. **End of day** (`routines/daily-summary.md`): P&L, equity snapshot to the
   trade log, one email.
5. **Weekly review** (Fridays): statistics, a letter grade, lessons, and any
   proposed rule change for the next version.

Every run commits its log to `memory/`. The dashboard is rebuilt from those
logs by GitHub Actions, so what you see on the page is what the agent wrote.

## What keeps it safe

- **Agent is advice-only.** `/conviction` and research routines never place
  orders. Only `submit_entry.py`, `close_position.py` and `replace_stop.py`
  touch the broker, and each one validates first.
- **Risk engine is pure.** `risk_engine/` has no network, database or clock
  access. It takes a snapshot and a proposal and returns accept or reject with
  a reason. Float input is rejected at the boundary.
- **Exact-payload validation.** `scripts/alpaca.sh` refuses any non-paper
  endpoint before credentials are loaded, and re-runs `validate_mutation.py` on
  the exact JSON body of every order, cancel or replace.
- **Stops never go backwards.** Stop replacement validates before cancelling,
  confirms the cancel, restores the old level on failure, and resumes
  idempotently on rerun. The broker's actual resting stop price is the floor.
- **Independent protection monitor.** A separate GitHub Actions job, with no
  Claude involved, checks that every position has a live protective stop and
  renews or tightens per the ladder.
- **Heartbeat.** After each close a job confirms every expected routine
  committed, the monitor succeeded, and no workflow failed. A miss sends email.
- **Versioned strategy.** `STRATEGY_VERSION` selects a frozen parameter set in
  `risk_engine/versions.py`. The rulebook file is sha256-pinned, and
  `strategy_version.py` hard-fails before any order if version and pin disagree.
- **One writer at a time.** Every mutation runs inside `coordinator.py`
  (ADR 0010): an account-wide lease in a committed, append-only state file,
  the intent pushed to `main` before the broker sees it, capacity reserved
  from recorded intents, and recovery of unfinished intents that may only
  restore a stop, never open exposure. Each run leaves a run record (ADR 0012)
  with the code SHA, outcome, actions and refusals.

## Components

| Component | Responsibility |
|---|---|
| `risk_engine/` | Rules, sizing, order and protection payloads, coverage checks, fill-based blotter, equity accounting |
| `scripts/validate_order.py` | Pre-flight for a proposed buy: cash, sizing, sector cap, cooldown, stop distance |
| `scripts/validate_mutation.py` | Validate the exact broker payload against current account and asset data |
| `scripts/submit_entry.py` | Idempotent buy with protective leg |
| `scripts/close_position.py` | Recovered exit: cancel stop, confirm, sell, confirm |
| `scripts/replace_stop.py` | Resumable stop replacement with restore on failure |
| `scripts/coordinator.py` | Lease, intent recording, reservations and recovery around every broker mutation |
| `scripts/state_store.py`, `scripts/run_record.py` | Committed append-only state (`state/events.jsonl`): intents, leases, per-run provenance |
| `scripts/protection_monitor.py` | Scheduled coverage check and actions without Claude |
| `scripts/heartbeat.py` | Daily liveness check, emails on a miss |
| `scripts/blotter.py` | FIFO round trips, cooldowns and sector streaks from broker fills |
| `scripts/reconcile_equity.py` | Daily cash, holdings and equity reconciliation against the broker (exit 4 on an unexplained difference) |
| `scripts/alpaca.sh` | The only broker transport: paper-only, mutation gate, bounded timeouts |
| `ledger/` | Optional Postgres record of decisions, broker responses and audit events |
| `memory/` | Strategy rulebook, trade log, research log, weekly reviews |
| `routines/` | The instruction files the scheduled agent runs |
| `docs/dashboard/` | Generated dashboard, published through GitHub Pages |

## Results so far

Equity, benchmark comparison and the open book are on the
[dashboard](https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/),
rebuilt nightly from the logs. The full order, fill and fee history was pulled
read-only and reconciled to equity exactly in
[research 0006](docs/research/0006-paper-results-reconciliation.md). The
[strategy assessment](docs/STRATEGY-ASSESSMENT.md) grades each rule
keep/modify/discontinue, and [STRATEGY-SPEC.md](docs/STRATEGY-SPEC.md) freezes
v1 and specifies v2 so that forward results can be scored per version.

## Run it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/build_dashboard_data.py --check
```

`doctor.py` checks log parsing and dashboard consistency. Add `--broker` to
compare the paper account's positions and open orders against expected
protection (read-only). Configuration names are in `env.template`.

Broker calls default to the production paper account; `ALPACA_PROFILE=drill`
selects the isolated drill account (`docs/ACCOUNTS.md`; provision it with
`scripts/setup_drill_account.sh`).

Ledger tests run against an isolated Postgres:

```bash
.venv/bin/pip install -e ".[dev,ledger]"
docker compose up -d
DATABASE_URL=postgresql://trading:trading@localhost:5433/trading .venv/bin/python -m pytest -q
```

## Working on the code

Start with [AGENTS.md](AGENTS.md), which maps each kind of task to the files
and tests that own it, and the current
[engineering handoff](docs/PROJECT-STATUS.md). Durable design decisions live in
[docs/adr/](docs/adr/). Both Codex and Claude follow the same instructions
through `CLAUDE.md`.

## Roadmap

- v1 baseline frozen at tag `v1-baseline` (2026-10-13). Next: provision the
  Cloudflare cron dispatcher so the protection monitor meets its 90-minute
  service level (#130).
- Run the v2 rulebook as a scored 30-session paper segment at $10,000.
- Replace log tails in routines with a generated state brief (#69).
