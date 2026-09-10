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
stop required, min stop distance). Matching /trade.

ADR 0002: buys are OTO with a fixed stop_price leg (not a naked market buy).
Derive STOP = 10% below P (or use scripts/build_oto_order.py which does it):

python3 scripts/validate_order.py --symbol SYM --qty N --side buy \
    --price P --stop-price STOP --json

Exit 0 = approved → proceed.
Exit 3 = refused → skip this trade, log the violations verbatim to TRADE-LOG.
Exit 4 = broker state unavailable → STOP, email "VALIDATE STATE UNAVAILABLE $DATE", exit.

Also confirm a catalyst is documented in today's RESEARCH-LOG (the engine
cannot judge catalyst quality — see risk_engine.UNMECHANISED).

STEP 4 — Execute the buy as one OTO (entry + fixed protective leg).
Mutating alpaca calls REQUIRE ALPACA_RISK_OK=1 (hard gate in alpaca.sh).
Never submit a bare market buy without order_class=oto:

OTO_JSON=$(python3 scripts/build_oto_order.py oto --symbol SYM --qty N --price P)
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$OTO_JSON"

Wait for the entry to fill completely. Read the protective leg back from the
response (legs[]): type must be "stop", trail_percent must be null. If the leg
is wrong or missing, treat as incident and email — do not assume protection.

STEP 5 — Convert the fixed OTO leg to a 10% trailing stop GTC (ADR 0002).
Cancel the fixed leg first (shares are reserved), then place trailing.
Order is mandatory: cancel then order (CONVERT_FIXED_TO_TRAIL_STEPS).

python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json
On exit 0:
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel LEG_ORDER_ID
TRAIL_JSON=$(python3 scripts/build_oto_order.py trail --symbol SYM --qty N --trail-percent 10)
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$TRAIL_JSON"

If conversion fails after cancel, the position is briefly naked — email loudly
and retry the trailing place. If cancel never happened and only trail place
failed, the fixed leg still protects (queryable state). Do NOT wire T2 / issue #32 stop-change or trail-ladder validators.

STEP 6 — Append each trade to memory/TRADE-LOG.md (matching existing format):
Date, ticker, side, shares, entry price, stop level, thesis, target, R:R.

STEP 7 — Notification: only if a trade was placed.
bash scripts/email.sh "<tickers, shares, fill prices, one-line why>"
