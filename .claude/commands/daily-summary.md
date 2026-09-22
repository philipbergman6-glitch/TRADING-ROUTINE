---
description: End-of-day summary — P&L math, EOD snapshot to trade log, one email
---

You are running the daily summary workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory for continuity:
- tail of memory/TRADE-LOG.md (find most recent EOD snapshot -> yesterday's
  equity, needed for Day P&L)
- TRADE-LOG entries dated today are the NARRATIVE only; the trade list and
  counts come from broker fills in STEP 2.

STEP 2 — Pull final state of the day:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders
python3 scripts/blotter.py --check    # exit 4 = fills and positions disagree → STOP, email "BLOTTER MISMATCH $DATE"
python3 scripts/blotter.py --json     # round_trips[] + open_lots[]; fills are the record

STEP 3 — Compute metrics:
- Day P&L ($ and %) = today_equity - yesterday_equity
- Phase cumulative P&L ($ and %) = today_equity - starting_equity
- Trades today: from blotter --json, every open_lot or round_trip with
  `entered` today (buys) plus every round_trip with `exited` today (sells,
  with realized pnl/pnl_pct). "none" only if the blotter shows none.
- Trades this week (3/week cap): count of lots/trips with `entered` Mon..today.
  If TRADE-LOG disagrees with the blotter, the blotter wins — say so in Notes.

STEP 4 — Append EOD snapshot to memory/TRADE-LOG.md:

### MMM DD — EOD Snapshot (Day N, Weekday)
**Portfolio:** $X | **Cash:** $X (X%) | **Day P&L:** ±$X (±X%) | **Phase P&L:** ±$X (±X%)

| Ticker | Shares | Entry | Close | Day Chg | Unrealized P&L | Stop |

**Notes:** one-paragraph plain-english summary.

STEP 5 — Send ONE email (always, even on no-trade days). <= 15 lines:
bash scripts/email.sh "EOD MMM DD
Portfolio: \$X (±X% day, ±X% phase)
Cash: \$X
Trades today: <list or none>
Open positions:
  SYM ±X.X% (stop \$X.XX)
Tomorrow: <one-line plan>"
