# 0013. A floor-preserving fixed stop is permitted protection

Date: 2026-10-12. Status: accepted. Amends ADR 0002 ("transient leg").
Wayfinder ticket #104 (decision, HITL with the owner), #107 (rulebook v1.2).

## Context

ADR 0002 made the entry's protective leg a fixed stop 9.5–10.5% below entry,
"permitted only as the transient leg of an atomic entry, pending conversion to
trailing" (rule 4, v1.1). The routines and the protection monitor never
behaved that way. Converting a fixed stop to a 10% trail starts the trail's
high-water mark at today's price, so when price has fallen the conversion
would lower the stop. Midday and market-open STEP 2b therefore HOLD the fixed
stop when `validate_stop_change` reports `stop_never_lowered`, and midday STEP
2c renews an expiring stop as a fixed stop at its current level, because a
fresh trail would drop it. Read literally, v1.1 rule 4 called every such held
stop a violation, and rule 7 ("never within 3% of current price") gave no
instruction when price drifts toward a resting stop (XLB, 2.4% above its
renewed fixed stop on 2026-09-18).

The audit (`docs/audits/2026-10-12/V1-FOUNDATION.md`) required every v1 rule
to be consistent across rulebook, scripts and routines. Either the routines
change to match the text, or the text changes to match the routines.

## Decision

**The rulebook changes, not the routines.** Rulebook v1.2:

1. Rule 4: the entry stop is placed at the 10% distance and converted to a
   10% trailing stop as soon as that would not lower it. A fixed stop held or
   renewed because conversion would lower it is permitted protection, not a
   transient; it converts the first session a 10% trail would sit at or above
   it. No stop is always a violation.
2. Rule 7: the 3% minimum constrains placing or moving a stop. Drift to within
   3% of a resting stop is a recorded hold (CONTEXT.md: *Standing stop*).
   Renewing an expiring stop at its current level or higher is never a rule-7
   violation.
3. The entry checklist's stop band is 10% (9.5–10.5%); "7–10%" was a v2 idea
   leaking into v1.

Enforcement follows the act/state split: the engine judges acts (placement at
entry, every stop change, renewal on the never-lowered check only), the
protection monitor reports state (coverage, held fixed stops, standing stops),
and the routine records drift in the trade log. The per-rule owner is the table
in `docs/STRATEGY-SPEC.md` section 2.1.

## Consequences

- No engine parameter changes. The held-stop behaviour already in the routines
  and `risk_engine/monitor.py` becomes the rule rather than a deviation from it.
- Midday STEP 2c stops gating renewals with `validate_order --stop-price`,
  which applied the entry band and 3% check against current price and would
  refuse a valid renewal, and gates them with `validate_stop_change.py`.
- The mutation gate (`validate_mutation.py`, run by `replace_stop.py` and the
  monitor) still applies the 3% check to a same-level renewal, so a standing
  stop inside 3% cannot yet be renewed and would expire. Until #137 lands, the
  routine emails "RENEWAL BLOCKED" with the expiry date instead of retrying;
  that email is the owner's deadline for #137.
- Considered and rejected: change the routines to convert immediately (lowers
  the floor, breaks rule 7's "never lower"); convert to a wider trail to stay
  outside 3% (also lowers the floor). Both trade a paper violation for a real
  loss of protection.
