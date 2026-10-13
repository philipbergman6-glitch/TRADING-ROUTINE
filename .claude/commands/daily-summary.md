---
description: End-of-day summary — P&L math, EOD snapshot to trade log, one email
---

## Run record (first step, ADR 0012)

Local runs write through the dedicated clone (`--local`, ADR 0004 section 3).
State goes through the same clone, never through this development checkout's
origin: every validate_order, submit_entry, close_position, replace_stop,
protection_monitor and coordinator call below carries the
TRADING_STATE_STORE=local prefix. Each Bash call is a fresh shell, so the
prefix goes on every call; an `export` does not carry over.

python3 scripts/run_record.py --local start --routine daily-summary --trigger local \
    --command-file .claude/commands/daily-summary.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED daily-summary $DATE: <printed reason>" and continue without a
record: this routine makes no broker mutation, and its log is still due.
Skip the finish step in that case.
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

You are running the daily summary workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory for continuity:
- tail of memory/TRADE-LOG.md (find most recent EOD snapshot -> yesterday's
  equity, needed for Day P&L)
- TRADE-LOG entries dated today are the NARRATIVE only; the trade list and
  counts come from broker fills in STEP 2.

STEP 2 — Pull final state of the day:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders
python3 scripts/blotter.py --check    # exit 4 = fills and positions disagree → STOP, email "BLOTTER MISMATCH $DATE"
python3 scripts/blotter.py --json     # round_trips[] + open_lots[]; fills are the record
python3 scripts/reconcile_equity.py   # exit 4 = cash, holdings or daily equity do not reconcile → STOP, email "RECONCILIATION MISMATCH $DATE" with its output

STEP 2b — Unfinished intents (ADR 0010 section 5). This routine never takes
the lease and never recovers; it reports what the writers left behind:
STATUS_JSON=$(TRADING_STATE_STORE=local python3 scripts/coordinator.py status); STATUS_EXIT=$?
- Exit 0 → add one finish --incident per item, filled from the JSON:
  each "non_terminal" entry → "unfinished intent <intent> (<action> <symbol>): <state>";
  each "takeovers" entry whose "at" is within the last 24 hours (72 on a Monday) →
  "lease takeover <lease> by <writer> superseding <supersedes> at <at>";
  a "holder" with "stale": true → "stale lease <lease> held by <writer> since <expires_at>".
  A takeover may land in two runs' records; that is expected. Never act on
  any of them here: the next writer or monitor run recovers them.
- Exit 10 → --incident "state store unavailable: <reason>"; continue (this
  routine changes nothing).
- Any other exit → --incident "coordinator status exit <N>"; continue.

STEP 3 — Compute metrics:
- Day P&L ($ and %) = today_equity - yesterday_equity
- Phase cumulative P&L ($ and %) = today_equity - starting_equity
- Trades today: from blotter --json, every open_lot or round_trip with
  `entered` today (buys) plus every round_trip with `exited` today (sells,
  with realized pnl/pnl_pct). "none" only if the blotter shows none.
- Trades this week (3/week cap): count of lots/trips with `entered` Mon..today.
  If TRADE-LOG disagrees with the blotter, the blotter wins — say so in Notes.

STEP 4 — Append EOD snapshot to memory/TRADE-LOG.md:

### MMM DD — EOD Snapshot (Day N, Weekday)
**Portfolio:** $X | **Cash:** $X (X%) | **Day P&L:** ±$X (±X%) | **Phase P&L:** ±$X (±X%)

| Ticker | Shares | Entry | Close | Day Chg | Unrealized P&L | Stop |

**Notes:** one-paragraph plain-english summary.

STEP 5 — Send ONE email (always, even on no-trade days). <= 15 lines:
bash scripts/email.sh "EOD MMM DD
Portfolio: \$X (±X% day, ±X% phase)
Cash: \$X
Trades today: <list or none>
Open positions:
  SYM ±X.X% (stop \$X.XX)
Tomorrow: <one-line plan>"

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
email "RUN RECORD FINISH FAILED daily-summary $DATE: <printed reason>".
