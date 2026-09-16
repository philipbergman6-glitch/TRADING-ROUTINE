# Cloud Routine Prompts

Each cloud routine carries a THIN prompt (updated 2026-09-17): sync to
origin/main, then read `routines/<name>.md` and execute it exactly. The files
here are the single source of truth — edit them, merge, done. Do not paste
full file contents into the cloud prompt; that copy goes stale (the June
copies ran without validate_order / OTO / the rule-12 backstop until Sep 17).

Thin prompt template:

    You are the <name> routine of the TRADING-ROUTINE paper trading bot.
    Stocks only — NEVER options. Ultra-concise.
    STEP A — Sync: git fetch origin main && git reset --hard FETCH_HEAD
    (on failure: email "SYNC FAILED <date>", stop).
    STEP B — Read routines/<name>.md IN FULL, then execute it exactly.

## Cron schedules (America/Chicago)

| Routine        | Cron           | File                    |
|----------------|----------------|-------------------------|
| Pre-market     | `30 6 * * 1-5` | `pre-market.md`         |
| Market-open    | `30 8 * * 1-5` | `market-open.md`        |
| Midday         | `0 12 * * 1-5` | `midday.md`             |
| Daily summary  | `0 15 * * 1-5` | `daily-summary.md`      |
| Weekly review  | `0 16 * * 5`   | `weekly-review.md`      |

## One-time prerequisites per routine

1. Install Claude GitHub App on this repo with `contents: write` so the routine can `git push origin main` directly. If `main` is protected, either disable protection or whitelist the App actor — the routine does not open PRs.
2. Set env vars on the routine (NOT in a committed .env file):
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_ENDPOINT`,
   `ALPACA_DATA_ENDPOINT`, `PERPLEXITY_API_KEY`, `PERPLEXITY_MODEL`,
   `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM`.
   Optional: `DATABASE_URL` (hosted Postgres) enables the audit ledger; the
   routine must then also `pip install -e ".[ledger]"`. Unset = ledger disabled.
