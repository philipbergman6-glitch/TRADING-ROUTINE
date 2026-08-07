# Trading Strategy

## Mission
Beat the S&P 500 over the challenge window. Stocks only — no options, ever.

## Capital & Constraints
- Starting capital: ~$100,000 (paper)
- Platform: Alpaca (paper trading)
- Instruments: Stocks ONLY
- PDT limit: not a constraint (account ≥ $25k)

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

## Entry Checklist
- Specific catalyst?
- Sector in momentum?
- Stop level (7-10% below entry)
- Target (min 2:1 R:R)
