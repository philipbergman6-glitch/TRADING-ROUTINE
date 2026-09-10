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

On approve (mutating alpaca requires ALPACA_RISK_OK=1).
Order is mandatory cancel-then-close (#38 / CUT_LOSER_STEPS): close alone
403s while reserved, and close-then-cancel leaves the loser held AND naked.
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID   # release reserved shares
ALPACA_RISK_OK=1 bash scripts/alpaca.sh close SYM
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
On exit 0 (TRAIL_TIGHTEN_STEPS = cancel then order — never reverse):
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID
TRAIL_JSON=$(python3 scripts/build_oto_order.py trail --symbol SYM --qty N --trail-percent T)
ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$TRAIL_JSON"
On exit 3 → skip tighten, log violations. On exit 4 → STOP.
#40 PATCH resize is OPEN — do not invent a patch path; cancel→replace still
has a brief naked window. Do NOT wire T2 / issue #32 stop-change validators.

STEP 5 — Thesis check. If a thesis broke intraday, cut the position even
if not at -7% yet — same validate_order + ALPACA_RISK_OK cancel-then-close gate
as STEP 3. Document reasoning in TRADE-LOG.

STEP 6 — Optional intraday research via Perplexity if something is moving
sharply with no obvious cause. Append afternoon addendum to RESEARCH-LOG.

STEP 7 — Notification: only if action was taken.
bash scripts/email.sh "<action summary>"
