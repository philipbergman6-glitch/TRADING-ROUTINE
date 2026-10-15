# Fund Brain

The knowledge base for this fund: every idea, the order it became, the fill,
the exit, and what was learned, linked so a routine or a person can follow one
trade end to end and see the whole book's state in one place.

Status 2026-10-15: **the raw record exists and is complete; the brain is not
yet built.** Everything below is already committed to this repository and
written by the routines themselves. What is missing is the linkage and the
index that turn a chronological log into something a routine can query.

## The chain, and where each link lives today

| Stage | Written by | Where | Form |
|---|---|---|---|
| Market view and ideas | pre-market, `/conviction` | `memory/RESEARCH-LOG.md` | dated prose, one entry per session |
| Rules the idea must pass | weekly review, ADRs | `memory/TRADING-STRATEGY.md`, `docs/STRATEGY-SPEC.md`, `risk_engine/versions.py` | versioned rulebook, sha256-pinned |
| Validation verdict | `validate_order.py` | run record in `state/events.jsonl` | accept or refusal with reason |
| Intent, lease, attempt | `coordinator.py` | `state/events.jsonl` | append-only JSONL, one line per event |
| Fill | broker | `memory/BLOTTER.json` | FIFO round trips and open lots from fills |
| Stop changes | `replace_stop.py`, protection monitor | `state/events.jsonl`, `memory/TRADE-LOG.md` | intent lines and EOD stop table |
| Exit | stop or `close_position.py` | `memory/BLOTTER.json`, `memory/TRADE-LOG.md` | round trip with P&L; EOD "Trades today" |
| Daily state | daily summary | `memory/TRADE-LOG.md` | EOD snapshot: equity, cash, positions, stops |
| Lessons | weekly review | `memory/WEEKLY-REVIEW.md`, `docs/STRATEGY-ASSESSMENT.md` | grade, lessons, proposed rule changes |
| Results audit | engineering | `docs/research/0006-paper-results-reconciliation.md` | fills reconciled to equity to the cent |
| Decisions about the system | engineering | `docs/adr/` | numbered decision records |

The [dashboard](https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/)
renders the daily state, the blotter and the run records from these files.

## What the brain adds

1. **One thread per trade.** A trade id that ties the research entry, the
   validation verdict, the intent, the fill, every stop change, the exit and
   the review sentence about it. Today those are five files joined by symbol
   and date, by hand.
2. **A state brief instead of log tails.** Routines currently read the last
   N lines of the logs. The brief (map #69) gives each routine the exact
   facts it needs: book, cushions, cooldowns, sector streaks, open intents,
   last decision per symbol, rules in force.
3. **Thesis tracking.** Each open position keeps its entry thesis, the
   conditions that would break it, and the dates it was re-checked, so the
   midday thesis check is against a record, not memory.
4. **Outcome review.** For every exit: what the name did after (research
   0006 section "What exited names did afterwards"), whether the rule that
   fired was right, and which rule change, if any, followed.
5. **Queryable.** Markdown stays the narrative; a generated index (JSON)
   answers "show me everything about PSX" or "every refusal in October".

## How to read the record now

- Latest state: last EOD snapshot in `memory/TRADE-LOG.md`.
- Why a trade happened: the same date in `memory/RESEARCH-LOG.md`, then the
  market-open entry in `memory/TRADE-LOG.md`.
- What the broker actually did: `memory/BLOTTER.json`, and the `run` and
  `intent` lines for that date in `state/events.jsonl`.
- What we learned: the following Friday in `memory/WEEKLY-REVIEW.md`.
- Why the system behaves as it does: `docs/adr/`, then `ARCHITECTURE.md`.

## Build plan

Tracked on the issue tracker under map #69 (state brief) and the v2 paper
experiment (`docs/PAPER-EXPERIMENT.md`). Pieces land here, under
`docs/brain/`, as generated files with their builder scripts and tests, in
the same way `docs/dashboard/data.js` is generated today.
