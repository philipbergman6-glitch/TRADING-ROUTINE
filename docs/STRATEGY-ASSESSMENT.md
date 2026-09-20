# Strategy and performance assessment

Date: 2026-09-19. Evidence: broker-reconciled results in
[research 0006](research/0006-paper-results-reconciliation.md). Scope: decide
what in the current approach deserves the owner's $10,000 before live execution
is built. This document changes no trading rule; proposed changes become
strategy v2 only when written into a versioned spec and run against v1.

## Verdict in one paragraph

The risk machinery works and should be kept. The selection engine does not
beat the benchmark and should be changed before any real money. Over 101
sessions the account returned +3.28% against +7.04% for SPY on identical dates,
with a −10.3% maximum drawdown against −4.5% for SPY. Two trades (AMD, MU) made
$9,820; the other thirteen lost $6,169. The single-name phase to June 30 beat
SPY by 2.8 pp; the sector-ETF phase since then trailed by 6.1 pp. Recommendation:
**do not fund yet**. Freeze the current rulebook as baseline v1, specify v2 with
the changes below, run both in paper at $10,000 scale with the execution
controls finished, and revisit the funding decision on a predeclared criterion.

## 1. Are the results trustworthy?

Yes for P&L, with stated gaps for the narrative.

- Broker fills, fees and the single deposit reconcile to the Sep 18 equity of
  $103,282.35 exactly: realized +$3,651.24, unrealized −$368.35, fees −$0.46.
- Every logged entry and exit exists at the broker at the logged quantity.
  Prices in the "reconstructed" May–June range match the broker within $0.05.
- The EOD log's equity differs from the broker's official close on 31 of 96
  overlapping days, usually by under $300 (snapshot before the close). The log's
  "phase high" of $115,135 was intraday; the highest broker close was $114,646
  on Jun 1. Use broker closes for any scoring.
- Five broker trading days have no EOD entry, and routine output for May 1 to
  Jun 10 was recovered from deleted branches. The narrative for that period is
  partial; the accounting is not.
- Seven 1–3 share F trades on Aug 11 were engineering tests in the scored
  account. They are excluded and must not recur.

## 2. Performance versus the S&P 500

| Metric | Bot | SPY |
|---|---|---|
| Return, Apr 27 close to Sep 18 close | +3.28% | +7.04% |
| Exposure-matched SPY (SPY scaled by the bot's daily invested fraction) | | +4.56% |
| Max drawdown | −10.32% | −4.46% |
| Sessions since last equity high | 77 | 0 |
| Daily volatility | 0.94% | 0.77% |
| Correlation of daily returns with SPY | 0.31 | |

The bot took more risk than SPY and earned less. Cash explains about 1.1 pp of
the gap (the return SPY earned on the shortfall below an 80% target). The
remaining ~2.6 pp is selection, concentrated in the ETF phase.

Weekly reviews graded 21 weeks: 14 of 21 underperformed the S&P, and every
week since Aug 28 has. Eight of those weekly benchmarks (May 1 to Jun 19) were
estimates with no index level in the log; the SPY figures in this document come
from daily bars and supersede them. The May outperformance is real. The reviews attributed the lag to a missing "leadership
single-name" for seven consecutive weeks without sourcing one, which is a
process finding in itself: the routine can diagnose but not act on a
discretionary sourcing task.

## 3. Strategy decisions versus operational failures

**Strategy decisions** (would have produced the same result with perfect
operations):

- Rotating the entire book into four equal-weight sector ETFs on Jun 25–30.
  From Jun 30 to Sep 18: XLB −2.1%, XLI −6.7% (stopped), XLP −1.1%, versus
  SPY +2.3%. This is the single largest cause of the lag.
- Re-entering names higher after a stop (AMD, PLTR, NVDA, XOM) cost 1.3% to
  3.5% per round trip in re-entry price alone.
- Entering NVDA and MSFT on Jun 3 into a falling tape; both were stopped
  within six sessions for −$3,509 combined.
- Tightening AMD's trail to 5% at +20%: exited at +29.8%; AMD rose another 28%
  in the next 20 sessions. The same rule protected PLTR and MU gains. Net
  effect unknown on this sample; it is a v2 test candidate, not a proven flaw.

**Operational failures** (results would differ with the same strategy and
correct operations):

- The mutating-order path was unusable Sep 8–16 (ledger config). No order was
  needed, so no loss occurred, but for five sessions the system could not cut a
  loser or renew an expiring stop. Fixed in PR #66; needs a test that proves
  protection does not depend on any optional component.
- State loss in May: the routine did not know AMD had exited and logged
  "stopped out or cut" ten days later. Decisions were made from stale memory.
- WMT: bought, then the entry condition was checked, then sold 60 seconds
  later. Validation must precede submission, always.
- Manual −7% cuts executed late (MSFT −8.1%) or were preempted by the trail on
  a gap (XLI −7.46%). The manual cut is a scheduled human-style check, not a
  resting order, so it structurally cannot fire at −7%.
- Protection coverage is only checked by `scripts/doctor.py`, which no routine
  runs. "Protection at all times" is enforced at entry and observed by the
  agent reading the order book; there is no independent monitor.
- Under-deployment for 46 of 98 sessions. Half was explicit patience
  (arguably a strategy decision); the July 23 to Aug 10 stretch, with a
  written deadline missed, was non-execution. Cost during that window alone:
  SPY +4.7% on the idle 40%.

Operational failures cost little money in this sample. They matter because
each is a mode in which real capital would sit unprotected or double-ordered.

## 4. Rule-by-rule recommendation

| # | Current rule | Evidence | Recommendation |
|---|---|---|---|
| 1 | No options | — | **Keep** |
| 2 | 75–85% deployed | Cash drag 1.1 pp; band was met only by buying ETFs | **Modify**: keep the band as a target, but define what fills it when there is no signal (see rule 12) |
| 3 | 5–6 positions, max 20% each | Never violated; concentration in 4×20% correlated ETFs was within the rule and still the main loss | **Keep**, add a correlation limit: at most two positions in the same sector, and sector ETFs count as their sector |
| 4 | 10% GTC protective stop at all times, OTO entry | Every position covered; worst single-trade loss −9.2%; stops absorbed the June and September stress without intervention | **Keep** as written |
| 5 | Cut losers at −7% manually | Fired late (−8.1%) or was preempted by the trail (−7.46%); redundant with the 10% trail on a drift | **Modify**: replace the manual check with a resting stop. v2 candidate: initial fixed stop at −7% converting to a 10% trail once the position is +5%. Score against v1 |
| 6 | Tighten trail to 7% at +15%, 5% at +20% | Helped PLTR and MU, cost AMD's largest run. The engine only checks a proposed change; nothing triggers it, and XOM peaked at +7.8% and exited at +0.5% because it never reached +15% | **Keep in v1**; v2 tests 7%/7% (no 5% step) and makes the tighten a triggered action |
| 7 | Stop never within 3%, never lowered | Never violated by an action. Violated as standing state now: XLB's renewed fixed stop of $48.78 sits 2.4% below the Sep 18 close of $49.99 and cannot ratchet | **Keep**, and monitor the standing condition, not only the change |
| 8 | Max 3 new trades per week | Bound only in weeks 1–2; 12 of 21 weeks had zero entries | **Keep** (harmless); the problem is too few qualifying entries, not too many |
| 9 | Follow sector momentum | As a filter for single names (May): +7.5% vs +4.7%. As the position itself (ETFs, Jul–Sep): −3.9% vs +2.3% | **Modify**: sector momentum is an entry filter, not a holding. Sector ETFs are not eligible as conviction positions |
| 10 | Exit a sector after 2 failed trades | Tech had three consecutive losers in June (NVDA, MSFT, AVGO); the rule was not invoked. The trade log has no sector field, so it cannot be computed | **Keep**, but record sector per trade and compute it from fills so it actually triggers |
| 11 | Patience > activity | Used to justify 0%–60% deployment for weeks; the reviews called it non-compliance | **Discontinue** as a rule. Replace with explicit conditions under which cash is acceptable (rule 12) |
| 12 | Deployment backstop: force a "leadership" add after 3 under-band sessions | Fired twice. XLK (Aug 10) +0.95% vs SPY −1.23% since; XLE (Sep 17) +0.59% vs +0.11%. Restored the band, but both adds were low-conviction ETFs chosen because something had to be bought | **Discontinue in this form**. Replace with a fallback: capital below the band with no qualifying signal is held in SPY, not cash and not a sector bet. Cash is acceptable only under a declared market-wide risk condition with a dated expiry |
| 13 | Cash only, never margin | Held | **Keep** |
| — | Entry checklist: catalyst, sector, stop, 2:1 target | No trade ever exited at target; every exit was a stop or a manual close | **Modify**: either make the target operative (trim one third at target) or delete it from the record |

Why the fallback is SPY rather than cash: the mission is to beat the S&P 500.
Idle cash guarantees underperformance in an up market and only helps in a
falling one; the fallback removes cash drag without forcing sector bets. It
also makes the exposure-matched benchmark and the passive benchmark converge,
so the scored alpha is the active sleeve's alone.

## 5. Investment universe (proposed v2)

- US-listed common stocks and ADRs with average dollar volume above $50M and
  price above $10, so a 20% position at $10,000 ($2,000) is at least 4 whole
  shares. No sector ETFs as conviction positions; SPY only as the fallback.
- Single-name gains came from AMD, MU, PLTR: liquid large caps with a specific
  catalyst and a sector tailwind. The May book is the template; the June book
  (chasing the same names higher after stops) is the anti-pattern. v2 adds a
  cooldown: no re-entry within 10 sessions of a stop-out in the same name.

## 6. What $10,000 changes

- Position size $2,000 at 20%. Whole-share rounding at prices up to ~$500 is
  under 25% of a position; prices above $1,000 (MU) are effectively excluded.
- Fees are immaterial (paper charged $0.46 on $2.4M traded; live commission at
  Alpaca is zero, regulatory fees scale with proceeds).
- Scaled to $10,000, this history's worst drawdown was $1,032 from the Jun 1
  peak and the equity never closed below the starting value. The $4,000
  tolerance would not have been approached; the proposed $1,000 review
  threshold on net loss from initial would not have fired, but a peak-to-trough
  rule at $1,000 would have, on Sep 16. Decide which definition applies
  before funding.
- Fixed operating cost is the dominant term at this size. The Sep 17 audit's
  illustration of $100 per month is a 12% annual hurdle on $10,000; the actual
  monthly spend on model, research and hosting is not recorded anywhere and
  must be before the funding decision.
- Slippage was not observable: paper fills at the quote, with partial fills
  simulated. At 5- to 30-share sizes live fills should be close, but this is
  the one thing paper cannot show and the pilot must measure.

## 7. Immediate actions regardless of the funding decision

- Decide whether XLB's fixed stop (2.4% below market) stays. Rule 7 forbids
  placing a stop inside 3%; it does not say what to do when price drifts into
  one. Options: leave it (a sector wiggle exits at an unintended level) or
  convert to a 10% trail (lowers the stop, which rule 7 also forbids). This is
  a rule gap to close in the spec.
- Record the actual monthly operating cost.
- Move engineering probes out of the scored account, or document the Aug 11
  F trades in the trade log as non-strategy orders.
- Rebuild the trade blotter from broker fills (the FIFO table in research 0006)
  and treat it as the record; the markdown stays as evidence.

## 8. Recommendation and decision criterion

1. **Freeze v1** as the baseline: the 13 rules above as written today, run in
   paper as a shadow (proposals scored, not necessarily executed).
2. **Specify v2**: rules 5, 9, 11, 12 and the checklist changed as above, plus
   the correlation limit and universe definition. Pin the strategy hash, prompt
   hash and model ID per `docs/PAPER-EXPERIMENT.md`.
3. **Finish execution controls first**: order idempotency, recovered exits,
   full broker lifecycle recording, and stop monitoring that runs without
   Claude and without the ledger.
4. **Run v2 in paper at $10,000** for the operational gate (30 clean
   sessions). Score v2 against SPY, exposure-matched SPY, and the v1 shadow.
5. **Funding criterion, stated now**: open a supervised pilot only if the
   30-session gate passes with zero unexplained reconciliation differences,
   and v2 is at or above exposure-matched SPY after costs over its segment.
   Thirty sessions cannot prove edge; they can prove the machinery and rule
   out obvious harm. The pilot's job is to measure live execution at small
   size, not to earn.

If the owner prefers to fund on the current rulebook regardless, the evidence
says to expect index-like risk with below-index return, and the loss tolerance
recorded in `docs/LIVE-READINESS.md` remains the outer bound.
