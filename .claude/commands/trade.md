---
description: Manual trade helper with strategy-rule validation. Usage — /trade SYMBOL SHARES buy|sell
---

## Strategy version gate (run first)

The approved version is "active" in docs/rulebook-pins.json (ADR 0011).
STRATEGY_VERSION must be set to its engine (v1) or the full version named there;
UNSET IS REFUSED, and the rulebook marker and hash must match the pin. Run:
    python3 scripts/strategy_version.py || exit 1
Exit 5 = env, marker or rulebook hash disagree, exit 1 = pins unreadable. STOP
on either — never trade under a rule set you did not intend. The mutation
scripts enforce the same binding and refuse (state version_binding_refused). Quote the printed
"STRATEGY_VERSION: vN" line in the TRADE-LOG entry.

## State store (run first, ADR 0004 section 3)

/trade writes state through the dedicated local clone, never through this
development checkout's origin: every validate_order, submit_entry,
close_position, replace_stop, protection_monitor and coordinator call below
carries the TRADING_STATE_STORE=local prefix. Each Bash call is a fresh shell,
so the prefix goes on every call; an `export` does not carry over.

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
After any of them STOP, log it to memory/TRADE-LOG.md and tell the owner
(exit 12: name the JSON's "intent" and quote the JSON verbatim).

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

Execute a manual trade. The risk engine decides whether it is allowed — you do
not re-derive the rules yourself, and you do not overrule it.

Args: SYMBOL SHARES SIDE (buy or sell). If missing, ask.

1. Pull the quote to get the ask price P:
   `bash scripts/alpaca.sh quote SYMBOL`

   For BUYs, rules 10 and 14 first (the engine does not check either):
   - Rule 10 (Script): SYMBOL's sector MUST be in memory/SECTORS.json. Run
     `python3 scripts/blotter.py --sector-streaks`; exit 4 → STOP. A sector
     whose entry has `"banned": true` is closed until its `lifts_on` date;
     buying into it, its sector ETF included → STOP and report the lift
     date. A sector missing from the output → add it to memory/SECTORS.json
     and rerun.
   - Rule 14 (Advisory until #136): if no single name is held (empty book
     included) and SYMBOL is a broad ETF (SPDR sector fund or index tracker),
     STOP unless the owner states the composition waiver (why no single name
     passes the Entry Checklist); write it to today's RESEARCH-LOG entry as
     "Composition waiver: <reason>" before validating.

2. Validate through the risk engine. This is mandatory and it reads live
   account state itself — do not hand-check the rules.

   For BUYs (ADR 0002 OTO fixed leg — validate with --stop-price, not trail-only):
   ```
   VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
       --price P --stop-price STOP --json); VALIDATE_EXIT=$?
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```
   Exit 10 (buys only) = state store unavailable: the reservations of
   unfinished intents are unknown → STOP; nothing was submitted.
   STOP = 10% below P (or let `scripts/build_oto_order.py oto --price P` derive it).

   For SELLs:
   ```
   VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --json); VALIDATE_EXIT=$?
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```

   Branch on `$VALIDATE_EXIT`, never on reading the JSON: 0 = approved. 3 = refused. 4 = broker state unavailable. 6 = ledger fail. 10 = buy refused: state store unavailable.

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
   # submit_entry.py: OTO via build_oto_order.py, intent en-<YYYYMMDD>-<SYM> (ADR 0005), lookup before submit; exit 8 → run the JSON `rerun` command
   ENTRY_JSON=$(TRADING_STATE_STORE=local python3 scripts/submit_entry.py --symbol SYM --qty N --price P); ENTRY_EXIT=$?
   HTTP_STATUS=$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("http_status") or "")')
   if [ -n "$HTTP_STATUS" ]; then
     python3 scripts/record_broker_response.py \
         --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
         --response "$(printf "%s" "$ENTRY_JSON" | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin).get("order") or {}))')"
   fi
   ```
   ENTRY_EXIT: 0 submitted / already_submitted / already_filled (use the returned
   order id) · 3 refused, broker_rejected or entry_retries_exhausted → log
   verbatim, STOP · 4 broker unavailable → STOP · 8 outcome unknown → run the
   JSON `rerun` command now (it carries --intent and resumes); still 8 → email
   "ENTRY OUTCOME UNKNOWN SYM", STOP. An 8 with state *_position_unprotected
   means the symbol is held with no verified stop: email "UNPROTECTED SYM", STOP.
   · 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
   broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
   do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
   Gate before convert: filled_qty known AND filled_qty == qty, AND legs[]
   matches FixedStop (type=stop, trail null). If filled_qty != qty or residual
   shares uncovered: INCIDENT — hard-fail. Email/log; do NOT convert or assume
   protected (ADR 0002 / quant seal).

   SELL of a protected position — cancel-then-close (#38) through the
   resumable script (cancel confirmed, sell under intent cl-<YYYYMMDD>-<SYM>,
   complete only when no longer held; exit 8 = naked → run the JSON `rerun`
   command, which carries --intent):
   ```
   CLOSE_JSON=$(TRADING_STATE_STORE=local python3 scripts/close_position.py --symbol SYM --reason "<why>"); CLOSE_EXIT=$?
   ```
   CLOSE_EXIT: 0 close submitted / already closing / close_complete or position
   gone · 2 no position, or a stop/sell resting with nothing held → report it ·
   3 refused, a verified stop still protects → HOLD · 4 broker unavailable → STOP ·
   8 UNPROTECTED → run the JSON `rerun` command now; still 8 → email
   "UNPROTECTED SYM", STOP.
   · 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
   broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
   do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).

7. For BUYs, convert ONLY after the fill+leg gate above (scripts/replace_stop.py —
   validates first, confirms cancel, resumable):

   ```
   VALIDATE_JSON=$(TRADING_STATE_STORE=local python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --trail-percent 10 --json); VALIDATE_EXIT=$?
   LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
   ```

   On exit 0:
   ```
   # One resumable command — never a hand-written cancel/order pair. It validates
   # the replacement against the ACTUAL resting stop before cancel, confirms the
   # cancel, submits client_order_id rs-<id>, restores the old level on failure.
   REPLACE_JSON=$(TRADING_STATE_STORE=local python3 scripts/replace_stop.py --order-id LEG_ORDER_ID --trail-percent 10); REPLACE_EXIT=$?
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
   · 10 store unavailable / 11 lease wait exhausted → nothing changed: no further
   broker mutation this run, email, log · 12 acted, outcome NOT recorded → INCIDENT,
   do NOT rerun: log the JSON, email, no further broker mutation (Coordinator exits).
   ```
   Query before claiming protected: neither fixed leg nor trail = incident.
   #40 still OPEN.

8. Log to memory/TRADE-LOG.md with full thesis, entry, stop, target, R:R.

9. `bash scripts/email.sh` with trade details.

Note: entry is atomic via OTO (ADR 0002). Conversion (replace_stop) and sell
cancel→close still have brief windows; PATCH (#40) is OPEN and not invented here.
