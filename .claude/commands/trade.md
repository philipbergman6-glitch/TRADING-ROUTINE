---
description: Manual trade helper with strategy-rule validation. Usage — /trade SYMBOL SHARES buy|sell
---

Execute a manual trade. The risk engine decides whether it is allowed — you do
not re-derive the rules yourself, and you do not overrule it.

Args: SYMBOL SHARES SIDE (buy or sell). If missing, ask.

1. Pull the quote to get the ask price P:
   `bash scripts/alpaca.sh quote SYMBOL`

2. Validate through the risk engine. This is mandatory and it reads live
   account state itself — do not hand-check the rules:

   ```
   python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
       --price P --trail-percent 10 --json
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

5. Print the order JSON and the validation verdict, then ask "execute? (y/n)".

6. On confirm:
   `bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"buy|sell","type":"market","time_in_force":"day"}'`

7. For BUYs, immediately place the 10% trailing stop GTC:
   `bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"sell","type":"trailing_stop","trail_percent":"10","time_in_force":"gtc"}'`
   If the stop fails to place, say so loudly — the position is unprotected and
   that is an incident, not a footnote.

8. Log to memory/TRADE-LOG.md with full thesis, entry, stop, target, R:R.

9. `bash scripts/email.sh` with trade details.

Note: steps 6–7 are still two calls, so a partial failure between them leaves an
unprotected position. That gap is known and tracked — see ARCHITECTURE.md.
