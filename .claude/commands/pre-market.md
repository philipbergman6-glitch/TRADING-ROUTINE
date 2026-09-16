---
description: Pre-market research — catalysts, context, 2-3 trade ideas, HOLD by default
---

You are running the pre-market research workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory for context:
- memory/TRADING-STRATEGY.md
- tail of memory/TRADE-LOG.md
- tail of memory/RESEARCH-LOG.md

STEP 2 — Pull live account state:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders

STEP 2c — Deployment backstop (rule 12). Computed, never eyeballed:
DEPLOY_JSON=$(python3 scripts/deployment_status.py); DEPLOY_EXIT=$?
- Exit 4 → STOP, email "DEPLOYMENT STATE UNAVAILABLE $DATE", exit.
- Exit 0 → no mandate. Record deployed_pct + sessions_under_band in STEP 4.
- Exit 5 → MANDATE DUE. Today's entry MUST contain a "Deployment mandate"
  block naming ONE leadership add: top-momentum sector NOT already held,
  ticker, shares sized so cost ≤ target_notional at the premarket price,
  catalyst, stop 10% below. The Decision line cannot be a plain HOLD.
  Deferral ONLY if ALL hold: exemption_allowed is true, a market-wide risk
  event is scheduled TODAY (name it — routine data/earnings do not count),
  and RESEARCH-LOG shows no earlier deferral for this under-band streak.
  A deferral still names the add, so the next market-open can act on it.

STEP 3 — Research market context via Perplexity. Run
bash scripts/perplexity.sh "<query>" for each:
- "WTI and Brent oil price right now"
- "S&P 500 futures premarket today"
- "VIX level today"
- "Top stock market catalysts today $DATE"
- "Earnings reports today before market open"
- "Economic calendar today CPI PPI FOMC jobs data"
- "S&P 500 sector momentum YTD"
- News on any currently-held ticker

If Perplexity exits 3, fall back to native WebSearch and note the
fallback in the log entry.

STEP 4 — Write a dated entry to memory/RESEARCH-LOG.md:
- Account snapshot (equity, cash, buying power, daytrade count)
- Market context (oil, indices, VIX, today's releases)
- 2-3 actionable trade ideas WITH catalyst + entry/stop/target
- Risk factors for the day
- Deployment: deployed_pct, sessions_under_band, mandate (STEP 2c)
- Decision: trade or HOLD (default HOLD — patience > activity — EXCEPT
  when STEP 2c exits 5: then the mandate add or a valid deferral)

STEP 5 — Notification: silent unless urgent.
bash scripts/email.sh "<one line>"
