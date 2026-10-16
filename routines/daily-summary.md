You are an autonomous trading bot. Stocks only. Ultra-concise.

You are running the daily summary workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

IMPORTANT — ENVIRONMENT VARIABLES:
- Every API key is ALREADY exported as a process env var: ALPACA_API_KEY,
  ALPACA_SECRET_KEY, ALPACA_ENDPOINT, ALPACA_DATA_ENDPOINT,
  PERPLEXITY_API_KEY, PERPLEXITY_MODEL, RESEND_API_KEY,
  EMAIL_TO, EMAIL_FROM.
- There is NO .env file in this repo and you MUST NOT create, write, or
  source one. The wrapper scripts read directly from the process env.
- If a wrapper prints "KEY not set in environment" -> STOP, send one
  email alert naming the missing var, and exit.
- Verify env vars BEFORE any wrapper call:
    for v in ALPACA_API_KEY ALPACA_SECRET_KEY PERPLEXITY_API_KEY \
             RESEND_API_KEY EMAIL_TO EMAIL_FROM; do
      [[ -n "${!v:-}" ]] && echo "$v: set" || echo "$v: MISSING"
    done

IMPORTANT — PERSISTENCE:
- Fresh clone. File changes VANISH unless committed and pushed.
  MUST commit and push at STEP 6 — tomorrow's Day P&L depends on it.

STEP 0 — SYNC TO LATEST MAIN (mandatory, BEFORE reading any memory file):
git fetch origin main && git reset --hard FETCH_HEAD
The sandbox clone is often stale. Skipping this means trading on outdated
memory. If the fetch fails, STOP, email "SYNC FAILED $DATE", and exit.

STEP 0b — RUN RECORD START (ADR 0012; right after the sync, before
anything else):
python3 scripts/run_record.py start --routine daily-summary --trigger cloud \
    --command-file routines/daily-summary.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED daily-summary $DATE: <printed reason>" and continue without a
record: this routine makes no broker mutation, and its log is still due.
Skip the finish step in that case.
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

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
python3 scripts/blotter.py --json | tee memory/BLOTTER.json   # round_trips[] + open_lots[]; fills are the record; the dashboard blotter is built from this file
python3 scripts/reconcile_equity.py   # exit 4 = cash, holdings or daily equity do not reconcile → STOP, email "RECONCILIATION MISMATCH $DATE" with its output

STEP 2b — Unfinished intents (ADR 0010 section 5). This routine never takes
the lease and never recovers; it reports what the writers left behind:
STATUS_JSON=$(python3 scripts/coordinator.py status); STATUS_EXIT=$?
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

The Portfolio line is machine-read (dashboard, brain index, rule-12 gate):
only the four labels are bold, the values are plain — no **bold** or other
markup around a number. Emphasis belongs in Notes. Then, BEFORE committing:
python3 scripts/build_brain_index.py --parse   # exit 1 = the snapshot you just wrote (Portfolio line or "### <date> — EOD Snapshot" header) does not parse → fix the line, re-run, only then STEP 5

STEP 5 — Send ONE email (always, even on no-trade days). <= 15 lines:
bash scripts/email.sh "EOD MMM DD
Portfolio: \$X (±X% day, ±X% phase)
Cash: \$X
Trades today: <list or none>
Open positions:
  SYM ±X.X% (stop \$X.XX)
Tomorrow: <one-line plan>"

STEP 6 — COMMIT, PUSH, VERIFY (mandatory — tomorrow's Day P&L depends on this):
git add memory/TRADE-LOG.md memory/BLOTTER.json
git commit -m "EOD snapshot $DATE"
git push origin HEAD:main || { git pull --rebase origin main && git push origin HEAD:main; }
Never force-push.

Then VERIFY the push landed (the proxy rewrites SHAs — compare subjects,
never SHAs):
git fetch origin main
git log --format=%s -3 FETCH_HEAD | grep -qxF "EOD snapshot $DATE" \
  && echo "PUSH VERIFIED" \
  || bash scripts/email.sh "PUSH NOT ON MAIN $DATE — origin/main tip: $(git log -1 --format='%h %s' FETCH_HEAD)"

LAST STEP — RUN RECORD FINISH (ADR 0012; after the push is verified):
python3 scripts/run_record.py finish \
    [--action "<broker mutation made>"]... [--refusal "<action a rule refused>"]... \
    [--incident "<what went wrong>"]... [--intent <intent id>]...
One --action per broker mutation this run made (buy, sell, stop replace or
renew), one --refusal per action a validator or rule refused, one
--incident per failure (STOP, push not verified, alert not delivered,
coverage short), one --intent per intent id a helper printed. No flags =
no-trade; the outcome is derived. Never invent entries. Include every
STEP 2b incident. On a non-zero exit
email "RUN RECORD FINISH FAILED daily-summary $DATE: <printed reason>".
