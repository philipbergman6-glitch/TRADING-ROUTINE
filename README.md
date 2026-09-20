# Trading Routine

A paper-trading research platform: an agent proposes decisions, a deterministic
risk engine checks orders, and broker state must be reconciled before the
results can be trusted. The primary objective is to learn and prove the system
before using real money. There is no live-trading override.

[Dashboard](https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/) ·
[Architecture](ARCHITECTURE.md) · [Vocabulary](CONTEXT.md) ·
[September 17 diagnosis](docs/audits/2026-09-17/REPORT.md) ·
[Implementation status](docs/audits/2026-09-17/IMPLEMENTATION.md)

For development sessions, start with [AGENTS.md](AGENTS.md) and the current
[engineering handoff](docs/PROJECT-STATUS.md). Claude uses the same instructions
through `CLAUDE.md`.

## Components

| Component | Responsibility |
|---|---|
| `risk_engine/` | Pure rules, order/protection payloads, snapshot coverage checks |
| `scripts/validate_order.py` | Proposed-order preflight and optional Postgres decision record |
| `scripts/validate_mutation.py` | Validate the exact broker mutation against current account and asset data |
| `scripts/alpaca.sh` | Exact paper endpoint, mutation gate, bounded transport and HTTP status |
| `ledger/` | Postgres decisions, broker responses and append-only audit events |
| `memory/` | Agent context and historical observations; not independently reconciled accounting |
| `routines/` | Scheduled research, execution instructions and reporting |
| `docs/dashboard/` | Generated log observations plus explicitly dated commentary |

`ALPACA_RISK_OK=1` expresses caller intent. It does not bypass the mutation
validator. Buys must be GTC market OTO orders with a fixed protective leg in the
9.5–10.5% entry-distance band. Asset class and fresh ask are checked at submit;
pending buys block another buy. Market fills can still differ from the quote.
Stop-tightening validation requires the broker's actual resting stop price,
preserving its previous high-water mark across replacement. Stop replacement
runs through `scripts/replace_stop.py`, which validates before cancelling,
confirms the cancel, restores the old level on failure and resumes on rerun.

## Current limits

This remains an experimental paper system. Direct access to broker credentials
is not isolated from the agent. Cross-process account reservations, stable
broker idempotency for buys, a recovered cancel→close exit and an independently
scheduled protection monitor remain to be implemented. The ledger is optional
in cloud routines and does not yet capture the complete broker lifecycle.

The latest committed equity snapshot and benchmark periods are displayed on
the dashboard. They are log-derived, with reconstructed history and estimated
benchmark weeks. Historical rule compliance and live protection are not
certified; incomplete realized P&L/win-rate figures are withheld.

## Local checks

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/build_dashboard_data.py --check
```

The doctor command checks local log parsing and dashboard consistency.
`--broker` additionally reads the paper account's positions and open orders to
compare remaining protective quantities and expiries. It does not place orders,
repair protection, or send notifications. Exit 4 means a check failed or state
was unavailable. Offline success does not imply verified broker protection.

The database tests need the ledger extra and an isolated Postgres database:

```bash
.venv/bin/pip install -e ".[dev,ledger]"
docker compose up -d
DATABASE_URL=postgresql://trading:trading@localhost:5433/trading .venv/bin/python -m pytest -q
```

Do not point integration tests at a production ledger.

## Scheduled routines

Use the thin prompts in [routines/README.md](routines/README.md). Each cloud
routine syncs the repository and reads its current instruction file. Full
prompt copies in the scheduler become stale. Market-open and midday still
coordinate execution through instructions; their recovery behavior is not yet
a deterministic state machine.

Research and reporting routines must not place orders. The ad-hoc `/conviction`
command produces advice; `/trade` executes through the same validation path.

## Next milestone

Finish a durable execution coordinator and independent reconciliation, then
reconcile accounting and run a versioned forward paper experiment against
simple baselines. See the implementation status for completed changes,
remaining proof gates and deployment limits.
