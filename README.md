# Trading Bot

**📊 Live dashboard:** https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/

Autonomous swing-trading agent for a ~$100,000 Alpaca paper account. Stocks only.
Claude Code is the bot — five cloud routines fire on weekday crons, read
memory from git, call wrappers for Alpaca/Perplexity/Resend-email, and
commit new memory back to main.

## Layout

- `CLAUDE.md` — agent rulebook, auto-loaded every session
- `scripts/` — bash wrappers for Alpaca, Perplexity, Resend email
- `.claude/commands/` — local slash commands for ad-hoc use
- `routines/` — cloud routine prompts (the production path)
- `memory/` — persistent state, committed to main

## Local quickstart

1. `cp env.template .env` and fill in credentials
2. Open repo in Claude Code
3. Run `/portfolio` for a read-only snapshot

## Cloud setup

See the setup guide — install Claude GitHub App, create 5 routines, paste
prompts from `routines/*.md` verbatim, enable "Allow unrestricted branch
pushes", set env vars on each routine (NOT in a .env file).

## Cron schedules (America/Chicago)

- Pre-market: `0 6 * * 1-5`
- Market-open: `30 8 * * 1-5`
- Midday: `0 12 * * 1-5`
- Daily summary: `0 15 * * 1-5`
- Weekly review: `0 16 * * 5`
