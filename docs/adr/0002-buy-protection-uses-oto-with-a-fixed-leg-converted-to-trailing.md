# A buy is protected by an OTO fixed leg, converted to a trailing stop after fill

Every buy is submitted as a single `oto` order carrying a **fixed** `stop_price`
leg at the rule-4 distance (9.5–10.5% below entry). Once the entry fills
completely, a separate step cancels that leg and places the standalone 10% GTC
`trailing_stop` the strategy actually wants. The position is therefore protected
from the instant it exists, and converges on a trailing stop shortly after.

Resolves Wayfinder ticket
[#36](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/36).
Rests on the empirical findings in
[`docs/research/0001-alpaca-atomic-entry-plus-protective-stop.md`](../research/0001-alpaca-atomic-entry-plus-protective-stop.md).

## The constraint

Alpaca offers atomicity or a trailing protective leg, **not both**. A bracket or
OTO places entry and protective leg in one request with no half-state — a
rejected entry creates zero orders — but the loss leg must be a fixed
`stop_price`. Every spelling of a trailing leg is rejected 422, and the docs
commit only to supporting it "in the future" with no date.

Strategy rule 4 mandates a trailing stop. So the buy path had to give up one of
the two.

## Why the fixed leg wins

**Rule 4 states a mechanism where it meant an intent.** "10% trailing stop on
every position as a real GTC order", read literally, forbids this decision —
even though a position resting on a fixed stop at the rule-4 distance is
strictly safer than one resting on nothing. A rule whose wording forbids the
safer option is describing how it once achieved its goal, not the goal.
`memory/TRADING-STRATEGY.md` is amended to say protection at all times, with a
10% trailing GTC as the mechanism and a fixed stop at the rule-4 distance
permitted as a transitional state during entry. **The engine may only enforce
rules the rulebook states** — same precedent as `LONG_ONLY` in
[#21](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/21).

**The naked window's cost is not its probability — it is that it is unbounded.**
Today's flow buys, waits for a fill, then places the stop. The window is short
and has never bitten. But if the stop POST fails after the routine has already
exited, nothing retries: the position sits unprotected until a human notices.

**The decisive argument is the shape of the failure, and it inverts the obvious
one.** This decision trades an *unprotected* position for a *silently
non-ratcheting* one — if the conversion never happens, the position looks
covered while running a stop that does not follow the price up. That sounds
worse, and is not: a wrong stop is a **state** the ledger can be queried for,
whereas a routine dying between two calls leaves **nothing behind to query**.
Detectability beats a marginally better failure mode that is invisible.

## What follows

- **Whole shares only on the buy path.** OTO hard-rejects fractional and
  notional (`422 fractional orders must be simple orders`, verified live for
  both `qty: "1.5"` and `notional: "20"`). A proposed buy with a fractional qty
  is a `Violation`. `Position` keeps accepting fractional `qty` — it reports
  whatever Alpaca holds — per #21.
- **A partial fill is an incident.** The docs state legs do not activate until
  the entry fills *completely*, and are silent on what happens to a leg when a
  partially-filled entry expires. The buy path hard-fails on
  `filled_qty != qty` rather than guessing. The empirical test is ticketed
  separately: forcing a partial fill needs a large order on an illiquid name, a
  materially riskier paper test than any run so far, and its answer changes only
  the edge handling, not this decision.
- **The silent-downgrade guard, in two places doing two jobs.** Sending both
  `stop_price` and `trail_percent` inside `stop_loss` returns **HTTP 200** with
  the trail silently `null` — a fixed stop wearing a trailing stop's name, with
  no error anywhere. Prevention: protection is a union of `Trailing(percent)`
  and `Fixed(stop_price)`, and the OTO serialiser for `Fixed` emits
  `stop_price` only, with no code path that can add a trail field — the bad
  request is unrepresentable. Detection: **read the leg back after submission**
  and assert its type and trail fields match what was asked for. A pre-POST
  assertion is deliberately omitted; it would guard a payload that cannot be
  built wrong.
- **Nothing retries the conversion in-process; the next routine converges it.**
  The conversion is recorded in the ledger as its own act with its own
  idempotency key, and "position protected by `stop` where `trailing_stop` was
  required" becomes a state each routine checks and fixes on entry. With five
  scheduled runs a day, the worst case is a position resting on a
  compliant-distance fixed stop for a few hours. This is a convergence step
  inside routines that already run — **not** the reconciliation worker the map
  rules out of scope.
- **The PDT fixed-stop fallback is repurposed, not deleted.**
  `routines/market-open.md:56-59` places a fixed stop when Alpaca "rejects with
  PDT error" — an error that can no longer occur, since Alpaca removed the PDT
  surface on 2026-07-06. The fallback goes; the fixed stop reappears one step
  earlier as the OTO leg on the entry call itself. It moves from the error path
  to the happy path. Answers item 2 of
  [#35](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/35).
- **[#37](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/37) is
  a hard dependency, not a nice-to-have.** `unprotected_orders()` already
  miscounts a broker-rejected stop as protection. This decision's entire safety
  argument rests on that query being trustworthy.

## Considered and rejected

**Keep the two-call flow** (buy, poll for fill, place the standalone trailing
stop). Preserves rule 4 exactly as written and keeps failures loud. Rejected
because the loudness is theoretical — there is no listener once the routine
exits — and it leaves the unbounded window that map
[#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19) exists
to eliminate.

**Wait for Alpaca to ship trailing legs.** No date, changelog entry, or roadmap
item exists; "in the future" is the entire commitment. Functionally the two-call
flow plus hope. Ruled out explicitly rather than by omission — if Alpaca ships
it, this ADR is superseded.

**Treat the conversion window as a tracked exception with a deadline**, rather
than amending rule 4. Rejected: it is the same decision plus bookkeeping, and
the deadline needs a monitor that does not exist and is out of scope.

## Scope boundary this fixes

This map makes wrong-protection a **queryable ledger state**. It does not build
the thing that watches it. Unprotected-position alerting and an operator
kill-switch are both out of scope — the first by the map's existing
monitoring-and-alerting boundary, the second because nothing in the destination
requires an operator-facing control.

## Rulebook and mechanics are kept apart

Only the rule-4 rewording lands in `memory/TRADING-STRATEGY.md`. Whole-shares
and partial-fill-hard-fail are **broker mechanics**, not strategy: they exist
because Alpaca rejects fractional OTOs and because an unknown fill state is
unsafe to act on. Mixing them into the rulebook would leave the next reader
unable to tell which constraints are beliefs about markets and which are
concessions to an API.
