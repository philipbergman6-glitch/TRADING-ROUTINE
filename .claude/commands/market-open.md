---
description: Market-open execution — validate, place buys, set 10% trailing stops
---

## Strategy version gate (run first)

STRATEGY_VERSION selects the rule set and UNSET silently means v1. The declared
version lives in memory/TRADING-STRATEGY.md ("Active strategy version"). Run:
    python3 scripts/strategy_version.py || exit 1
Exit 5 = env and declared version disagree, exit 1 = marker unreadable. STOP on
either — never trade under a rule set you did not intend. Quote the printed
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

You are running the market-open execution workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

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
    --price P --trail-percent 10 --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0:
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
untouched → log + HOLD · 4 broker unavailable, nothing changed → STOP · 7 replacement
failed, old level restored as fixed stop → email "STOP REPLACE FAILED SYM", log ·
8 possibly UNPROTECTED → rerun the SAME command now (resumes, up to 3×); still 8 →
email "UNPROTECTED SYM", log, STOP.
On exit 3 → log violations, keep scanning. On exit 4 → STOP, email, exit.

STEP 2c — Deployment backstop (rule 12). Computed, never eyeballed:
DEPLOY_JSON=$(python3 scripts/deployment_status.py); DEPLOY_EXIT=$?
- Exit 4 → STOP, email "DEPLOYMENT STATE UNAVAILABLE $DATE", exit.
- Exit 0 → no mandate; proceed with today's research plan only.
- Exit 5 → MANDATE DUE. The buy list MUST include one leadership add: the
  "Deployment mandate" name from today's RESEARCH-LOG, or, if absent, the
  top-momentum sector ETF not already held. Size: shares = floor(
  target_notional / live price). It goes through STEP 3-5 like any buy.
  Skip it ONLY if (a) today's RESEARCH-LOG recorded a valid deferral
  (exemption_allowed true + named market-wide risk event today), or
  (b) the risk engine refuses it (exit 3). Either way: log the reason to
  TRADE-LOG under "## $DATE — Market-Open (Deployment Backstop)", email
  "BACKSTOP ADD SKIPPED $DATE: <reason>", and commit the log.
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

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
    --price P --stop-price STOP --sector "GICS Sector" --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
Exit 0 = approved → proceed.
Exit 3 = refused → skip this trade, log the violations verbatim to TRADE-LOG.
Exit 4 = broker state unavailable → STOP, email "VALIDATE STATE UNAVAILABLE $DATE", exit.

Also confirm a catalyst is documented in today's RESEARCH-LOG (the engine
cannot judge catalyst quality — see risk_engine.UNMECHANISED).

STEP 4 — Execute the buy as one OTO (entry + fixed protective leg) through
scripts/submit_entry.py — the ONLY sanctioned buy path. It builds the OTO,
stamps client_order_id en-<YYYYMMDD>-<SYM>, looks that id up BEFORE
submitting (a rerun after a crash/timeout never buys twice), submits through
alpaca.sh (which re-validates the exact body with ALPACA_RISK_OK=1), and
confirms by client id. Never hand-write a raw order call for a buy.

ENTRY_JSON=$(python3 scripts/submit_entry.py --symbol SYM --qty N --price P); ENTRY_EXIT=$?
# http_status is set only when THIS run submitted (not on already_submitted).
HTTP_STATUS=$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
ENTRY_EXIT: 0 submitted / already_submitted (use the returned order id) · 3
refused or broker_rejected → log verbatim, skip · 4 broker unavailable →
STOP · 8 outcome unknown → rerun the SAME command now (it resumes); still 8 →
email "ENTRY OUTCOME UNKNOWN SYM", STOP the buy path for that symbol.
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
(.github/workflows/protection-monitor.yml, runs every 30 min without Claude
or the ledger) converts it then. Under v2, SKIP this step unless the
monitor's last report shows a HOLD you are asked to resolve.
ONLY after the STEP 4 gate (filled_qty == qty AND leg matches). Use scripts/replace_stop.py on
the fixed leg: it validates first, cancels (shares are reserved), confirms
the cancel, then places the trail — resumable, never a hand-written pair.

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0:
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
untouched → log + HOLD · 4 broker unavailable, nothing changed → STOP · 7 replacement
failed, old level restored as fixed stop → email "STOP REPLACE FAILED SYM", log ·
8 possibly UNPROTECTED → rerun the SAME command now (resumes, up to 3×); still 8 →
email "UNPROTECTED SYM", log, STOP.
Query open orders/position before claiming protected: if neither the fixed
leg nor the trail is present, that is an incident. Do NOT wire T2 /
issue #32 stop-change or trail-ladder validators. #40 PATCH still OPEN — do
not claim the sub-second cancel→place window is closed; replace_stop makes it
recoverable, not atomic.

STEP 6 — Append each trade to memory/TRADE-LOG.md (matching existing format):
Date, ticker, side, shares, entry price, stop level, thesis, target, R:R.

STEP 7 — Notification: only if a trade was placed.
bash scripts/email.sh "<tickers, shares, fill prices, one-line why>"
