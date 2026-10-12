# Trading Strategy

## Mission
Beat the S&P 500 over the challenge window. Stocks only — no options, ever.

## Capital & Constraints
- Starting capital: ~$100,000 (paper)
- Platform: Alpaca (paper trading)
- Instruments: Stocks ONLY
- Active strategy version: v1.3 (v1 engine rules per docs/STRATEGY-SPEC.md
  plus rule 14, in force since 2026-09-25, the rule 4/7 standing-stop
  wording of 2026-10-12 (ADR 0013), and the rule 10/12/14 definitions of
  2026-10-12; the STRATEGY_VERSION env var MUST
  match the major version and this file's sha256 MUST match its pin in
  docs/rulebook-pins.json — scripts/strategy_version.py checks both. Any edit
  to this file requires a version bump and a new pin; routines never edit it)
- PDT limit: does not exist. Alpaca removed `pattern_day_trader`,
  `daytrade_count`, `daytrading_buying_power` and `pdt_check` on 2026-07-06,
  after FINRA replaced Rule 4210's PDT framework with intraday margin. There is
  no day-trade count to read and no PDT rejection to handle. Do not re-derive
  the old $25k threshold — it is gone, not merely satisfied.

## Core Rules
1. NO OPTIONS — ever
2. 75-85% deployed
3. 5-6 positions at a time, max 20% each
4. Protection at all times: every open position carries a live GTC protective
   stop. At entry the stop is placed at the 10% distance (fixed leg 9.5–10.5%
   below entry, ADR 0002) and converted to a 10% trailing stop as soon as that
   conversion would not lower the stop. A fixed stop that is held or renewed
   because conversion would lower it is permitted protection, not a transient;
   it is converted the first session a 10% trail would sit at or above it. No
   stop is always a violation.
   Amended 2026-08-11 (ADR 0002): Alpaca cannot place a trailing stop as the
   protective leg of an atomic entry, so "trailing at all times" read literally
   was unimplementable and therefore unenforceable by the risk engine.
   Amended 2026-10-12 (ADR 0013): a floor-preserving held fixed stop is
   permitted protection.
5. Cut losers at -7% manually
6. Tighten trail: 7% at +15%, 5% at +20%
7. Never place or move a stop to within 3% of current price; never lower a
   stop. If price drifts to within 3% of a resting stop, leave it and record
   the condition each session it persists. Renewing an expiring stop at its
   current level or higher is never a violation of this rule.
8. Max 3 new trades per week
9. Follow sector momentum
10. Exit a sector after 2 consecutive failed trades. A failed trade is a
    closed FIFO round trip at a loss per the fill-based blotter. Exiting a
    sector means no NEW entry in it, its own sector ETF included (sector per
    memory/SECTORS.json); open positions stay on their stops and nothing is
    force-sold. The ban lifts 20 sessions after the second loss. Computed by
    scripts/blotter.py --sector-streaks. Defined 2026-10-12.
11. Patience > activity
12. Deployment backstop: if deployed capital is below the 75-85% band for 3
    consecutive sessions, the next market-open routine MUST add at least one
    leadership position toward the band. Patience does not override the
    deployment mandate beyond 3 sessions absent a market-wide risk event (not
    routine data/earnings). Added 2026-08-07 after 6+ weeks of under-deployment
    and a blown soft deadline; "patience" was masking non-compliance.
    Computed by scripts/deployment_status.py (EOD snapshots below 75%);
    one deferral max per under-band streak. Added 2026-09-17.
    The instrument of a mandated add is constrained by rule 14; rule 14
    never excuses the add itself. Added 2026-10-12.
13. Cash only, never margin: a buy may never cost more than settled `cash`.
    Margin buying power is not capital. The account is a margin account
    (`multiplier: 4`), so `buying_power` runs far above `equity` — on
    2026-08-11, $323,675 against $106,566 of equity and $21,075 of cash.
    Sizing reads `cash`; `buying_power` is never an input to any rule. Added
    2026-08-11 (issue #35) to give the engine's existing `SUFFICIENT_CASH`
    check a rule to mechanise — the guard was already in code with nothing in
    this file behind it, so swapping it to the more natural-looking
    `buying_power` field would have been an unremarkable refactor rather than a
    violation. Leverage became reachable when PDT was abolished; this is the
    only constraint that regime leaves behind.
14. Composition mandate — the next new position is a single name. While the
    book holds ZERO idiosyncratic single-name positions (i.e. every open
    position is a broad-sector/index ETF, or the book is empty), the next new
    position opened — whether discretionary or mandated by rule 12 — MUST
    be a single name that passes the full Entry Checklist. A further ETF may
    be opened only if no single name passes that checklist, and the specific
    reason must be written into the pre-market RESEARCH-LOG entry for that
    session. This constrains
    WHAT is bought, never WHETHER: it does not force a trade, does not override
    rule 11 (patience > activity), and lapses automatically the moment one
    single-name position is open. Added 2026-09-25 after eight consecutive
    weekly reviews named the missing idiosyncratic leader as the cause of the
    relative lag and five consecutive relative losses followed; the one entry
    in that span (XLE, 2026-09-17) was rule-12-forced and went to a sixth
    correlated ETF because nothing in this file said it could not. Same failure
    mode rule 12 was written to fix, in the composition dimension: a standing
    intention with no mechanism behind it.
    Rule 14 constrains WHAT a rule-12 add buys; it never excuses the add
    itself, and rule 12 never waives this rule. A broad ETF is a SPDR sector
    fund or an index tracker (SPY, QQQ, IWM, DIA, VTI and similar); anything
    else is a single name. Added 2026-10-12.

## Entry Checklist
- Specific catalyst?
- Sector in momentum?
- Stop level: 10% below entry (rule 4 band 9.5–10.5%)
- Target (min 2:1 R:R)
