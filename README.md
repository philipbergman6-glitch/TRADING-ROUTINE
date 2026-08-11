# Trading Bot

An autonomous AI trader running a **paper (fake-money) ~$100,000 Alpaca
account**, with a deterministic risk engine that evaluates every mechanisable
strategy rule in tested code rather than in prose.

**📊 Dashboard:** https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/
**🏛 Design rationale:** [ARCHITECTURE.md](ARCHITECTURE.md)

Live since 2026-04-27. Stocks only, no options, no real money.

## The Big Picture

The trader is Claude Code itself — there is no separate trading program. Five
times per trading day a scheduled routine wakes Claude in the cloud. Each time it
reads its memory (markdown in `memory/`, committed to the repo, so each session
resumes exactly where the last left off), does its job for that time of day, and
writes back what it learned.

The interesting engineering problem is not stock-picking. It is **stopping a
non-deterministic component from doing something irreversible.** That is what
`risk_engine/` is for.

## What is actually enforced in code

These rules are mechanised in `risk_engine/`, each with a test proving both that
it passes valid orders and that it rejects invalid ones. The model cannot talk
its way past them:

| Rule | Enforced |
|---|---|
| Paper account only | ✅ code — refuses every order on a non-paper account |
| Stocks only, never options | ✅ code — rejects option contract symbols |
| Max 6 open positions | ✅ code |
| Max 20% of equity per position | ✅ code — measured on the *resulting* position |
| Max 3 new trades per week | ✅ code — counted from the broker, not the log |
| Never spend more cash than available | ✅ code |
| Deployment ceiling (85%) | ✅ code |
| Every buy carries a stop | ✅ code — an unprotected buy is never approved |
| A stop is never within 3% of price | ✅ code — on a proposed buy |
| A stop never moves down | 🚧 written and tested, **not called** |
| A stop is never within 3% of price, on a stop *change* | 🚧 written and tested, **not called** |
| Trail ladder: 10% → 7% at +15% → 5% at +20% | 🚧 written and tested, **not called** |
| Follow sector momentum | ⚠️ prose — a judgment, left to the operator |
| Specific catalyst required | ⚠️ prose — presence is checkable, quality is not |
| Cut losers at −7% | ⚠️ prose — an exit trigger, not a property of a proposed order |
| Exit a sector after 2 failed trades | ⚠️ prose — *blocked on data*: TRADE-LOG records no sector field |

The ⚠️ rows are not oversights. They are listed in `risk_engine.UNMECHANISED`
with the reason each was left to human judgment.

The 🚧 rows are a different thing, and the more honest label for them is
*half-done*. `validate_stop_change` and `required_trail_percent`
(`risk_engine/engine.py:267`, `:308`) are real, deterministic and covered by
tests — but they have **zero non-test callers**, and `validate_stop_change`
never consults the trail ladder at all. Every stop *modification* this bot makes
is therefore still governed by routine prose (`routines/midday.md:39-49`), not by
the engine. Wiring them up is [issue #32](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/32);
it is harder than it looks, because tightening a trailing stop is a
cancel-and-replace, so there is no reliable "current stop price" for the caller
to compare against.

## What this does not do yet

Stated plainly, because the gap between what a system does and what its README
claims is where trust dies:

- **The five scheduled routines are not yet guarded by the risk engine.** Only
  the manual `/trade` path calls it. The routines still follow prose
  instructions. This was deliberate sequencing — the risky integration is staged
  behind the manual path before touching an unattended flow that places orders
  every morning — but until that lands, the ✅ table above describes `/trade`,
  not the 8:30 AM routine.
- **There is a partial-failure gap between buying and stopping.** The market buy
  and the protective stop are two separate API calls. A failure between them
  leaves an unprotected position. The engine refuses to approve an unprotected
  buy, but closing the *execution* gap needs idempotency keys and an
  orchestration layer that does not exist yet.
- **The sell path would be refused by the broker.** Rule 4 puts a full-size
  trailing stop on every position, and an open sell order reserves its full
  quantity — so `qty_available` is structurally `0` on every position this bot
  holds (verified live on all four: XLB, XLI, XLK, XLP). A sell into that is
  `HTTP 403 / code 40310000`, and `DELETE /v2/positions/{symbol}` returns the
  same 403 without cancelling the blocking order. The engine checks `qty`, not
  `qty_available`, so it would *approve* a sell the broker then rejects. Cancel-
  then-sell is the only viable sequence; deciding whether the engine validates
  the POST or the whole sequence is
  [issue #41](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/41).
  Findings: [`docs/research/0002`](docs/research/0002-alpaca-share-reservation-and-qty-available.md).
- **Cutting a loser can leave it held *and* unprotected.** `routines/midday.md`
  closes then cancels; given the reservation above, the close 403s and the cancel
  succeeds — so the loser stays, minus its stop. Live and armed daily until
  [#38](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/38) lands.
- **No reconciliation loop.** Nothing compares local state against broker state,
  or alerts when a position has no stop — and the query that would power one
  (`ledger/store.py:218`) currently counts a broker-*rejected* stop as
  protection ([#37](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/37)).
- **Markdown is still the operational system of record.** Postgres is an
  additive ledger, not the source of truth.
- **Single user, paper only.** No multi-tenancy, no auth, no credential
  encryption, no live trading. Not built, and deliberately so — there is one
  user and one paper account.
- **Dashboard narrative is partly curated and frozen** (see the "as of" stamps).
  Portfolio figures regenerate from the logs; the written analysis does not.

## How the pieces fit

- **`risk_engine/`** — the validation layer. Deterministic Python, no I/O. Says no.
- **`memory/`** — the working memory. Strategy, trade log, research notes. What Claude reads.
- **`ledger/`** — the record. Postgres: proposed → decided → submitted → broker response.
- **`scripts/alpaca.sh`** — a *private broker adapter*, sitting behind the risk engine, not in front of it.
- **`routines/`** — the five cloud prompts that run on timers. This is production.
- **`CLAUDE.md`** — standing orders, auto-loaded every session.
- **`.claude/commands/`** — manual controls (`/portfolio`, `/trade`, `/conviction`).

## Run it yourself

```bash
cp env.template .env          # fill in your API keys
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest              # risk engine tests: pure, no services needed
```

Validate a hypothetical order against live account state — read-only, submits
nothing:

```bash
python3 scripts/validate_order.py --symbol AAPL --qty 100 --side buy \
    --price 187.85 --trail-percent 10 --json
```

Exit `0` approved, `3` refused (with every broken rule listed), `4` broker state
unavailable. A real refusal looks like:

```
REFUSED   buy 100 AAPL
  - max_deployment_pct: would deploy 89.60% of equity, max is 85%
  max shares permitted right now: 47
```

For the ledger tests, bring up Postgres first:

```bash
docker run -d --name trading-pg -e POSTGRES_USER=trading \
    -e POSTGRES_PASSWORD=trading -e POSTGRES_DB=trading \
    -p 5433:5432 postgres:16-alpine

DATABASE_URL=postgresql://trading:trading@localhost:5433/trading .venv/bin/pytest
```

`docker-compose.yml` describes the same service if you have the Compose plugin
installed (`docker compose up -d`); the `docker run` line above is the verified
path and needs only the base Docker CLI.

Ledger tests skip cleanly when `DATABASE_URL` is unset, so a Docker problem
never costs you the safety tests — the risk engine suite has no service
dependencies at all.

In Claude Code, `/portfolio` gives a read-only snapshot — nothing is bought or sold.

## Cloud setup

The production bot runs as five Claude cloud routines on cron timers:

1. Install the Claude GitHub App on this repo.
2. Create 5 routines and paste the prompts from `routines/*.md` verbatim.
3. Enable unrestricted branch pushes (routines commit memory to main).
4. Set API keys as environment variables on each routine — **not** in a `.env` file.

## Daily schedule (America/Chicago)

| Time | Routine | What it does |
|---|---|---|
| 6:00 AM Mon–Fri | Pre-market | Research catalysts, draft 2–3 trade ideas. Default is HOLD. |
| 8:30 AM Mon–Fri | Market-open | Validate ideas against the rules, place buys, set 10% trailing stops. |
| 12:00 PM Mon–Fri | Midday | Cut losers at −7%, tighten stops on winners, re-check theses. |
| 3:00 PM Mon–Fri | Daily summary | P&L math, end-of-day snapshot to the trade log, one email. |
| 4:00 PM Friday | Weekly review | Stats, letter grade, one email, optional strategy tweak. |
