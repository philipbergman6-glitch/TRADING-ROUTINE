---
description: Market-open execution — validate, place buys, set 10% trailing stops
---

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

STEP 3 — Validate EVERY buy through the risk engine BEFORE placing it.
Do NOT hand-check sizing rules — the engine owns them (max positions,
max 20% size, max 3 trades/week, sufficient cash, 85% deployment ceiling,
stop required, min stop distance). Matching /trade:

python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
    --price P --trail-percent 10 --json

Exit 0 = approved → proceed.
Exit 3 = refused → skip this trade, log the violations verbatim to TRADE-LOG.
Exit 4 = broker state unavailable → STOP, email "VALIDATE STATE UNAVAILABLE $DATE", exit.

Also confirm a catalyst is documented in today's RESEARCH-LOG (the engine
cannot judge catalyst quality — see risk_engine.UNMECHANISED).

STEP 4 — Execute the buys only after STEP 3 approved (market, day TIF).
Mutating alpaca calls REQUIRE ALPACA_RISK_OK=1 (hard gate in alpaca.sh):
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"buy","type":"market","time_in_force":"day"}'
Wait for fill confirmation before placing the stop.

STEP 5 — Immediately place 10% trailing stop GTC for each new position.
Re-validate the protective sell (position must now exist), then submit:
python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json
On exit 0:
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"sell","type":"trailing_stop","trail_percent":"10","time_in_force":"gtc"}'

If the trailing stop is rejected, fall back to fixed stop 10% below entry
(re-validate with --stop-price first):
python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --stop-price X.XX --json
On exit 0:
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"sell","type":"stop","stop_price":"X.XX","time_in_force":"gtc"}'

If also blocked, note the stop in TRADE-LOG as "stop-blocked, set tomorrow AM"
and email loudly — unprotected position is an incident.

STEP 6 — Append each trade to memory/TRADE-LOG.md (matching existing format):
Date, ticker, side, shares, entry price, stop level, thesis, target, R:R.

STEP 7 — Notification: only if a trade was placed.
bash scripts/email.sh "<tickers, shares, fill prices, one-line why>"
