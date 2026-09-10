---
description: Manual trade helper with strategy-rule validation. Usage — /trade SYMBOL SHARES buy|sell
---

Execute a manual trade. The risk engine decides whether it is allowed — you do
not re-derive the rules yourself, and you do not overrule it.

Args: SYMBOL SHARES SIDE (buy or sell). If missing, ask.

1. Pull the quote to get the ask price P:
   `bash scripts/alpaca.sh quote SYMBOL`

2. Validate through the risk engine. This is mandatory and it reads live
   account state itself — do not hand-check the rules.

   For BUYs (ADR 0002 OTO fixed leg — validate with --stop-price, not trail-only):
   ```
   python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
       --price P --stop-price STOP --json
   ```
   STOP = 10% below P (or let `scripts/build_oto_order.py oto --price P` derive it).

   For SELLs:
   ```
   python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --json
   ```

   Exit 0 = approved. Exit 3 = refused. Exit 4 = broker state unavailable.

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
   OTO_JSON=$(python3 scripts/build_oto_order.py oto --symbol SYM --qty N --price P)
   ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$OTO_JSON"
   ```
   Gate before convert: filled_qty known AND filled_qty == qty, AND legs[]
   matches FixedStop (type=stop, trail null). If filled_qty != qty or residual
   shares uncovered: INCIDENT — hard-fail. Email/log; do NOT convert or assume
   protected (ADR 0002 / quant seal).

   SELL of a protected position — cancel-then-close (#38), never close-then-cancel:
   ```
   ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID
   ALPACA_RISK_OK=1 bash scripts/alpaca.sh close SYM
   ```

7. For BUYs, convert ONLY after the fill+leg gate above (cancel leg, confirm
   cancel, then place trailing — CONVERT_FIXED_TO_TRAIL_STEPS):

   ```
   python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
       --price P --trail-percent 10 --json
   ```

   On exit 0:
   ```
   ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel LEG_ORDER_ID
   TRAIL_JSON=$(python3 scripts/build_oto_order.py trail --symbol SYM --qty N --trail-percent 10)
   ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$TRAIL_JSON"
   ```
   If conversion fails after cancel: email loudly and retry the trail —
   briefly naked. Query before claiming protected: fixed leg still open =
   protected (queryable); neither fixed nor trail = incident. #40 still OPEN.

8. Log to memory/TRADE-LOG.md with full thesis, entry, stop, target, R:R.

9. `bash scripts/email.sh` with trade details.

Note: entry is atomic via OTO (ADR 0002). Conversion cancel→trail and sell
cancel→close still have brief windows; PATCH (#40) is OPEN and not invented here.
