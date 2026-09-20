# Working in Trading Routine

This is an experimental paper-trading research platform. For engineering
tasks, maintain the software; running a trading routine is a separate task.

## Start a session

1. Read `docs/PROJECT-STATUS.md` for the last engineering handoff and open work.
2. Run `git status --short --branch` and `git log -5 --oneline`. Compare the
   handoff baseline with subsequent commits and local changes before relying
   on it. Preserve existing work.
3. Use the task map below to read the relevant implementation and tests.
   Load historical logs only for the dates or evidence the task needs.

The status file is a dated handoff, not live account state. Code and tests
establish implemented behavior; strategy and ADRs establish intended behavior.
If they disagree, identify the discrepancy rather than silently changing policy.

## Task map

| Task | Read / work here |
|---|---|
| Setup and local commands | `README.md`, `pyproject.toml`, `env.template` |
| Architecture or module boundaries | `ARCHITECTURE.md`; vocabulary in `CONTEXT.md`; decisions in `docs/adr/` |
| Risk rules and sizing | `memory/TRADING-STRATEGY.md`, `risk_engine/engine.py`, `risk_engine/models.py`, `tests/test_risk_engine.py` |
| Broker execution and stop recovery | `scripts/validate_order.py`, `scripts/validate_mutation.py`, `scripts/alpaca.sh`, `scripts/replace_stop.py`; `tests/test_broker_boundary.py`, `tests/test_mutation_validation.py`, `tests/test_replace_stop.py` |
| Protection payloads / coverage | `risk_engine/protection.py`, `risk_engine/reconciliation.py`, `scripts/validate_stop_change.py`, `scripts/doctor.py`; corresponding tests |
| Ledger / database | `ledger/live_path.py`, `ledger/store.py`, `ledger/migrations/`; `tests/test_ledger.py`, `tests/test_t4_ledger_live_path.py` |
| Routine or command behavior | Relevant `routines/<name>.md` and `.claude/commands/<name>.md`; `tests/test_t1_*` through `tests/test_t4_*` check their wiring |
| Dashboard and log parsing | `scripts/build_dashboard_data.py`, `scripts/deployment_status.py`, `docs/dashboard/index.html`; corresponding tests |
| Audit findings and remaining proof | `docs/audits/2026-09-17/IMPLEMENTATION.md` first; `docs/audits/2026-09-17/REPORT.md` is the earlier diagnosis |
| Experiment design | `docs/PAPER-EXPERIMENT.md`; strategy versions in `docs/STRATEGY-SPEC.md`; supporting investigations in `docs/research/` |

## Project constraints

- Keep `risk_engine/` pure (no network, database, or clock I/O); money uses
  `Decimal`, and float input is rejected at the boundary.
- Paper accounts only. All broker calls use `scripts/alpaca.sh`; mutations
  validate the exact payload. `ALPACA_RISK_OK=1` is caller intent, not approval.
  Protective-stop replacement uses `scripts/replace_stop.py`.
- Keep credentials private. Use `env.template` for configuration names; avoid
  dumping `.env` or credential values into output or documentation.
- `DATABASE_URL` enables the optional ledger; a configured but failing ledger
  fails closed. Historical logs describing mandatory configuration may be stale.
- `docs/dashboard/data.js` is generated: change its inputs/builder and regenerate.
  Preserve historical log evidence and existing parser-sensitive formats.
- When changing a shared routine behavior, update both cloud and local command
  instructions. Scheduler configuration is external; repository edits alone
  do not verify deployment. The hard-reset sync in `routines/README.md` is for
  disposable cloud checkouts, not this development workspace.

## Verification

Use `.venv/bin/python` when available; setup is in `README.md`.

```bash
env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/build_dashboard_data.py --check
git diff --check
```

Run checks appropriate to the change. Ledger changes also need integration
tests against an isolated Postgres database (see README and CI); their fixtures
truncate ledger tables. Offline doctor success does not verify broker state.
For dashboard input/builder changes, regenerate before the golden-file check.

## Trading tasks only

Read the requested routine/command in full, `memory/TRADING-STRATEGY.md`,
`memory/PROJECT-CONTEXT.md`, recent relevant entries in `memory/TRADE-LOG.md`
and `memory/RESEARCH-LOG.md`; read `memory/WEEKLY-REVIEW.md` for weekly reviews.
Use fresh broker state for account decisions; markdown history is not a current
account snapshot. Research and `/conviction` produce advice; `/trade` executes.
Use the API wrappers and preserve the memory files' existing entry formats.

## Leave a handoff

After material engineering work, update `docs/PROJECT-STATUS.md` with the date,
code baseline, completed changes, checks actually run, remaining work, and any
deployment uncertainty. Replace stale status instead of appending a session
transcript. Keep durable design decisions in `docs/adr/`, architecture in
`ARCHITECTURE.md`, and trading observations in `memory/`. Routine log-only
updates do not require an engineering handoff rewrite.
