# Weekly Review

Friday reviews appended here.

Template for each entry:

## Week ending YYYY-MM-DD

### Stats
| Metric | Value |
|--------|-------|
| Starting portfolio | $X |
| Ending portfolio | $X |
| Week return | ±$X (±X%) |
| S&P 500 week | ±X% |
| Bot vs S&P | ±X% |
| Trades | N (W:X / L:Y / open:Z) |
| Win rate | X% |
| Best trade | SYM +X% |
| Worst trade | SYM -X% |
| Profit factor | X.XX |

### Closed Trades
| Ticker | Entry | Exit | P&L | Notes |

### Open Positions at Week End
| Ticker | Entry | Close | Unrealized | Stop |

### What Worked
- ...

### What Didn't Work
- ...

### Key Lessons
- ...

### Adjustments for Next Week
- ...

### Overall Grade: X

---

## Week ending 2026-06-05

### Stats
| Metric | Value |
|--------|-------|
| Starting portfolio | $111,880 (May 29 close) |
| Ending portfolio | $108,456 (Jun 5 latest) |
| Week return | -$3,424 (-3.06%) |
| S&P 500 week | -2.35% (7,580→7,402) |
| Bot vs S&P | -0.71% |
| Phase P&L | +$8,456 (+8.46%) vs S&P phase ~+11.3% |
| Trades | 5 (W:2 / L:1 / open:2) |
| Win rate | 67% (2/3 closed) |
| Best trade | MU +18.6% |
| Worst trade | AVGO -4.4% |
| Profit factor | 8.02 |

### Closed Trades
| Ticker | Entry | Exit | Shares | P&L | Notes |
|--------|-------|------|--------|-----|-------|
| PLTR | $136.96 | ~$150.90 | 152 | +$2,119 (+10.2%) | 7% trail triggered ~Jun 2-3; correct exit |
| MU | $853.58 | ~$1,012 | 25 | +$3,961 (+18.6%) | Gap-fill stop Jun 4; semi sector sympathy; locked gains |
| AVGO | $427.95 | ~$409 | 40 | -$758 (-4.4%) | Gap-fill stop Jun 4; AVGO earnings miss, AI forecast cut $62.5B→$55B |

### Open Positions at Week End
| Ticker | Entry | Close | Unrealized | Stop | Notes |
|--------|-------|-------|------------|------|-------|
| MSFT | $436.20 | $414.70 | -$1,032 (-4.9%) | $392.45 | Entered Jun 3; AI/Azure thesis intact |
| NVDA | $219.64 | $204.90 | -$1,326 (-6.7%) | $199.44 | ⚠️ $0.63 from -7% cut trigger ($204.27); watch Mon open |

**Deployment: $38,347 / $108,456 = 35.4% — far below 75-85% target**

### What Worked
- Trailing stop system executed automatically on both gap-down opens (MU, AVGO) — no emotion, rules ran cleanly
- MU locked in +18.6% before sector contagion erased more — 5% trail did its job
- PLTR trailed up to +10.2% and stopped out; entered at $136.96, exited $150.90
- Profit factor of 8.02 — winners swamped the one loser
- No options, no rule violations, no forced trades

### What Didn't Work
- AVGO held through Q2 earnings (AMC Jun 3); guidance cut -12% on AI forecast → -4.4% loss; earnings risk was identifiable
- NVDA re-entered Jun 3 just 2 days before NFP — entered into confirmed binary risk event; now -6.7% and barely above -7% cut
- MSFT also entered Jun 3 pre-NFP; -4.9% loss out of the gate
- Post-exit deployment crashed to 35.4%; no good setups Friday to rebuild
- Bot underperforming S&P over full phase: +8.46% vs ~+11.3%

### Key Lessons
- Never open new positions within 48h of scheduled high-impact macro (NFP, CPI, FOMC) — both Jun 3 entries are now underwater because of Jun 5 NFP
- Trailing stop system works — let it run; MU (+18.6%) and PLTR (+10.2%) prove this
- Earnings risk on existing positions: when a position is near stop and has an earnings event, consider tightening to 5% trail 2 days prior
- Under-deployment after stops is a structural drag; need a playbook to rotate faster into Energy/Staples setups

### Adjustments for Next Week
- **NVDA critical:** -7% cut trigger at $204.27; current $204.90; cut manually at open Monday if it opens below $204.27
- Rebuild to 75-85% deployment with 2-3 new positions; prioritize sectors not exposed to semi selloff
- Energy (XOM/CVX) and diversifiers (META, GOOGL) scouted in Jun 4 pre-market — review after NFP digestion Mon AM
- Enforce: no new entries Wed-Thu before Friday NFP (or within 48h of any Tier-1 macro event)
- FOMC Jun 16-17 approaching — factor into trade timing next week

### Overall Grade: C+
Phase behind benchmark (-2.84%). Week -3.06% vs S&P -2.35%. Risk management working correctly (stops, no rule breaks), but entry timing poor and deployment too low.
