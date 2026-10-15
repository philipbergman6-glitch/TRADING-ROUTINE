# Fund Brain

The knowledge base for this fund: every idea, the order it became, the fill,
the exit, and what was learned, linked so a routine or a person can follow one
trade end to end and see the whole book's state in one place.

Status 2026-10-15: **the raw record exists and is complete; the first slice
of the brain, the index, is built.** Everything below is already committed to
this repository and written by the routines themselves. The linkage that turns
a chronological log into something a routine can query lands here piece by
piece; the map is tracker issue
[#169](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/169).

## The index (built)

- [`INDEX.md`](INDEX.md): per-symbol table (sector, closed and open
  lifecycles, research and trade-log mentions, last decision date), open
  lots, round trips, every refusal, source counts.
- [`index.json`](index.json): the machine form. `symbols[SYM]` holds
  everything about one symbol (research entry ids, trade-log entry ids, idea
  and decision mentions, last decision text, blotter round trips and open
  lots, run and intent ids, week endings); `dates[YYYY-MM-DD]` joins the same
  record per UTC day; `entries`, `runs`, `intents`, `weeks` and `refusals`
  hold the detail.
- Built by `scripts/build_brain_index.py` from the committed record, no
  network, no LLM. `--check` reproduces both files or fails, and runs in the
  dashboard workflow after every EOD push. `--symbol PSX` and
  `--refusals 2026-10` answer the two reference questions from the shell.
- Join key today is (symbol, UTC date); the trade id is ADR 0014, ticket
  [#172](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/172).
  Run and intent records are included only when started before the latest
  EOD snapshot, the same cutoff the dashboard uses, so the committed index is
  reproducible between EOD pushes.

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

Tracked on the issue tracker under map
[#169 Fund Brain](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/169)
(trade id, thread per trade, thesis record, outcome review, brief reads the
brain), with map #69 (state brief) as the first consumer and the v2 paper
experiment (`docs/PAPER-EXPERIMENT.md`) as the client. Pieces land here,
under `docs/brain/`, as generated files with their builder scripts and tests,
in the same way `docs/dashboard/data.js` is generated today.
