# Trading Strategy

## Mission
Beat the S&P 500 over the challenge window. Stocks only — no options, ever.

## Capital & Constraints
- Starting capital: ~$100,000 (paper)
- Platform: Alpaca (paper trading)
- Instruments: Stocks ONLY
- PDT limit: does not exist. Alpaca removed `pattern_day_trader`,
  `daytrade_count`, `daytrading_buying_power` and `pdt_check` on 2026-07-06,
  after FINRA replaced Rule 4210's PDT framework with intraday margin. There is
  no day-trade count to read and no PDT rejection to handle. Do not re-derive
  the old $25k threshold — it is gone, not merely satisfied.

## Core Rules
1. NO OPTIONS — ever
2. 75-85% deployed
3. 5-6 positions at a time, max 20% each
4. 10% trailing stop on every position as a real GTC order
5. Cut losers at -7% manually
6. Tighten trail: 7% at +15%, 5% at +20%
7. Never within 3% of current price; never move a stop down
8. Max 3 new trades per week
9. Follow sector momentum
10. Exit a sector after 2 consecutive failed trades
11. Patience > activity
12. Deployment backstop: if deployed capital is below the 75-85% band for 3
    consecutive sessions, the next market-open routine MUST add at least one
    leadership position toward the band. Patience does not override the
    deployment mandate beyond 3 sessions absent a market-wide risk event (not
    routine data/earnings). Added 2026-08-07 after 6+ weeks of under-deployment
    and a blown soft deadline; "patience" was masking non-compliance.
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

## Entry Checklist
- Specific catalyst?
- Sector in momentum?
- Stop level (7-10% below entry)
- Target (min 2:1 R:R)
