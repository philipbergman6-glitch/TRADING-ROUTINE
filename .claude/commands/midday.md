---
description: Midday scan — cut losers at -7%, tighten stops on winners, thesis check
---

## Run record (first step, ADR 0012)

Local runs write through the dedicated clone (`--local`, ADR 0004 section 3).
State goes through the same clone, never through this development checkout's
origin: every validate_order, submit_entry, close_position, replace_stop,
protection_monitor and coordinator call below carries the
TRADING_STATE_STORE=local prefix. Each Bash call is a fresh shell, so the
prefix goes on every call; an `export` does not carry over.

python3 scripts/run_record.py --local start --routine midday --trigger local \
    --command-file .claude/commands/midday.md --model "<your model id>"
--model is the exact model ID your own system prompt states; never guess one
(no environment variable exposes it). If it exits non-zero (10 = store
unavailable, 2 = usage), email
"RUN RECORD FAILED midday $DATE: <printed reason>" and STOP: a run that cannot
be recorded makes no broker mutation (ADR 0004 section 1).
If the run STOPs anywhere after this point, run the finish step first with
--incident naming why.

## Strategy version gate (run first)

The approved version is "active" in docs/rulebook-pins.json (ADR 0011).
STRATEGY_VERSION must be set to its engine (v1) or the full version named there;
UNSET IS REFUSED, and the rulebook marker and hash must match the pin. Run:
    python3 scripts/strategy_version.py || exit 1
Exit 5 = env, marker or rulebook hash disagree, exit 1 = pins unreadable. STOP
on either — never trade under a rule set you did not intend. The mutation
scripts enforce the same binding and refuse (state version_binding_refused). Quote the printed
"STRATEGY_VERSION: vN" line in the TRADE-LOG entry.

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
VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py ... --json)
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

You are running the midday scan workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

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

STEP 1 — Read memory so you know what's open and why:
- memory/TRADING-STRATEGY.md (exit rules)
- tail of memory/TRADE-LOG.md (entries, original thesis per position, stops)
- today's memory/RESEARCH-LOG.md entry

STEP 2 — Pull current state:
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders
python3 scripts/blotter.py --check   # fill-based FIFO book must match positions
The protection monitor (.github/workflows/protection-monitor.yml) is
scheduled every 30 min but GitHub fires it only ~2x/day at unpredictable
times (service level and measurement: ADR 0007; the heartbeat reports the
stale windows each evening). It may have renewed, converted or tightened stops; read broker state,
never assume what it did, and never write in the log that it acted unless
its run appears in `gh run list --workflow=protection-monitor.yml`.

STEP 2b — On-entry ADR 0002 convergence (leftover fixed legs).
Scan open orders from STEP 2 for leftover fixed protective sells —
`side=sell`, `type=stop` (NOT `trailing_stop`), trail fields null/absent —
covering a held position. Convert each via scripts/replace_stop.py
(never a hand-written cancel/order pair). Do NOT leave convergence as wishful "next routine" prose.

Gate FIRST — conversion must never move the stop down. A new 10% trail starts
its high-water mark at today's price, so its stop is P × 0.90. S = the fixed
order's stop_price:
python3 scripts/validate_stop_change.py --current-stop S --new-stop "$(python3 -c 'import sys; from decimal import Decimal as D; print((D(sys.argv[1])*D("0.90")).quantize(D("0.01")))' P)" --current-price P --json
Exit 3 with `stop_never_lowered` → HOLD the fixed stop (intended state after an
expiry renewal, not a failure); log "HOLD fixed SYM @ S" and skip to next order.
Exit 0 → convert:
VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On VALIDATE_EXIT=0:
# One resumable command — never a hand-written cancel/order pair. It validates
# the replacement against the ACTUAL resting stop before cancel, confirms the
# cancel, submits client_order_id rs-<id>, restores the old level on failure.
REPLACE_JSON=$(TRADING_STATE_STORE=local python3 scripts/replace_stop.py --order-id ORDER_ID --trail-percent 10); REPLACE_EXIT=$?
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
On validate_order exit 3 → log, keep scanning. On exit 4 → STOP. On exit 6 → STOP (ledger).

Standing stops (rule 7, v1.2). For every resting protective stop, fixed or
trailing, where (P − S) / P < 3%: leave it — do not move, convert, widen or
lower it — and log "STANDING SYM stop S is X.XX% below P (rule 7: left, recorded)"
under today's entry in TRADE-LOG, every session it persists. The protection
monitor reports the same condition as `standing`. It is a hold, not a violation.

STEP 2c — Renew expiring protective stops (Alpaca GTC expires after ~90 days).
bash scripts/alpaca.sh orders | python3 scripts/build_oto_order.py expiring
For each item (renew_stop_price = current stop level rounded UP — never lower),
renew via scripts/replace_stop.py --stop-price. Replacement is a FIXED
stop, not a fresh trail — a fresh trail would restart its high-water mark and
drop the stop. STEP 2b holds it fixed until a 10% trail would sit at/above it.
A held or renewed fixed stop is permitted protection (rule 4, v1.2), not a fault.

Gate with the stop-change validator in renewal mode, NOT validate_order:
validate_order judges a new entry (9.5–10.5% band, 3% minimum against current
price) and refuses a valid renewal. Rule 7 (v1.2): renewing at the current
level is never a violation, even inside 3% of price. S = the expiring order's stop_price:
python3 scripts/validate_stop_change.py --current-stop S --new-stop RENEW_STOP_PRICE --current-price P --renewal --json
- Exit 0 → renew (below), also when price sits within 3% of S.
- Exit 3 with `stop_never_lowered` → RENEW_STOP_PRICE is wrong; do NOT renew,
  email "RENEWAL REFUSED SYM", log.
- Exit 3 with `stop_distance` → RENEW_STOP_PRICE is above S rounded up to the
  cent (a raise is a change, so the 3% minimum applies) or S is at/above price;
  do NOT renew, email "RENEWAL REFUSED SYM", log.
Renew:
REPLACE_JSON=$(TRADING_STATE_STORE=local python3 scripts/replace_stop.py --order-id ORDER_ID --stop-price RENEW_STOP_PRICE); REPLACE_EXIT=$?
# A renewal is not a ledger order (the protection monitor renews the same way, without
# the ledger): record_broker_response --kind stop is not run for it.
REPLACE_EXIT handling as in STEP 2b (3 → old stop untouched, email; 7 → email;
8 → rerun the SAME command, still 8 → email "UNPROTECTED SYM", STOP; 4 → STOP)
· 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
Log "Stop renewed SYM: <old type> → fixed @ RENEW_STOP_PRICE (expiry)" to TRADE-LOG.

STEP 3 — Cut losers immediately. For every position where
unrealized_plpc <= -0.07, validate the sell through the risk engine first
(paper + position coherence). Do NOT skip validate_order:

VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
Exit 0 = approved → proceed.
Exit 3 = refused → log violations verbatim; do not close.
Exit 4 = broker state unavailable → STOP, email alert, exit.

On approve, close through scripts/close_position.py — the ONLY sanctioned
exit path. It performs the mandatory cancel-then-close (#38 / CUT_LOSER_STEPS)
with every step confirmed from broker state: preflights the sell while the
stop still rests, cancels the stop and polls until `canceled`, confirms the
position, submits the market sell under close intent cl-<YYYYMMDD>-<SYM>
(ADR 0005: attempts -r1.. after a dead sell; a same-day re-entry gets -2) and
confirms it. Done means the symbol is no longer held and no buy is live, never
merely that an earlier sell filled. A rerun resumes; it never sells twice and
never leaves the position naked silently. Never hand-write the cancel/close pair.

CLOSE_JSON=$(TRADING_STATE_STORE=local python3 scripts/close_position.py --symbol SYM --reason "cut at -7% per rule"); CLOSE_EXIT=$?
HTTP_STATUS=$(printf "%s" "$CLOSE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$CLOSE_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
CLOSE_EXIT: 0 close submitted / already closing / close_complete or position
gone (not held, no buy live) · 2 no position, or a stop/sell resting with
nothing held → log verbatim, email the state · 3 refused, a verified stop still
protects, or position_gone_buy_live → log, HOLD · 4 broker unavailable,
no uncovered position seen → STOP · 8 UNPROTECTED — the broker shows no verified
stop for the position (refused or unreadable while uncovered, or stop canceled
and sell not confirmed) → rerun the JSON `rerun` command now (it carries
--intent, so it resolves this close even after UTC midnight); still 8 → email
"UNPROTECTED SYM", STOP.
· 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
Log the exit to TRADE-LOG: exit price, realized P&L (from
`python3 scripts/blotter.py --markdown`, fill-based), "cut at -7% per rule".

STEP 4 — Tighten trailing stops on winners. Ladder is owned by the engine
(`required_trail_percent` via `scripts/validate_stop_change.py`) — do NOT
hand-compute 15%/20% thresholds in prose.

For each position with a resting trailing stop:
  G = unrealized_plpc * 100          # e.g. 0.16 → 16
  C = current trail_percent on the open sell order
  S = actual stop_price on the resting broker order (preserves its high-water mark)
  P = current mark price

Ask the engine for the widest trail still permitted, then validate the change:
T=$(python3 scripts/validate_stop_change.py --gain-pct G --print-required)
# Skip if already at or tighter than required (nothing to tighten).
python3 scripts/validate_stop_change.py --gain-pct G --proposed-trail T \
    --current-trail C --current-stop S --current-price P --json
Exit 0 = approved trail/stop change (wires required_trail_percent +
validate_stop_change against the actual broker stop).
Exit 3 = refused → skip tighten, log violations verbatim.
Exit 2 = usage → STOP, fix inputs.

Then validate the replacement protective sell (T1) before mutating:
VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent T --json); VALIDATE_EXIT=$?
[ "$VALIDATE_EXIT" -eq 0 ] || echo "VALIDATE REFUSED exit=$VALIDATE_EXIT: $VALIDATE_JSON"   # branch on VALIDATE_EXIT, never on reading the JSON
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On VALIDATE_EXIT=0:
# One resumable command — never a hand-written cancel/order pair. It validates
# the replacement against the ACTUAL resting stop before cancel, confirms the
# cancel, submits client_order_id rs-<id>, restores the old level on failure.
REPLACE_JSON=$(TRADING_STATE_STORE=local python3 scripts/replace_stop.py --order-id ORDER_ID --trail-percent T); REPLACE_EXIT=$?
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
On validate_order exit 3 → skip tighten, log. On exit 4 → STOP. On exit 6 → STOP (ledger).
#40 PATCH resize is OPEN — do not invent a patch path. replace_stop leaves a
sub-second cancel→place window but validates first, confirms the cancel,
restores the old level on failure and resumes on rerun. T2 validates the stop/trail change; it does not
close that window.

STEP 5 — Thesis check. If a thesis broke intraday, cut the position even
if not at -7% yet — same validate_order + scripts/close_position.py gate as
STEP 3. Document reasoning in TRADE-LOG.

STEP 6 — Optional intraday research via Perplexity if something is moving
sharply with no obvious cause. Append afternoon addendum to RESEARCH-LOG.

STEP 7 — Notification: only if action was taken.
bash scripts/email.sh "<action summary>"

LAST STEP — RUN RECORD FINISH (ADR 0012):
python3 scripts/run_record.py --local finish \
    [--action "<broker mutation made>"]... [--refusal "<action a rule refused>"]... \
    [--incident "<what went wrong>"]... [--intent <intent id>]...
One --action per broker mutation this run made (buy, sell, stop replace or
renew), one --refusal per action a validator or rule refused, one
--incident per failure (STOP, push not verified, alert not delivered,
coverage short), one --intent per intent id a helper printed. No flags =
no-trade; the outcome is derived. Never invent entries. On a non-zero exit
email "RUN RECORD FINISH FAILED midday $DATE: <printed reason>".
