---
description: Manual trade helper with strategy-rule validation. Usage — /trade SYMBOL SHARES buy|sell
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

Execute a manual trade. The risk engine decides whether it is allowed — you do
not re-derive the rules yourself, and you do not overrule it.

Args: SYMBOL SHARES SIDE (buy or sell). If missing, ask.

1. Pull the quote to get the ask price P:
   `bash scripts/alpaca.sh quote SYMBOL`

2. Validate through the risk engine. This is mandatory and it reads live
   account state itself — do not hand-check the rules.

   For BUYs (ADR 0002 OTO fixed leg — validate with --stop-price, not trail-only):
   ```
   VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
       --price P --stop-price STOP --json)
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```
   STOP = 10% below P (or let `scripts/build_oto_order.py oto --price P` derive it).

   For SELLs:
   ```
   VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --json)
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```

   Exit 0 = approved. Exit 3 = refused. Exit 4 = broker state unavailable. Exit 6 = ledger fail.

3. **If it exits non-zero, STOP.** Print the violations verbatim and do not
   submit anything. Do not retry with different numbers unless the operator
   asks. If it suggests a `max shares permitted right now`, you may offer that
   smaller size — re-validate it before proceeding.

4. For BUYs the engine requires a stop on the order itself; there is no
   approved unprotected buy. Confirm a catalyst is documented in today's
   RESEARCH-LOG (the engine cannot judge catalyst quality — see
   `risk_engine.UNMECHANISED`).

5. Print the OTO/sell JSON and the validation verdict, then ask "execute? (y/n)".

6. On confirm (mutating alpaca requires ALPACA_RISK_OK=1 after validation):

   BUY — one OTO call (entry + fixed protective leg). Never a bare market buy:
   ```
   # LEDGER_ORDER_ID from the buy validate --json above (re-assert before record)
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   # submit_entry.py: OTO via build_oto_order.py, client id en-<YYYYMMDD>-<SYM>, lookup before submit; exit 8 → rerun same command
   ENTRY_JSON=$(python3 scripts/submit_entry.py --symbol SYM --qty N --price P); ENTRY_EXIT=$?
   HTTP_STATUS=$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
   if [ -n "$HTTP_STATUS" ]; then
     python3 scripts/record_broker_response.py \
         --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
         --response "$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
   fi
   ```
   Gate before convert: filled_qty known AND filled_qty == qty, AND legs[]
   matches FixedStop (type=stop, trail null). If filled_qty != qty or residual
   shares uncovered: INCIDENT — hard-fail. Email/log; do NOT convert or assume
   protected (ADR 0002 / quant seal).

   SELL of a protected position — cancel-then-close (#38) through the
   resumable script (cancel confirmed, sell stamped cl-<YYYYMMDD>-<SYM>,
   exit 8 = naked → rerun the same command):
   ```
   CLOSE_JSON=$(python3 scripts/close_position.py --symbol SYM --reason "<why>"); CLOSE_EXIT=$?
   ```

7. For BUYs, convert ONLY after the fill+leg gate above (scripts/replace_stop.py —
   validates first, confirms cancel, resumable):

   ```
   VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --trail-percent 10 --json)
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```

   On exit 0:
   ```
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
   ```
   Query before claiming protected: neither fixed leg nor trail = incident.
   #40 still OPEN.

8. Log to memory/TRADE-LOG.md with full thesis, entry, stop, target, R:R.

9. `bash scripts/email.sh` with trade details.

Note: entry is atomic via OTO (ADR 0002). Conversion (replace_stop) and sell
cancel→close still have brief windows; PATCH (#40) is OPEN and not invented here.
