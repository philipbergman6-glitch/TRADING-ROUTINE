---
description: Midday scan — cut losers at -7%, tighten stops on winners, thesis check
---

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

You are running the midday scan workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory so you know what's open and why:
- memory/TRADING-STRATEGY.md (exit rules)
- tail of memory/TRADE-LOG.md (entries, original thesis per position, stops)
- today's memory/RESEARCH-LOG.md entry

STEP 2 — Pull current state:
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders

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
On validate_order exit 3 → log, keep scanning. On exit 4 → STOP. On exit 6 → STOP (ledger).

STEP 2c — Renew expiring protective stops (Alpaca GTC expires after ~90 days).
bash scripts/alpaca.sh orders | python3 scripts/build_oto_order.py expiring
For each item (renew_stop_price = current stop level rounded UP — never lower),
renew via scripts/replace_stop.py --stop-price. Replacement is a FIXED
stop, not a fresh trail — a fresh trail would restart its high-water mark and
drop the stop. STEP 2b holds it fixed until a 10% trail would sit at/above it.

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --stop-price RENEW_STOP_PRICE --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0:
REPLACE_JSON=$(python3 scripts/replace_stop.py --order-id ORDER_ID --stop-price RENEW_STOP_PRICE); REPLACE_EXIT=$?
# http_status is set only when this run submitted the order (not on resume).
HTTP_STATUS=$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
if [ -n "$HTTP_STATUS" ]; then
  python3 scripts/record_broker_response.py \
      --order-id "$LEDGER_ORDER_ID" --kind stop --http-status "$HTTP_STATUS" \
      --response "$(printf "%s" "$REPLACE_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
fi
REPLACE_EXIT handling as in STEP 2b (3 → old stop untouched, email; 7 → email;
8 → rerun the SAME command, still 8 → email "UNPROTECTED SYM", STOP).
validate_order exit 3 → do NOT run replace_stop; email. Exit 4/6 → STOP.
Log "Stop renewed SYM: <old type> → fixed @ RENEW_STOP_PRICE (expiry)" to TRADE-LOG.

STEP 3 — Cut losers immediately. For every position where
unrealized_plpc <= -0.07, validate the sell through the risk engine first
(paper + position coherence). Do NOT skip validate_order:

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
Exit 0 = approved → proceed.
Exit 3 = refused → log violations verbatim; do not close.
Exit 4 = broker state unavailable → STOP, email alert, exit.

On approve (mutating alpaca requires ALPACA_RISK_OK=1).
Order is mandatory cancel-then-close (#38 / CUT_LOSER_STEPS): close alone
403s while reserved, and close-then-cancel leaves the loser held AND naked.
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID   # release reserved shares
ALPACA_RISK_OK=1 bash scripts/alpaca.sh close SYM
Log the exit to TRADE-LOG: exit price, realized P&L, "cut at -7% per rule".

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
VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent T --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0:
# One resumable command — never a hand-written cancel/order pair. It validates
# the replacement against the ACTUAL resting stop before cancel, confirms the
# cancel, submits client_order_id rs-<id>, restores the old level on failure.
REPLACE_JSON=$(python3 scripts/replace_stop.py --order-id ORDER_ID --trail-percent T); REPLACE_EXIT=$?
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
On validate_order exit 3 → skip tighten, log. On exit 4 → STOP. On exit 6 → STOP (ledger).
#40 PATCH resize is OPEN — do not invent a patch path. replace_stop leaves a
sub-second cancel→place window but validates first, confirms the cancel,
restores the old level on failure and resumes on rerun. T2 validates the stop/trail change; it does not
close that window.

STEP 5 — Thesis check. If a thesis broke intraday, cut the position even
if not at -7% yet — same validate_order + ALPACA_RISK_OK cancel-then-close gate
as STEP 3. Document reasoning in TRADE-LOG.

STEP 6 — Optional intraday research via Perplexity if something is moving
sharply with no obvious cause. Append afternoon addendum to RESEARCH-LOG.

STEP 7 — Notification: only if action was taken.
bash scripts/email.sh "<action summary>"
