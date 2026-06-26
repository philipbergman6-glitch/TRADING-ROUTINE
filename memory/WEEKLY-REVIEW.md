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

## Week ending 2026-06-12

### Stats
| Metric | Value |
|--------|-------|
| Starting portfolio | $108,650.28 (Mon Jun 08 close, derived — Mon AM not logged) |
| Ending portfolio | $106,856.01 |
| Week return | -$1,794.27 (-1.65%) |
| S&P 500 week | +0.7% |
| Bot vs S&P | -2.4% |
| Trades | 3 (W:0 / L:2 / open:1) |
| Win rate | 0% |
| Best trade | MSFT -8.1% (no winners; least-bad closed) |
| Worst trade | NVDA -9.4% |
| Profit factor | 0.00 |

### Closed Trades
| Ticker | Entry | Exit | P&L | Notes |
|--------|-------|------|-----|-------|
| MSFT | $436.20 | ~$401 | ~-$1,690 (-8.1%) | 10% trailing stop triggered Jun 09; exited past -7% cut level |
| NVDA | $219.64 | ~$199 | ~-$1,857 (-9.4%) | 10% trailing stop triggered Jun 09; exited past -7% cut level |

### Open Positions at Week End
| Ticker | Entry | Close | Unrealized | Stop |
|--------|-------|-------|------------|------|
| XOM | $150.14 | $146.98 | -$448.72 (-2.11%) | $137.24 (10% trail, HWM $152.49) |

### What Worked
- GTC trailing stops did their job — capped MSFT/NVDA losses without manual intervention when tech rolled over.
- Friday discipline: held 2 unused trade slots rather than forcing entries into hot CPI (4.2%) + hot PPI (6.5%) + VIX 22 + live FOMC next week.
- Sector rotation read: exited stalled AI-tech, pivoted to energy (XOM) per rule 9.
- Daily research caught the macro turn early (Jun 09 pre-market flagged CPI as binary; didn't add risk into it).

### What Didn't Work
- Both closed trades exited at -8.1% and -9.4% — past the -7% manual cut line. The cut rule wasn't executed intraday; the wider trail did the exit instead.
- Under-deployed all week (0% → 19.5% vs 75-85% target). Cash drag is its own risk vs the benchmark.
- Tech re-entry (MSFT/NVDA Jun 3) was into fading catalysts (post-Build, post-RTX Spark) — paid for it Jun 09.
- XOM entry caught an oil pullback immediately; -2.1% after three sessions, thesis intact but timing soft.

### Key Lessons
- The -7% manual cut must fire BEFORE the 10% trail does — monitor intraday, don't wait for EOD. Cost of inaction this week: ~1.5-2.4% extra slippage per position.
- Entering on faded catalysts is not "sector momentum" — require a forward catalyst, not a recent one.
- Hot-inflation regime + VIX > 20 = wider stops get hit more; sizing/holding through binary macro weeks needs more caution.

### Adjustments for Next Week
- FOMC Jun 16-17: no new entries before the decision. Re-engage Jun 18+ with the scout list (GOOGL/META comm-svcs, energy adds).
- Post-FOMC priority: rebuild to 75-85% deployed with 2-3 quality setups (3 weekly slots available).
- Enforce -7% cut at midday scan, every session, mechanically.
- Manage XOM by rules: manual cut $139.63, trail $137.24.

### Overall Grade: C-

No strategy rule changes — failures were execution (late -7% cuts) and timing, not rule design. Flagging for watch: if -7% cuts are missed again next week, add an explicit intraday cut-check rule to TRADING-STRATEGY.md.

---

## Week ending 2026-06-19

### Stats
| Metric | Value |
|--------|-------|
| Starting portfolio | $106,860.27 (Mon Jun 15 AM = Fri Jun 12 close) |
| Ending portfolio | $106,111.89 |
| Week return | -$748.38 (-0.70%) |
| S&P 500 week | +0.93% (7,431.46 → 7,500.58, Fri Jun 12 → Thu Jun 18 close; Fri holiday) |
| Bot vs S&P | -1.63% |
| Trades | 1 (W:0 / L:1 / open:0) |
| Win rate | 0% |
| Best trade | none (only XOM closed) |
| Worst trade | XOM -5.60% |
| Profit factor | 0.00 |

### Closed Trades
| Ticker | Entry | Exit | P&L | Notes |
|--------|-------|------|-----|-------|
| XOM | $150.14 | $141.74 | -$1,192.80 (-5.60%) | Thesis-break cut Jun 15 — US-Iran peace deal removed Hormuz oil premium; cut before -7% trigger |

### Open Positions at Week End
| Ticker | Entry | Close | Unrealized | Stop |
|--------|-------|-------|------------|------|
| — | — | — | 100% cash | — |

### What Worked
- Thesis-break discipline: cut XOM at -5.60% on the US-Iran peace deal (structural removal of the oil premium), before the -7% line — last week's flagged failure (late cuts) was not repeated.
- FOMC patience was vindicated: held 100% cash through Jun 16-17; the hawkish Warsh debut (9/18 projecting a 2026 hike) sent S&P -1.2% on Jun 17 — sitting out the binary saved real drawdown.
- Capital preserved through a regime shift (easing → tightening bias) with zero new risk taken into it.

### What Didn't Work
- 100% cash ALL week — 0% deployed vs 75-85% target for five straight sessions. Pure cash drag; lagged S&P by 1.63% doing nothing.
- The post-FOMC GOOGL/CAT deployment plan never fired (Jun 18 nor staged for Jun 22) — "patience" curdled into paralysis once the binary had passed.
- Down week (-0.70%) in an up market (+0.93%) — the only P&L event was a realized loss (XOM) with no offsetting positions working.

### Key Lessons
- Patience into a binary (FOMC) is correct; staying flat AFTER the binary clears is just under-deployment. The two must be separated — once the event passes, re-engagement is the job, not more waiting.
- A thesis-break cut is now executing cleanly (XOM) — that muscle is built. The deficit has shifted entirely from exits to entries.
- Three consecutive weeks under deployment target is a pattern, not a blip. Cash-heavy "discipline" is itself a benchmark risk when the tape grinds higher.

### Adjustments for Next Week
- Monday Jun 22: decisive deployment is the #1 priority — rebuild from 0% toward 75-85% with 2-3 quality setups. CAT (industrials, raised FY26 guide, low rate-sensitivity) is PRIMARY; GOOGL downgraded pending the ~$80-85B financing/dilution overhang.
- Favor industrials/materials (less rate-sensitive) over mega-tech/semis given the hawkish tightening bias; require a forward catalyst, not a faded one.
- Set a hard deployment floor mindset: if a setup clears the entry checklist, take it — do not let "wait one more day" recur a fourth week.
- 3 weekly trade slots open. Keep ≤20% per name; 10% trailing GTC on every entry.

### Overall Grade: C-

No strategy rule changes. Risk discipline (XOM thesis-break cut, FOMC patience) was textbook; the failure is chronic under-deployment — an execution gap, not a rule-design gap. Forcing entries into a hawkish regime shift on triple-witching would have been the wrong fix. Flagging for watch: if deployment is still at/near 0% by Wed Jun 24 after a green-enough tape, that is a discipline failure to correct — not a rules problem to legislate.

---

## Week ending 2026-06-26

### Stats
| Metric | Value |
|--------|-------|
| Starting portfolio | $106,111.89 (Mon Jun 22 AM = prior-week carry, 100% cash) |
| Ending portfolio | $106,039.11 |
| Week return | -$72.78 (-0.07%) |
| S&P 500 week | -1.91% (7,500.58 Jun 18 → 7,357.49 Jun 26; Jun 19 holiday) |
| Bot vs S&P | +1.84% |
| Trades | 2 (W:0 / L:0 / open:2) |
| Win rate | n/a (no closed trades) |
| Best trade | GOOGL +0.43% (open, unrealized) |
| Worst trade | XLF -0.77% (open, unrealized) |
| Profit factor | n/a (no closed trades) |

### Closed Trades
| Ticker | Entry | Exit | P&L | Notes |
|--------|-------|------|-----|-------|
| — | — | — | — | None closed this week |

### Open Positions at Week End
| Ticker | Entry | Close | Unrealized | Stop |
|--------|-------|-------|------------|------|
| GOOGL | $336.36 | $337.80 | +$89.28 (+0.43%) | $311.72 (10% trail GTC, hwm $346.36) |
| XLF | $53.97 | $53.55 | -$162.05 (-0.77%) | $49.21 (10% trail GTC, hwm $54.68) |

### What Worked
- Idle streak finally broken: after 6 straight 100%-cash sessions (Jun 16–24), the market-open routine fired Jun 25 and both GOOGL + XLF filled, each with a 10% trailing GTC stop attached on entry.
- Beat the benchmark: bot -0.07% vs S&P -1.91% (+1.84% relative) — sitting ~60% cash through a down week (S&P -1.44% on Jun 23) cushioned the book.
- Bad-R:R discipline held: CAT deferred all week (ask far above ~$935 Street PT — never buy above target); NEM/GDX dropped when gold broke <$4,000. No chased or forced entries.
- Patience through binaries paid: held cash across MU earnings (Jun 24) + Core PCE (Jun 25). PCE printed in-line at 3.4%, and the pre-staged GOOGL/XLF entry executed cleanly post-print.

### What Didn't Work
- Still under-deployed: 39.4% vs the 75-85% target. The "outperformance" was cash drag breaking our way in a down tape — it would have been lag in an up week. Not a repeatable edge.
- Deployment didn't land until Jun 25, the 7th flagged session. Five "non-negotiable" deployment notes logged before a single buy hit — plan-to-execution gap persisted most of the week.
- Only 2/3 weekly trades used; 3rd held in reserve, so the deployment gap rolls into next week.
- XLF thesis softened on entry day: by Jun 26 the rotation read flipped financials from "+28.8% YTD leader" to "lagging / losing relative edge." Bought a name whose sector leadership was already fading.

### Key Lessons
- The under-deployment that lagged the S&P the prior 3 weeks only helped this week because the tape fell — luck, not skill. The fix remains disciplined deployment toward 75-85%, not cash-timing the market.
- Sector momentum can flip within a single week (XLF: leader → laggard). Re-confirm the sector thesis at the moment of entry; size laggard-sector names smaller or skip them.
- The execution chain (plan → market-open fill) is the bottleneck, not research. The routine that fired Jun 25 must keep firing — verify orders actually land instead of re-logging the same overdue note.

### Adjustments for Next Week
- Deploy the 3rd weekly trade and build toward 75-85%: favor the new leader Industrials (XLI) over adding the softening XLF; GOOGL already at the 20% cap.
- Reassess XLF relative strength: if financials confirm lagging and XLF drifts toward its stop / -7% cut, exit and rotate into Industrials.
- Keep ≤20% per name; 10% trailing GTC on every entry; enforce the -7% manual cut at midday.
- VIX closed Jun 26 ~20 — require tape confirmation (S&P green/flat, VIX easing) before adding into a >20 vol regime. Next majors all July (jobs Jul 2/6, CPI Jul 14, FOMC).

### Overall Grade: C+

A step up from the prior two C- weeks: capital was finally deployed, risk rules were clean (stops on entry, no bad-R:R chases, patience through two binaries), and the book beat the S&P. But the relative win was mostly cash-drag luck in a down tape, not deployed alpha, and chronic under-deployment plus late execution persist. No strategy rule changes — the deficit is execution/deployment cadence, not rule design. The standing Jun 24 deployment flag was technically hit (0% through Wed) but corrected Thu Jun 25; keep the routine firing and close the deployment gap next week.
