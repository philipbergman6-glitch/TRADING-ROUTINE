You are an autonomous trading bot. Stocks only — NEVER options. Ultra-concise.

You are running the market-open execution workflow. Resolve today's date via:
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
- STRATEGY VERSION (hard gate, right after the loop above): the approved
  version is "active" in docs/rulebook-pins.json (ADR 0011); STRATEGY_VERSION
  must be its engine (v1) or the full version named there — UNSET IS REFUSED — and the
  rulebook marker and hash must match the pin. Run:
    python3 scripts/strategy_version.py || { bash scripts/email.sh "STRATEGY_VERSION MISMATCH $DATE: $(python3 scripts/strategy_version.py 2>&1)"; exit 1; }
  Exit 5 = env, marker or rulebook hash disagree, exit 1 = pins unreadable.
  The mutation scripts refuse the same way (version_binding_refused). Either way STOP — never trade under a rule set you did not intend. Quote
  the printed "STRATEGY_VERSION: vN" line in today's TRADE-LOG entry.

IMPORTANT — PERSISTENCE:
- Fresh clone. File changes VANISH unless committed and pushed.
  MUST commit and push at STEP 8 if any trades fired or a backstop add
  was skipped.

## T4 — ledger on the live path (optional; mandatory when configured)

`validate_order.py` writes every verdict (approved **and** refused) to Postgres when `DATABASE_URL` is set.
`--json` includes `ledger_order_id`. Ledger is **optional**: `DATABASE_URL` unset →
stderr `LEDGER DISABLED`, `ledger_order_id` null, verdict still valid — proceed
(record_broker_response no-ops). Exit **6** = ledger configured but failed → STOP. This records; it does **not** bind validate→submit
([#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19) still
open). Markdown remains the operational store
([#28](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/28)).

Capture after every validate (single-quoted `-c` — double quotes NameError on the key):

```
VALIDATE_JSON=$(python3 scripts/validate_order.py ... --json)
# exit 0 or 3 = verdict (ledger row if DATABASE_URL set); exit 6 → STOP
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
```

After every successful mutating order submit, persist the broker response
(existing Ledger API — `submit` / `stop` only; no invented cancel writer).
Derive real HTTP status via `ALPACA_HTTP_STATUS_FILE` (alpaca.sh writes curl
`%{http_code}`; never hardcode 200). Re-assign `LEDGER_ORDER_ID` from **each**
validate `--json` before the matching `record_broker_response`:

```
HTTP_STATUS_FILE=$(mktemp)
RESP=$(ALPACA_HTTP_STATUS_FILE="$HTTP_STATUS_FILE" ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$ORDER_JSON")
HTTP_STATUS=$(cat "$HTTP_STATUS_FILE"); rm -f "$HTTP_STATUS_FILE"
python3 scripts/record_broker_response.py \
    --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
    --response "$RESP"
```

Trail/protective places that are separate broker orders: `--kind stop`
(Ledger `record_stop` / protection). Parent entry OTO: `--kind submit`.

## Coordinator exits (ADR 0010)

submit_entry.py, close_position.py and replace_stop.py each run as one
coordinated action: take the account lease in the state store, recover any
intent an earlier writer left unfinished, act, record the outcome. Every
ENTRY_EXIT / CLOSE_EXIT / REPLACE_EXIT legend below ends with the three codes
the coordinator adds:
- 10 store unavailable — nothing changed. Make no further broker mutation
  this run; email "STATE STORE UNAVAILABLE $DATE: <script> SYM: <reason>" and
  log it. Not an exit 10: replace_stop restoring a stop on a held position
  that has none proceeds without the store and alerts itself (ADR 0004
  section 1).
- 11 lease wait exhausted — another writer (the protection monitor, a local
  /trade, an overlapping run) held the lease through the wait; nothing
  changed. Do not rerun now and make no further broker mutation this run (the
  holder, or the next monitor run, finishes its own work); email "LEASE WAIT
  EXHAUSTED $DATE: <script> SYM, held by <holder>" and log it.
- 12 INCIDENT — the broker ACTED but the outcome could not be recorded. Do NOT
  rerun: the next writer or protection monitor run recovers the outcome from
  broker state. Read broker state before writing what happened, log the JSON
  verbatim, email "OUTCOME NOT RECORDED $DATE: <script> SYM" (the script has
  already alerted; this is the run's own record) and make no further broker
  mutation this run.
After any of them, still write today's TRADE-LOG entry and commit it, then
finish the run record with one --incident naming the exit (exit 12 also
passes --intent <the JSON's "intent">).

Unfinished intents in run records: pass one --intent per intent id a helper
printed (stderr "intent <id>: submitting attempt ..." or the JSON "intent").
An intent the run could not finish (exit 12, an 8 that survived its reruns, a
crash) stays non-terminal in the store; the next writer recovers it first, and
the read-only routines list it as "unfinished intent <id>" in their run
records until then.

STEP 0 — SYNC TO LATEST MAIN (mandatory, BEFORE reading any memory file):
git fetch origin main && git reset --hard FETCH_HEAD
The sandbox clone is often stale. Skipping this means trading on outdated
memory. If the fetch fails, STOP, email "SYNC FAILED $DATE", and exit.

STEP 0b — RUN RECORD START (ADR 0012; right after the sync, before
anything else):
python3 scripts/run_record.py start --routine market-open --trigger cloud \
    --command-file routines/market-open.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED market-open $DATE: <printed reason>" and STOP: a run that cannot
be recorded makes no broker mutation (ADR 0004 section 1).
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

STEP 1 — Read memory for today's plan:
- memory/TRADING-STRATEGY.md
- TODAY's entry in memory/RESEARCH-LOG.md (if missing, run pre-market
  STEPS 1-3 inline)
- tail of memory/TRADE-LOG.md (for weekly trade count)

STEP 2 — Re-validate with live data:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh quote <each planned ticker>

STEP 2b — On-entry ADR 0002 convergence (leftover fixed legs).
Before any new buys: `bash scripts/alpaca.sh orders` (open). Scan for leftover
fixed protective sells — `side=sell`, `type=stop` (NOT `trailing_stop`), trail
fields null/absent — covering a held position. Each is wrong-protection state
left when a prior convert failed; do NOT leave this to "the next routine".

For every leftover fixed stop, convert via scripts/replace_stop.py (validates before cancel, confirms cancel,
resumable on rerun — never a hand-written cancel/order pair):
Gate FIRST — conversion must never move the stop down. A new 10% trail starts
its high-water mark at today's price, so its stop is P × 0.90. S = the fixed
order's stop_price:
python3 scripts/validate_stop_change.py --current-stop S --new-stop "$(python3 -c 'import sys; from decimal import Decimal as D; print((D(sys.argv[1])*D("0.90")).quantize(D("0.01")))' P)" --current-price P --json
Exit 3 with `stop_never_lowered` → HOLD the fixed stop (intended state after an
expiry renewal, not a failure); log "HOLD fixed SYM @ S" and skip to next order.
Exit 0 → convert:
VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On VALIDATE_EXIT=0:
# One resumable command — never a hand-written cancel/order pair. It validates
# the replacement against the ACTUAL resting stop before cancel, confirms the
# cancel, submits client_order_id rs-<id>, restores the old level on failure.
REPLACE_JSON=$(python3 scripts/replace_stop.py --order-id ORDER_ID --trail-percent 10); REPLACE_EXIT=$?
# http_status is set only when this run submitted the order (not on resume).
HTTP_STATUS=$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind stop --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
REPLACE_EXIT: 0 replaced/already replaced/old stop filled · 3 refused, old stop
verifiably still protects, untouched → log + HOLD · 4 broker unavailable, nothing
changed and no uncovered position seen → STOP · 7 replacement failed, old level
restored as fixed stop → email "STOP REPLACE FAILED SYM", log · 8 UNPROTECTED — the
broker shows no verified stop for the position, whatever caused it (refused or
expired while uncovered, or mid-replacement) → rerun the SAME command now (resumes,
up to 3×); still 8 → email "UNPROTECTED SYM", log, STOP.
· 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
On VALIDATE_EXIT=3 → log violations, keep scanning. On VALIDATE_EXIT=4 → STOP, email, exit.

STEP 2b-ii — Coverage re-verification (ADR 0007). Monitoring may have been
stale for hours (GitHub fires the monitor ~2x/day); never add to a book you
have not just verified. Before any buy:
python3 scripts/protection_monitor.py --dry-run; COVERAGE_EXIT=$?
- Exit 0 → every position covered; proceed.
- Exit 5 → coverage short: NO new buys this session. Email
  "COVERAGE SHORT $DATE: <issues from the JSON>", log it under today's
  Market-Open entry, and go to STEP 8 (the monitor's next run or midday
  repairs; market-open never places protective orders for existing legs).
- Exit 4 → broker state unavailable: STOP, email "BROKER STATE UNAVAILABLE
  $DATE", exit.
- Exit 10 → state store unavailable: its unfinished intents could not be read
  and every buy would be refused anyway (validate_order exits 10). NO new buys
  this session; email "STATE STORE UNAVAILABLE $DATE: <reason>", log it, and
  continue as for exit 5.
- Any other exit (12 comes only from a live monitor run, never --dry-run) →
  STOP, email "COVERAGE CHECK FAILED $DATE exit=<N>", exit.

STEP 2c — Deployment backstop (rule 12). Computed, never eyeballed:
DEPLOY_JSON=$(python3 scripts/deployment_status.py); DEPLOY_EXIT=$?
- Exit 4 → STOP, email "DEPLOYMENT STATE UNAVAILABLE $DATE", exit.
- Exit 0 → no mandate; proceed with today's research plan only.
- Exit 5 → MANDATE DUE. The buy list MUST include one leadership add: the
  "Deployment mandate" name from today's RESEARCH-LOG, or, if absent, the
  top-momentum sector ETF not already held. Rule 14 constrains WHAT, never
  WHETHER: if no single name is held (empty book included) and the add is a
  broad ETF, today's RESEARCH-LOG must carry a "Composition waiver: <reason>"
  line; if it does not, append one now (why no single name passed the Entry
  Checklist) before STEP 3. If the add's sector is banned under rule 10
  (STEP 3), take the next sector that is not. Size: shares = floor(
  target_notional / live price). It goes through STEP 3-5 like any buy.
  Skip it ONLY if (a) today's RESEARCH-LOG recorded a valid deferral
  (exemption_allowed true + named market-wide risk event today), or
  (b) the risk engine refuses it (exit 3). Either way: log the reason to
  TRADE-LOG under "## $DATE — Market-Open (Deployment Backstop)", email
  "BACKSTOP ADD SKIPPED $DATE: <reason>", and commit at STEP 8.
  "Patience" is not a reason.

STEP 3 — Validate EVERY buy through the risk engine BEFORE placing it.
Do NOT hand-check sizing rules — the engine owns them (max positions,
max 20% size, max 3 trades/week, sufficient cash, 85% deployment ceiling,
stop required, min stop distance). Matching /trade.

ADR 0002: buys are OTO with a fixed stop_price leg (not a naked market buy).
STOP is the active version's entry distance below P (STRATEGY_VERSION: v1 =
10%, v2 = 7%); scripts/build_oto_order.py and scripts/submit_entry.py derive it.
Before validating under v2, the symbol's GICS sector MUST be recorded in
memory/SECTORS.json (commit it with the trade); a buy without a sector is
refused. Pass --sector to validate_order to mirror it.

Rule 10 (Script), once per session before the first buy. Every buy's sector
MUST be in memory/SECTORS.json (add it and commit it with the trade).
STREAKS_JSON=$(python3 scripts/blotter.py --sector-streaks); STREAKS_EXIT=$?
- Exit 4 (fills unavailable, memory/SECTORS.json missing or empty, or a
  traded symbol has no sector) → no new buys this session; email "RULE 10
  UNAVAILABLE $DATE", log it, go to STEP 8.
- Read SYM's sector entry from STREAKS_JSON. `"banned": true` → skip the buy
  (its sector ETF included), log "RULE 10 SECTOR BAN <sector> until
  <lifts_on>: SYM" to TRADE-LOG. A sector missing from STREAKS_JSON → add it
  to memory/SECTORS.json and rerun before buying. Open positions are never
  sold for it.
Rule 14 (Engine): if no single name is held (empty book included), a
broad-ETF buy (SPDR sector fund or index tracker) is refused unless it
carries a composition waiver. Pass one ONLY when today's RESEARCH-LOG has a
"Composition waiver: <reason>" line, with that same reason; without one →
skip it, log "RULE 14 SKIPPED SYM: no composition waiver" to TRADE-LOG.
The waiver goes to BOTH validate_order.py and submit_entry.py (the alpaca.sh
gate reads it back from the entry intent).
WAIVER_ARGS=()   # or: WAIVER_ARGS=(--composition-waiver "<reason from RESEARCH-LOG>")

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
    --price P --stop-price STOP --sector "GICS Sector" "${WAIVER_ARGS[@]}" --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
Exit 0 = approved → proceed.
Exit 3 = refused → skip this trade, log the violations verbatim to TRADE-LOG.
Exit 4 = broker state unavailable → STOP, email "VALIDATE STATE UNAVAILABLE $DATE", exit.
Exit 10 = state store unavailable (buys only: the reservations of unfinished
intents are unknown) → no new buys this session; email "STATE STORE
UNAVAILABLE $DATE: <reason>", log it, go to STEP 6.

Also confirm a catalyst is documented in today's RESEARCH-LOG (the engine
cannot judge catalyst quality — see risk_engine.UNMECHANISED).

STEP 4 — Execute the buy as one OTO (entry + fixed protective leg) through
scripts/submit_entry.py — the ONLY sanctioned buy path. It builds the OTO,
names the entry intent en-<YYYYMMDD>-<SYM> (ADR 0005), looks its attempts up
BEFORE submitting (a rerun after a crash/timeout never buys twice; a dead
attempt is retried as -r1.. automatically, no --tag needed), submits through
alpaca.sh (which re-validates the exact body with ALPACA_RISK_OK=1), and
confirms by client id. Never hand-write a raw order call for a buy.

ENTRY_JSON=$(python3 scripts/submit_entry.py --symbol SYM --qty N --price P "${WAIVER_ARGS[@]}"); ENTRY_EXIT=$?
# http_status is set only when THIS run submitted (not on already_submitted).
HTTP_STATUS=$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
ENTRY_EXIT: 0 submitted / already_submitted / already_filled (use the returned
order id) · 3 refused, broker_rejected or entry_retries_exhausted → log
verbatim, skip · 4 broker unavailable → STOP · 8 outcome unknown → rerun the
JSON `rerun` command now (it carries --intent and resumes); still 8 →
email "ENTRY OUTCOME UNKNOWN SYM", STOP the buy path for that symbol. An 8 with
state *_position_unprotected means the symbol is already held with no verified
stop: email "UNPROTECTED SYM", STOP.
· 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
Gate before any convert: read filled_qty on the parent AND the
protective leg. Do NOT convert, and do NOT assume the position is protected,
until BOTH are true:
  (a) filled_qty is known and filled_qty == qty (complete fill);
  (b) legs[] matches FixedStop (type=stop, trail fields null).
If filled_qty != qty (partial fill) OR residual shares would be uncovered:
INCIDENT — hard-fail. Email, log to TRADE-LOG, stop the buy path for that
symbol. Never proceed as full size; never convert on assumed full qty
(ADR 0002 / quant seal).
If leg wrong/missing after a complete fill: INCIDENT — email; do not assume
protection.

STEP 5 — Convert the fixed OTO leg to the trailing stop GTC (ADR 0002).
Under v1 convert immediately after the fill; under v2 (rule 4) the fixed
leg stays until the position is up +5% — the protection monitor
(.github/workflows/protection-monitor.yml, scheduled for 30 min but GitHub
fires it only ~2x/day at unpredictable times; no Claude, no ledger)
converts it when it happens to run. Under v2 convert it yourself here when
the +5% gate is met; do not defer to the monitor.
ONLY after the STEP 4 gate (filled_qty == qty AND leg matches). Use scripts/replace_stop.py on
the fixed leg: it validates first, cancels (shares are reserved), confirms
the cancel, then places the trail — resumable, never a hand-written pair.

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On VALIDATE_EXIT=0:
# One resumable command — never a hand-written cancel/order pair. It validates
# the replacement against the ACTUAL resting stop before cancel, confirms the
# cancel, submits client_order_id rs-<id>, restores the old level on failure.
REPLACE_JSON=$(python3 scripts/replace_stop.py --order-id LEG_ORDER_ID --trail-percent 10); REPLACE_EXIT=$?
# http_status is set only when this run submitted the order (not on resume).
HTTP_STATUS=$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind stop --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
REPLACE_EXIT: 0 replaced/already replaced/old stop filled · 3 refused, old stop
verifiably still protects, untouched → log + HOLD · 4 broker unavailable, nothing
changed and no uncovered position seen → STOP · 7 replacement failed, old level
restored as fixed stop → email "STOP REPLACE FAILED SYM", log · 8 UNPROTECTED — the
broker shows no verified stop for the position, whatever caused it (refused or
expired while uncovered, or mid-replacement) → rerun the SAME command now (resumes,
up to 3×); still 8 → email "UNPROTECTED SYM", log, STOP.
· 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
Query open orders/position before claiming protected: if neither the fixed
leg nor the trail is present, that is an incident. Do NOT wire T2 /
issue #32 stop-change or trail-ladder validators. #40 PATCH still OPEN — do
not claim the sub-second cancel→place window is closed; replace_stop makes it
recoverable, not atomic.

STEP 6 — Append today's Market-Open entry to memory/TRADE-LOG.md (matching
existing format). With trades: date, ticker, side, shares, entry price, stop
level, thesis, target, R:R per trade. WITHOUT trades: still write the entry,
headed "### $DATE — Market-Open", opening "**No trades.**" with the reason
(HOLD plan, coverage short, mandate refused, ...). The heartbeat distinguishes
"did not run" from "nothing to do" only by this record.

STEP 7 — Notification: only if a trade was placed.
bash scripts/email.sh "<tickers, shares, fill prices, one-line why>"
email.sh exits non-zero when the owner was not told (creds unset, Resend
rejected the send, a verified bounce, or an unreadable status); treat that as
"the owner was not told": retry once, then note "ALERT NOT DELIVERED" in the
TRADE-LOG entry. Exit 0 with "delivery=unverified" means it was sent but the
key cannot check delivery: not a failure, do not retry.

STEP 8 — COMMIT, PUSH, VERIFY (mandatory EVERY trading day — the commit is
the no-trade outcome record the heartbeat reads):
SUBJECT="market-open trades $DATE"      # any order submitted or backstop skip logged
SUBJECT="market-open no-trade $DATE"    # otherwise
git add memory/TRADE-LOG.md
git commit -m "$SUBJECT"
git push origin HEAD:main || { git pull --rebase origin main && git push origin HEAD:main; }
Never force-push.

Then VERIFY the push landed (the proxy rewrites SHAs — compare subjects,
never SHAs):
git fetch origin main
git log --format=%s -3 FETCH_HEAD | grep -qxF "$SUBJECT" \
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
no-trade; the outcome is derived. Never invent entries. On a non-zero exit
email "RUN RECORD FINISH FAILED market-open $DATE: <printed reason>".
