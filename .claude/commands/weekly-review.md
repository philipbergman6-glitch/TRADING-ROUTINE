---
description: Friday weekly review — stats, grade, one email, optional strategy update
---

## Run record (first step, ADR 0012)

Local runs write through the dedicated clone (`--local`, ADR 0004 section 3).
State goes through the same clone, never through this development checkout's
origin: every validate_order, submit_entry, close_position, replace_stop,
protection_monitor and coordinator call below carries the
TRADING_STATE_STORE=local prefix. Each Bash call is a fresh shell, so the
prefix goes on every call; an `export` does not carry over.

python3 scripts/run_record.py --local start --routine weekly-review --trigger local \
    --command-file .claude/commands/weekly-review.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED weekly-review $DATE: <printed reason>" and continue without a
record: this routine makes no broker mutation, and its log is still due.
Skip the finish step in that case.
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

You are running the Friday weekly review workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory for full week context:
- memory/WEEKLY-REVIEW.md (match existing template exactly)
- ALL this week's entries in memory/TRADE-LOG.md
- ALL this week's entries in memory/RESEARCH-LOG.md
- memory/TRADING-STRATEGY.md

STEP 2 — Pull week-end state:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions

STEP 2b — Unfinished intents (ADR 0010 section 5). This routine never takes
the lease and never recovers; it reports what the writers left behind:
STATUS_JSON=$(TRADING_STATE_STORE=local python3 scripts/coordinator.py status); STATUS_EXIT=$?
- Exit 0 → add one finish --incident per item, filled from the JSON:
  each "non_terminal" entry → "unfinished intent <intent> (<action> <symbol>): <state>";
  each "takeovers" entry whose "at" is within the last 7 days →
  "lease takeover <lease> by <writer> superseding <supersedes> at <at>";
  a "holder" with "stale": true → "stale lease <lease> held by <writer> since <expires_at>".
  A takeover may land in two runs' records; that is expected. Never act on
  any of them here: the next writer or monitor run recovers them.
- Exit 10 → --incident "state store unavailable: <reason>"; continue (this
  routine changes nothing).
- Any other exit → --incident "coordinator status exit <N>"; continue.

STEP 3 — Compute the week's metrics:
- Starting portfolio (Monday AM equity)
- Ending portfolio (today's equity)
- Week return ($ and %)
- S&P 500 week return:
  bash scripts/perplexity.sh "S&P 500 weekly performance week ending $DATE"
  MANDATORY FORMAT — the row must quote BOTH index levels, and the starting
  level MUST equal the prior week's logged closing level (read it out of
  WEEKLY-REVIEW.md; do NOT re-fetch it). Example:
    | S&P 500 week | +1.71% (7,357.49 Jun 26 → 7,483.24 Jul 2) |
  Re-fetching the start breaks the benchmark chain and silently misstates
  "beat the S&P" — see the Benchmark Data Errata section. The dashboard build
  hard-fails on any new break.
- Closed-trade stats come from BROKER FILLS, never from TRADE-LOG prose
  (fills are the record; markdown is the narrative — docs/STRATEGY-SPEC.md):
    python3 scripts/blotter.py --check    # exit 4 = fills and positions disagree → STOP, email "BLOTTER MISMATCH $DATE"
    python3 scripts/blotter.py --json     # round_trips[] (exited, pnl, pnl_pct) + open_lots[]
    python3 scripts/blotter.py --markdown # paste as the Closed trades table (this week's rows)
  "This week" = round_trips whose `exited` date is Mon..today. Do not pass
  --after: a trip entered last week and exited this week needs its entry fill.
  From those rows compute, and show the arithmetic:
  - Trades taken (W/L/open): W = pnl > 0, L = pnl <= 0, open = open_lots
  - Win rate (closed trades only)
  - Best trade, worst trade (by pnl_pct)
  - Profit factor (sum winners / |sum losers|; "n/a" if no losers)
  If a TRADE-LOG entry and the blotter disagree, the blotter wins — note the
  discrepancy under "What didn't work" so it gets fixed, never silently pick one.

STEP 4 — Append full review section to memory/WEEKLY-REVIEW.md:
- Week stats table
- Closed trades table
- Open positions at week end
- What worked (3-5 bullets)
- What didn't work (3-5 bullets)
- Key lessons learned
- Adjustments for next week
- Overall letter grade (A-F)

STEP 5 — If a rule needs to change (proven out for 2+ weeks, or failed
badly), PROPOSE it in the review under a "Proposed rule change" heading:
the rule text, the evidence, and the version it would start. Do NOT edit
memory/TRADING-STRATEGY.md — it is hash-pinned (docs/rulebook-pins.json)
and any edit without an owner-approved version bump halts every routine
at scripts/strategy_version.py the next session. The owner applies the
change and bumps the version.

Log-format gate — run BEFORE committing. The dated entry header is
machine-read (dashboard, brain index, rule-12 gate): the kind after the dash
must be one the parser already knows for this routine (a "## Week ending YYYY-MM-DD" section with its "### Overall Grade:" line),
never a new word, and the EOD Portfolio line keeps plain values.
python3 scripts/build_brain_index.py --parse   # exit 1 = an entry you just wrote does not parse → fix it, re-run, only then STEP 6

STEP 6 — Send ONE email. <= 15 lines:
bash scripts/email.sh "Week ending MMM DD
Portfolio: \$X (±X% week, ±X% phase)
vs S&P 500: ±X%
Trades: N (W:X / L:Y / open:Z)
Best: SYM +X%  Worst: SYM -X%
One-line takeaway: <...>
Grade: <letter>"

LAST STEP — RUN RECORD FINISH (ADR 0012):
python3 scripts/run_record.py --local finish \
    [--action "<broker mutation made>"]... [--refusal "<action a rule refused>"]... \
    [--incident "<what went wrong>"]... [--intent <intent id>]...
One --action per broker mutation this run made (buy, sell, stop replace or
renew), one --refusal per action a validator or rule refused, one
--incident per failure (STOP, push not verified, alert not delivered,
coverage short), one --intent per intent id a helper printed. No flags =
no-trade; the outcome is derived. Never invent entries. Include every
STEP 2b incident. On a non-zero exit
email "RUN RECORD FINISH FAILED weekly-review $DATE: <printed reason>".
