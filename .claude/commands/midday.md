---
description: Midday scan — cut losers at -7%, tighten stops on winners, thesis check
---

You are running the midday scan workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory so you know what's open and why:
- memory/TRADING-STRATEGY.md (exit rules)
- tail of memory/TRADE-LOG.md (entries, original thesis per position, stops)
- today's memory/RESEARCH-LOG.md entry

STEP 2 — Pull current state:
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders

STEP 3 — Cut losers immediately. For every position where
unrealized_plpc <= -0.07, validate the sell through the risk engine first
(paper + position coherence). Do NOT skip validate_order:

python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --json

Exit 0 = approved → proceed.
Exit 3 = refused → log violations verbatim; do not close.
Exit 4 = broker state unavailable → STOP, email alert, exit.

On approve (mutating alpaca requires ALPACA_RISK_OK=1):
ALPACA_RISK_OK=1 bash scripts/alpaca.sh close SYM
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID   # cancel its trailing stop
Log the exit to TRADE-LOG: exit price, realized P&L, "cut at -7% per rule".

STEP 4 — Tighten trailing stops on winners. For each eligible position,
cancel old trailing stop, place new one. Ladder stays prose only
(do NOT wire stop-change / trail-ladder validators — T2 / issue #32):
- Up >= +20% -> trail_percent: "5"
- Up >= +15% -> trail_percent: "7"
Never tighten within 3% of current price. Never move a stop down.

Before cancel+replace, validate the replacement protective sell:
python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent T --json
On exit 0:
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order '{"symbol":"SYM","qty":"N","side":"sell","type":"trailing_stop","trail_percent":"T","time_in_force":"gtc"}'
On exit 3 → skip tighten, log violations. On exit 4 → STOP.

STEP 5 — Thesis check. If a thesis broke intraday, cut the position even
if not at -7% yet — same validate_order + ALPACA_RISK_OK close/cancel gate
as STEP 3. Document reasoning in TRADE-LOG.

STEP 6 — Optional intraday research via Perplexity if something is moving
sharply with no obvious cause. Append afternoon addendum to RESEARCH-LOG.

STEP 7 — Notification: only if action was taken.
bash scripts/email.sh "<action summary>"
