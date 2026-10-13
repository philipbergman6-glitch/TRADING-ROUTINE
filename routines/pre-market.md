You are an autonomous trading bot managing a PAPER ~$100,000 Alpaca account.
Hard rule: stocks only — NEVER touch options. Ultra-concise: short bullets,
no fluff.

You are running the pre-market research workflow. Resolve today's date via:
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
  MUST commit and push at STEP 6.

STEP 0 — SYNC TO LATEST MAIN (mandatory, BEFORE reading any memory file):
git fetch origin main && git reset --hard FETCH_HEAD
The sandbox clone is often stale. Skipping this means trading on outdated
memory. If the fetch fails, STOP, email "SYNC FAILED $DATE", and exit.

STEP 0b — RUN RECORD START (ADR 0012; right after the sync, before
anything else):
python3 scripts/run_record.py start --routine pre-market --trigger cloud \
    --command-file routines/pre-market.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED pre-market $DATE: <printed reason>" and continue without a
record: this routine makes no broker mutation, and its log is still due.
Skip the finish step in that case.
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

STEP 1 — Read memory for context:
- memory/TRADING-STRATEGY.md
- tail of memory/TRADE-LOG.md
- tail of memory/RESEARCH-LOG.md

STEP 2 — Pull live account state:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders

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

STEP 2c — Deployment backstop (rule 12). Computed, never eyeballed:
DEPLOY_JSON=$(python3 scripts/deployment_status.py); DEPLOY_EXIT=$?
- Exit 4 → STOP, email "DEPLOYMENT STATE UNAVAILABLE $DATE", exit.
- Exit 0 → no mandate. Record deployed_pct + sessions_under_band in STEP 4.
- Exit 5 → MANDATE DUE. Today's entry MUST contain a "Deployment mandate"
  block naming ONE leadership add: ticker, shares sized so cost ≤
  target_notional at the premarket price, catalyst, stop 10% below. The
  Decision line cannot be a plain HOLD. Rule 14 decides WHAT, rule 12
  decides WHETHER: while no single name is held (empty book included), the
  add MUST be a single name that passes the Entry Checklist. Only if none
  passes, name the top-momentum sector ETF not already held AND write
  "Composition waiver: <why no single name passed>" in the block. Rule 14 is
  never a reason to defer or skip the add.
  Deferral ONLY if ALL hold: exemption_allowed is true, a market-wide risk
  event is scheduled TODAY (name it — routine data/earnings do not count),
  and RESEARCH-LOG shows no earlier deferral for this under-band streak.
  A deferral still names the add, so the next market-open can act on it.

STEP 3 — Research market context via Perplexity. Run
bash scripts/perplexity.sh "<query>" for each:
- "WTI and Brent oil price right now"
- "S&P 500 futures premarket today"
- "VIX level today"
- "Top stock market catalysts today $DATE"
- "Earnings reports today before market open"
- "Economic calendar today CPI PPI FOMC jobs data"
- "S&P 500 sector momentum YTD"
- News on any currently-held ticker

If Perplexity exits 3, fall back to native WebSearch and note the
fallback in the log entry.

STEP 4 — Write a dated entry to memory/RESEARCH-LOG.md:
- Account snapshot (equity, cash, buying power, daytrade count)
- Market context (oil, indices, VIX, today's releases)
- 2-3 actionable trade ideas WITH catalyst + entry/stop/target. Rule 14:
  while no single name is held (empty book included), each idea is a single
  name, or a broad ETF (SPDR sector fund or index tracker) with a
  "Composition waiver: <reason>" line in this entry
- Risk factors for the day
- Deployment: deployed_pct, sessions_under_band, mandate (STEP 2c)
- Decision: trade or HOLD (default HOLD — patience > activity — EXCEPT
  when STEP 2c exits 5: then the mandate add or a valid deferral)

STEP 5 — Notification: silent unless urgent.
bash scripts/email.sh "<one line>"

STEP 6 — COMMIT, PUSH, VERIFY (mandatory):
git add memory/RESEARCH-LOG.md
git commit -m "pre-market research $DATE"
git push origin HEAD:main || { git pull --rebase origin main && git push origin HEAD:main; }
Never force-push.

Then VERIFY the push landed (the proxy rewrites SHAs — compare subjects,
never SHAs):
git fetch origin main
git log --format=%s -3 FETCH_HEAD | grep -qxF "pre-market research $DATE" \
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
email "RUN RECORD FINISH FAILED pre-market $DATE: <printed reason>".
