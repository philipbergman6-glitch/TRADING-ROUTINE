# 0006 — Paper results reconciled against the broker (2026-04-27 to 2026-09-18)

Date: 2026-09-19. Read-only pull from the Alpaca paper account (account
created 2026-04-17, one $100,000 JNLC deposit). Sources: `/v2/account`,
`/v2/positions`, `/v2/orders?status=all` (58 orders, paged), `/v2/account/activities`
(104 FILL, 24 FEE, 1 JNLC), `/v2/account/portfolio/history` (1D), and IEX daily
bars for SPY and every traded symbol. Broker data is the record; the markdown
logs are the narrative. Where they differ, the difference is reported, not
overwritten.

## Reconciliation

| Item | Value | Note |
|---|---|---|
| Equity 2026-09-18 close | $103,282.35 | `/v2/account` `last_equity`, equals the EOD log |
| Realized P&L, FIFO from fills | +$3,651.24 | 15 round trips, excluding the F test trades |
| Unrealized P&L, open positions | −$368.35 | XLB, XLE, XLK, XLP |
| Fees (TAF, CAT, REG) | −$0.46 | Paper account charges no commission |
| Sum | +$3,282.43 | Equity − $100,000 = $3,282.35. Reconciled to the cent (rounding) |

Cross-checks:

- All 19 entries and 15 exits in the log exist as broker fills at the logged
  quantities. The XLB buy was a 415-share market order that filled 412 and was
  canceled for the remaining 3; the log correctly records 412.
- Fill prices in the "reconstructed" May 1 to Jun 10 range match the broker
  within $0.05 on every exit checked (AMD $408.93, PLTR $132.33, MU $1,013.36,
  AVGO $410.09). The provenance warning in `memory/TRADE-LOG.md` can be relaxed
  for prices; the missing-day gaps remain.
- EOD log equity vs broker daily close: 96 days overlap; 65 agree within $30,
  31 differ by more. Most differences are under $300 and consistent with the
  snapshot being taken shortly before the official close. Largest: log
  $115,135.09 on Jun 2 vs broker $113,362.76 (the log's "phase high" was
  taken intraday; the broker peak close was $114,645.67 on Jun 1). May 4 log
  equals the broker's May 1 close (a one-day shift in that recovered entry).
- Broker trading days with no EOD log entry: Apr 28, Apr 29, May 11, Jun 15,
  Jun 16. Recovered range May 1 to Jun 10 has additional runs that wrote to
  deleted branches and were spliced back.
- Portfolio-history timestamps are midnight UTC and hold the previous session's
  close; the series was shifted one day before comparison.
- Seven F fills on 2026-08-11 (1 to 3 shares, net −$0.08) are engineering tests
  of the OTO entry path (ADR 0002) executed in the trading account. They are
  excluded from trade statistics and should not recur in a scored account.

## Performance, identical dates

Baseline $100,000 at the 2026-04-27 close (first fills 2026-04-28 09:30 ET).
Benchmark: SPY IEX close, total-return adjustment applied by the data API
(`adjustment=all`); dividends are not reinvested in the paper account either.

| Metric | Bot | SPY |
|---|---|---|
| Total return to 2026-09-18 | +3.28% | +7.04% |
| Relative | −3.75 pp | |
| Max drawdown (daily closes) | −10.32% (peak Jun 1 $114,645.67, trough Sep 16 $102,827.45) | −4.46% (Jun 2 to Jun 10) |
| Days without a new equity high | Jun 1 to Sep 18, 77 sessions | |
| Worst rolling 20-session return | −6.28% (ending Jun 30) | |
| Daily volatility | 0.94% | 0.77% |
| Daily correlation with SPY | 0.31 | |
| Average invested fraction (EOD log) | 62% (median 77%) | 100% |
| Exposure-matched SPY (SPY × prior-day invested fraction) | | +4.56% |

Monthly, chained from broker closes:

| Month | Bot | SPY | Cum bot | Cum SPY |
|---|---|---|---|---|
| Apr 27 to 30 | +1.18% | +0.45% | +1.18% | +0.45% |
| May | +10.57% | +5.28% | +11.88% | +5.76% |
| Jun | −3.96% | −1.03% | +7.45% | +4.67% |
| Jul | −2.26% | +0.02% | +5.02% | +4.69% |
| Aug | +0.21% | +2.69% | +5.23% | +7.51% |
| Sep 1 to 18 | −1.85% | −0.44% | +3.28% | +7.04% |

Two regimes:

| Segment | Book | Bot | SPY |
|---|---|---|---|
| Apr 27 to Jun 30 | Single names (AMD, NVDA, PLTR, XOM, MU, AVGO, MSFT, GOOGL) | +7.45% | +4.67% |
| Jun 30 to Sep 18 | Sector ETFs (XLB, XLI, XLP, XLK, XLE) plus GOOGL to Jul 23 | −3.88% | +2.26% |

## Closed trades (broker FIFO)

| Sym | In | Out | Days | Qty | Avg in | Avg out | P&L $ | P&L % | Exit |
|---|---|---|---|---|---|---|---|---|---|
| PLTR | 04-28 | 05-06 | 8 | 142 | 142.30 | 132.33 | −1,415.78 | −7.01 | trail 10% |
| AMD | 04-28 | 05-06 | 8 | 62 | 314.97 | 408.93 | +5,825.49 | +29.83 | trail 5% (tightened) |
| AMD | 05-07 | 05-18 | 11 | 49 | 414.16 | 421.44 | +356.86 | +1.76 | trail 10% |
| WMT | 05-21 | 05-21 | 0 | 175 | 122.44 | 122.38 | −11.43 | −0.05 | market, same minute |
| NVDA | 04-28 | 05-26 | 28 | 90 | 208.64 | 212.71 | +366.30 | +1.95 | trail 10% |
| XOM | 05-07 | 05-27 | 20 | 140 | 145.94 | 146.62 | +95.21 | +0.47 | trail 10% |
| PLTR | 05-07 | 06-02 | 26 | 152 | 136.96 | 152.21 | +2,317.64 | +11.13 | trail 7% (tightened) |
| AVGO | 05-27 | 06-04 | 8 | 40 | 427.95 | 410.09 | −714.57 | −4.17 | trail 10% |
| MU | 05-26 | 06-04 | 9 | 25 | 853.58 | 1,013.36 | +3,994.50 | +18.72 | trail 5% (tightened) |
| NVDA | 06-03 | 06-09 | 6 | 90 | 219.64 | 199.37 | −1,823.96 | −9.23 | trail 10% |
| MSFT | 06-03 | 06-09 | 6 | 48 | 436.20 | 401.09 | −1,685.28 | −8.05 | market (manual cut at −8.1%) |
| XOM | 06-10 | 06-15 | 5 | 142 | 150.14 | 141.74 | −1,192.80 | −5.59 | market (thesis break) |
| XLF | 06-25 | 06-29 | 4 | 390 | 53.97 | 53.83 | −52.85 | −0.25 | market (rotation) |
| GOOGL | 06-25 | 07-23 | 28 | 62 | 336.36 | 322.93 | −832.73 | −3.99 | trail 10% |
| XLI | 06-29 | 09-14 | 77 | 116 | 182.16 | 168.58 | −1,575.36 | −7.46 | trail 10% |

Stats: 15 trades, 6 winners (40%), gross wins $12,956, gross losses $9,305,
profit factor 1.39, average win $2,159, average loss $1,034. AMD and MU
together earned $9,820; the other 13 trades net −$6,169.

Entries by ISO week: 3, 3, 0, 1, 2, 2, 1, 0, 2, 3, then 0, 0, 0, 0, 0, 1, 0,
0, 0, 0, 1 (Jul 6 to Sep 18). Twelve of 21 weeks had no new entry. The
3-per-week cap bound only in the first two weeks.

## What exited names did afterwards

| Sym | Exit | +5 sessions | +20 sessions | To Sep 18 |
|---|---|---|---|---|
| PLTR | 05-06 @132.33 | −1.7% | +7.1% | +34.1% |
| AMD | 05-06 @408.93 | +8.9% | +27.9% | +36.9% |
| AMD | 05-18 @421.44 | +19.6% | +20.4% | +32.8% |
| NVDA | 05-26 @212.71 | +4.5% | −6.6% | +4.4% |
| XOM | 05-27 @146.62 | +3.5% | −6.9% | +11.3% |
| PLTR | 06-02 @152.21 | −13.2% | −17.4% | +16.6% |
| AVGO | 06-04 @410.09 | −6.3% | −8.8% | −12.8% |
| MU | 06-04 @1,013.36 | −1.7% | −3.1% | +0.2% |
| NVDA | 06-09 @199.37 | +3.9% | +1.6% | +11.4% |
| MSFT | 06-09 @401.09 | −2.0% | −4.4% | +22.9% |
| XOM | 06-15 @141.74 | −2.0% | +1.3% | +15.1% |
| XLF | 06-29 @53.83 | +4.1% | +7.0% | +3.8% |
| GOOGL | 07-23 @322.93 | +3.3% | +5.4% | +8.1% |
| XLI | 09-14 @168.58 | +0.7% | +0.7% | +0.7% |

Tightened trails (AMD 5%, PLTR 7%, MU 5%) fired at +29.8%, +11.1%, +18.7%.
PLTR and MU then fell (tightening helped); AMD kept rising 28% in 20 sessions
(tightening cost the largest winner). Re-entries after a stop paid more than the
exit price every time: AMD +1.3%, PLTR +3.5%, NVDA +3.3%, XOM +2.4%.

## Cash drag

46 of 98 logged sessions closed below 75% invested. Applying the shortfall from
an 80% target to SPY's daily return, the forgone return is 1.11% of equity over
the period (positive in every month but June, when cash helped by 1.06%).
This is smaller than the 3.75 pp gap to SPY: most of the gap is selection in
the ETF phase, not cash.

## Protection coverage from broker timestamps

- Every entry received a GTC protective order. Latency from last fill to stop
  creation: 9 to 12 minutes on Apr 28 (first day), 1 to 4 minutes for later
  manual placements, 0 to 1 minute for the OTO path (XLE, Sep 17).
- Stop replacements (tightening or renewal) were cancel-then-place with gaps of
  3 to 8 seconds; no position was left uncovered across a session boundary.
- Two GTC stops (XLB, XLP) were renewed on Sep 16 as fixed stops nine and
  twelve days before their 90-day expiry. The prior three months had no expiry
  event because no position was held that long until XLI/XLB/XLP.
- Open protection at Sep 18: XLB fixed $48.78, XLP fixed $79.91, XLK trail 10%
  ($172.575), XLE trail 10% ($58.275). All four positions covered; no excess
  or missing quantity.

## Operational events, dated

| Date | Event | Class |
|---|---|---|
| Apr 28 | Stops placed 9 to 12 min after fills | Protection latency |
| May 1 to Jun 10 | Routine output written to per-session branches later deleted; recovered Aug 12 | Record loss |
| May 18 to 20 | Log states "AMD exited sometime since Apr 30 (stopped out or cut)"; the bot did not know its own May 6 and May 18 exits | State loss |
| May 21 | WMT bought then sold 60 s later after the gap-up condition was checked post-fill | Order before validation |
| Jun 9 | MSFT manual cut executed at −8.1% against a −7% rule; NVDA trail hit the same session at −9.2% | Cut latency |
| Jun 10 to 25 | Deployment 0% to 19.5% for eleven sessions | Under-deployment |
| Jul 23 to Aug 10 | Deployment ~60% for twelve sessions; explicit Aug 5 deadline missed | Under-deployment |
| Aug 11 | F test trades in the scored account | Test contamination |
| Sep 8 to 16 | `DATABASE_URL` unset and psycopg missing; every mutating order path failed closed | Execution path down |
| Sep 14 | XLI trail filled at −7.46% before any midday cut could act | Trail/cut convergence |

None of these caused a loss beyond the WMT scratch and the extra ~1.1 pp on
MSFT. The exposure they reveal is different: for five sessions in September the
system could not have cut a loser or renewed an expiring stop.
