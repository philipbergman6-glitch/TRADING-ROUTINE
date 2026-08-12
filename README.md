# Trading Routine

**An autonomous trading platform where a language model is the trader — and a
deterministic engine is the thing that can say no.**

Live since 2026-04-27 on a paper (fake-money) ~$100,000 Alpaca account.
75 trading days. **Zero rule breaches. No stop ever lowered.** Stocks only, no
options, no real money.

**📊 Live dashboard:** https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/
**🏛 Design rationale:** [ARCHITECTURE.md](ARCHITECTURE.md) · **📖 Vocabulary:** [CONTEXT.md](CONTEXT.md)

---

## The idea

There is no trading program. The trader *is* Claude Code.

Five times per trading day a scheduled routine wakes it in the cloud. Each time
it reads its own memory — plain markdown, committed to this repo — does the job
for that hour, writes back what it learned, and pushes. The next session picks
up exactly where the last one left off. Nobody is watching.

That works only if the model can never do something irreversible. So the
interesting engineering problem here is not stock-picking. It is:

> **How do you give a non-deterministic component real money-shaped power, and
> still be able to prove afterwards why every order existed and who allowed it?**

Everything in this repo is an answer to that question.

---

## The three-way split

The single most important structural decision. Blur any two of these and you
lose the audit trail.

| | Role | Where |
|---|---|---|
| **Risk engine** | The validation layer. Deterministic. Says no. | `risk_engine/` |
| **Working memory** | What the model reads to know what it is doing. | `memory/*.md` |
| **Ledger** | Immutable record: proposed → decided → submitted → broker response. | `ledger/` (Postgres) |

The risk engine does not remember. The memory does not decide. The ledger does
neither — it only records.

```
Model proposes a trade
        ↓
scripts/validate_order.py        ← the enforceable boundary
        ↓
risk_engine.validate_order()     ← deterministic; returns EVERY broken rule
        ↓   (refused → exit 3, nothing is sent)
        ↓   (approved)
scripts/alpaca.sh                ← private broker adapter, behind the boundary
        ↓
Alpaca paper API
        ↓
ledger (Postgres)                ← proposed, decided, sent, returned
```

The model may propose. It may not bypass the engine.

---

## The rules, as code

Each rule below is mechanised in `risk_engine/`, with a test proving both that
it passes a valid order and that it rejects an invalid one. The model cannot
argue with any of them.

| Rule | How it's enforced |
|---|---|
| Paper account only | refuses every order on a non-paper account |
| Stocks only, never options | rejects option contract symbols |
| Max 6 open positions | counted from the broker |
| Max 20% of equity per position | measured on the *resulting* position, not the current one |
| Max 3 new trades per week | counted from the broker, not from the log |
| Never spend more cash than available | |
| Deployment ceiling, 85% | |
| Every buy carries a stop | an unprotected buy is never approved |
| A stop is never within 3% of price | |

A refusal returns **every** violated rule, not the first one — so a refusal is
auditable, not a bare `False`:

```
REFUSED   buy 100 AAPL
  - max_deployment_pct: would deploy 89.60% of equity, max is 85%
  max shares permitted right now: 47
```

Three design choices that matter more than the rule list:

- **The engine is a pure module.** No network, no database, no clock. Which is
  why 51 test functions on it cost almost nothing to write and run in **0.03
  seconds**. The dangerous, untestable part — talking to a broker — is pushed to
  the edges where it belongs.
- **Money is `Decimal`, and floats are *rejected* at the boundary, not
  converted.** Accepting `0.1` as a float means storing
  `0.10000000000000000555...`, and a position-size check that is off by a cent
  is a bug you find in production instead of in review.
- **Paper-only is enforced twice, deliberately.** `alpaca.sh` hard-fails on any
  non-paper endpoint, *and* the engine re-checks the account mode itself rather
  than trusting that the upstream guard held. A safety property enforced in
  exactly one place is one refactor away from being enforced in none.

Rules that are genuinely judgment calls — sector momentum, catalyst quality,
patience over activity — are not faked into code. They are listed in
`risk_engine.UNMECHANISED` with the reason each was left to a human. Knowing
which rules *shouldn't* be automated is part of the design.

---

## It checks itself

Three things the system did on its own that are the real point of the project.

### It wrote a rule into its own strategy, then obeyed it on deadline

For six weeks the bot sat below its 75–85% deployment mandate, deferring
redeployment every session under "patience > activity." On **Aug 07 the weekly
review amended `memory/TRADING-STRATEGY.md` itself** — adding Rule 12, a
deployment backstop — with the reason written in plain text:

> *"patience was masking non-compliance."*

On Aug 10 the market-open routine cited that new rule and bought XLK, lifting
deployment 60.4% → 80.2%. Diagnose → legislate → execute, unattended.

### It audited its own benchmark, and corrected it against its own interest

An Aug 11 audit found the logged S&P series had **re-fetched its starting level
three times** instead of chaining from the prior week's close — so "beat the
S&P" was being scored against a discontinuous series. The chart now plots the
re-chained series and the weekly reviews carry an errata section.

Note the direction: the corrected benchmark is **worse** for the bot (+5.12%
chained vs +3.26% as logged). It is used anyway, and the build now hard-fails on
any new break in the chain.

### It refuses to let curated text pass as live

The dashboard carries **two independent dates**. `LOG_ASOF` moves nightly with
the trade log. `ANALYSIS_ASOF` only moves when a human rewrites the editorial
prose. Both are shown, always, so written analysis can never be mistaken for a
fresh reading.

---

## The five routines

Production is `routines/*.md` — five prompts on cron timers, America/Chicago.

| Time | Routine | What it does |
|---|---|---|
| 6:00 AM Mon–Fri | **Pre-market** | Research catalysts, draft 2–3 trade ideas. Default is HOLD. |
| 8:30 AM Mon–Fri | **Market-open** | Validate ideas against the rules, place buys, set 10% trailing stops. |
| 12:00 PM Mon–Fri | **Midday** | Cut losers at −7%, tighten stops on winners, re-check theses. |
| 3:00 PM Mon–Fri | **Daily summary** | P&L math, end-of-day snapshot to the trade log, one email. |
| 4:00 PM Friday | **Weekly review** | Stats, letter grade, one email, optional strategy amendment. |

Plus two ad-hoc decision skills in `.claude/commands/`: `/conviction` (deep,
citing research pass that adversarially tries to refute its own bear case before
a candidate survives) and `/trade` (the mechanical rule-check and execution
path). `/portfolio` is read-only.

The distinction between a **routine** (scheduled, habitual) and a **decision
skill** (ad-hoc, research-driven, advice-only) is enforced in the vocabulary
itself — see [CONTEXT.md](CONTEXT.md), which fixes the shared language across
the routines, the rulebook and the logs so two documents can't quietly mean
different things by the same word.

---

## Memory as a first-class component

`memory/` is not documentation. It is the running state of an agent that has no
other continuity:

| File | What it holds |
|---|---|
| `TRADING-STRATEGY.md` | The rulebook. The bot reads it every session — and has amended it. |
| `TRADE-LOG.md` | Every entry, exit, stop and EOD snapshot. The blotter. |
| `RESEARCH-LOG.md` | Today's research, written before any trade is allowed. |
| `PROJECT-CONTEXT.md` | Mission, constraints, standing prohibitions. |
| `WEEKLY-REVIEW.md` | Friday self-assessment, letter grade, amendment proposals. |

Because it's markdown in git, **every state the agent has ever been in is
recoverable** — and that has already paid off: six weeks of session history was
reconstructed from 136 unmerged branches and landed back on `main`, with the
reconstructed entries explicitly labelled as reconstruction rather than
observation.

---

## Track record

15 weeks, from `docs/dashboard/data.js` — regenerated from the logs, not written
by hand:

| | |
|---|---|
| Return | **+6.70%** |
| Chained S&P 500 | +7.26% |
| Peak equity | $115,135 (Jun 02) |
| Rule breaches | **0** |
| Stops ever lowered | **0** |
| Worst single loss | −9.4%, and shrinking every month |

The story splits cleanly at the June reset: **+8.72% vs +2.03%** through Jun 05
on a single-name tech book, then **−1.86% vs +5.13%** across the nine weeks
since on sector ETFs. The dashboard says so on its own front page, in red.

Risk control is the part that is genuinely solved. Every open position carries a
live GTC protective stop, reconciled by hand against the broker share-for-share
on 2026-08-11.

---

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
unavailable.

The ledger's integration tests want a real Postgres, which is all
`docker-compose.yml` is for:

```bash
docker compose up -d
DATABASE_URL=postgresql://trading:trading@localhost:5433/trading .venv/bin/pytest
```

They skip cleanly when `DATABASE_URL` is unset, so **a Docker problem never
costs you the safety tests** — the risk-engine suite has no service dependencies
at all.

---

## Deploying it

The production bot is five Claude cloud routines on cron timers — no server, no
container, no orchestrator:

1. Install the Claude GitHub App on this repo with `contents: write`.
2. Create 5 routines and paste the prompts from `routines/*.md` verbatim.
3. Allow the App to push to `main` (routines commit memory directly).
4. Set API keys as environment variables on each routine — **not** in a `.env` file.

Cron schedules and the full prerequisite list are in
[`routines/README.md`](routines/README.md).

---

## Engineering notes

Design decisions are written down where they were made, not reconstructed later:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the three-way split, why the engine is
  pure, what is enforced vs. left to judgment, and every deliberate deferral.
- [`docs/adr/`](docs/adr) — architecture decisions, including why a buy's
  protection uses an OTO fixed leg converted to a trailing stop.
- [`docs/research/`](docs/research) — primary-source broker research: Alpaca's
  atomic entry-plus-stop behaviour, and how share reservation interacts with
  `qty_available`. Read before designing around them, not after being surprised.
- [`CONTEXT.md`](CONTEXT.md) — the shared vocabulary, with the terms each one
  replaces.

The roadmap and the honest state of every in-flight piece live in
`ARCHITECTURE.md` under **Deliberate deferrals**, and in the issue tracker.
