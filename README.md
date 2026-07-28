# Trading Bot

**📊 Live dashboard:** https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/

## The Big Picture

This repo is an AI stock trader. The AI is Claude Code itself — there is no
separate trading program. Five times per trading day, a scheduled "routine"
wakes Claude up in the cloud. Each time, Claude:

1. **Reads its memory** — markdown files in `memory/` that record its
   strategy rules, open positions, and past research. Git is its brain:
   because memory is committed to the repo, each session picks up exactly
   where the last one left off.
2. **Does its job for that time of day** — research before the market opens,
   place trades at the open, check on positions midday, summarize at the
   close, review the week on Fridays.
3. **Writes back what it learned** — updates the memory files and commits
   them, so the next session knows what happened.

It trades a **paper (fake-money) ~$100,000 account** on Alpaca. Stocks only,
no options. The goal: beat the S&P 500.

## How the pieces fit

- **Claude Code** = the trader (the decision-maker)
- **`memory/`** = its long-term memory (strategy, trade log, research notes)
- **`routines/`** = its daily schedule (the prompts that run on timers in the cloud)
- **`scripts/`** = its hands (bash wrappers it uses to talk to the outside world:
  Alpaca for trading, Perplexity for research, Resend for email)
- **`CLAUDE.md`** = its standing orders (rules loaded automatically every session)
- **`.claude/commands/`** = manual controls (slash commands like `/portfolio`
  for when you want to run something yourself instead of waiting for a timer)

## Folder guide

| Path | What it is |
|---|---|
| `CLAUDE.md` | The rulebook. Auto-loaded every session. |
| `memory/` | Persistent state: strategy, trade log, research log, weekly reviews. Committed to main. |
| `routines/` | The five cloud prompts — this is what actually runs in production. |
| `scripts/` | `alpaca.sh` (trading), `perplexity.sh` (research), `email.sh` (email). Always used instead of raw API calls. |
| `.claude/commands/` | Slash commands for ad-hoc local use (`/portfolio`, `/trade`, `/conviction`, plus local versions of the daily routines). |
| `dashboard/` | The live web dashboard, rebuilt automatically from memory logs at end of day. |

## Run it yourself (local)

1. `cp env.template .env` and fill in your API keys.
2. Open this repo in Claude Code.
3. Type `/portfolio` — a safe, read-only snapshot of the account, positions,
   and open orders. Nothing is bought or sold.

## Cloud setup (the automated version)

The production bot runs as five Claude cloud routines on cron timers:

1. Install the Claude GitHub App on this repo.
2. Create 5 routines and paste the prompts from `routines/*.md` verbatim.
3. Enable "Allow unrestricted branch pushes" (routines commit memory to main).
4. Set the API keys as environment variables on each routine — **not** in a
   `.env` file.

## Daily schedule (America/Chicago)

| Time | Routine | What it does |
|---|---|---|
| 6:00 AM Mon–Fri | Pre-market | Research catalysts, draft 2–3 trade ideas. Default is HOLD. |
| 8:30 AM Mon–Fri | Market-open | Validate ideas against the rules, place buys, set 10% trailing stops. |
| 12:00 PM Mon–Fri | Midday | Cut losers at −7%, tighten stops on winners, re-check theses. |
| 3:00 PM Mon–Fri | Daily summary | P&L math, end-of-day snapshot to the trade log, one email. |
| 4:00 PM Friday | Weekly review | Stats, letter grade, one email, optional strategy tweak. |
