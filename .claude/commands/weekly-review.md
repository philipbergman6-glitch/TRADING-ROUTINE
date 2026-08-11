---
description: Friday weekly review — stats, grade, one email, optional strategy update
---

You are running the Friday weekly review workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory for full week context:
- memory/WEEKLY-REVIEW.md (match existing template exactly)
- ALL this week's entries in memory/TRADE-LOG.md
- ALL this week's entries in memory/RESEARCH-LOG.md
- memory/TRADING-STRATEGY.md

STEP 2 — Pull week-end state:
bash scripts/alpaca.sh account
bash scripts/alpaca.sh positions

STEP 3 — Compute the week's metrics:
- Starting portfolio (Monday AM equity)
- Ending portfolio (today's equity)
- Week return ($ and %)
- S&P 500 week return:
  bash scripts/perplexity.sh "S&P 500 weekly performance week ending $DATE"
  MANDATORY FORMAT — the row must quote BOTH index levels, and the starting
  level MUST equal the prior week's logged closing level (read it out of
  WEEKLY-REVIEW.md; do NOT re-fetch it). Example:
    | S&P 500 week | +1.71% (7,357.49 Jun 26 → 7,483.24 Jul 2) |
  Re-fetching the start breaks the benchmark chain and silently misstates
  "beat the S&P" — see the Benchmark Data Errata section. The dashboard build
  hard-fails on any new break.
- Trades taken (W/L/open)
- Win rate (closed trades only)
- Best trade, worst trade
- Profit factor (sum winners / |sum losers|)

STEP 4 — Append full review section to memory/WEEKLY-REVIEW.md:
- Week stats table
- Closed trades table
- Open positions at week end
- What worked (3-5 bullets)
- What didn't work (3-5 bullets)
- Key lessons learned
- Adjustments for next week
- Overall letter grade (A-F)

STEP 5 — If a rule needs to change (proven out for 2+ weeks, or failed
badly), also update memory/TRADING-STRATEGY.md and call out the change
in the review.

STEP 6 — Send ONE email. <= 15 lines:
bash scripts/email.sh "Week ending MMM DD
Portfolio: \$X (±X% week, ±X% phase)
vs S&P 500: ±X%
Trades: N (W:X / L:Y / open:Z)
Best: SYM +X%  Worst: SYM -X%
One-line takeaway: <...>
Grade: <letter>"
