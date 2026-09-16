# Implementation following the September 17 audit

This change completes the first remediation stage and adds a read-only broker
coverage checker. It does not complete the durable execution coordinator or
start the prospective investment experiment.

## Implemented

- Trail replacement validation requires the broker's actual `stop_price`.
  A prior high of 130/current price 120 can no longer approve lowering the
  resting stop from 117 to 114. Missing broker floor is a refusal.
- Entry protection is unambiguous: fixed stop 9.5–10.5% below entry or exactly
  10% entry trail. Non-equity symbol formats are rejected by the pure engine;
  the mutation boundary also checks broker asset class and buy tradability.
- The adapter accepts only the exact paper and market-data endpoints. The
  former live override has been removed.
- Status capture preserves curl transport errors, refuses non-2xx responses,
  and clears old status before a mutation. Nested preflight reads cannot
  overwrite the outer mutation's status.
- Every adapter mutation runs `validate_mutation.py` on its actual arguments
  before transport. The old env flag is only caller intent. Buys use fresh asks,
  validate current account sizing, require GTC OTO protection and refuse while
  another buy is pending. Bulk mutations are disabled. The OTO builder now
  defaults to GTC so an interrupted conversion does not deliberately use a
  day-only protective leg.
- `doctor.py` checks offline state; `--broker` adds read-only, current-order
  coverage reconciliation. Conditional/held/expired/canceled/day orders cannot
  certify coverage. Remaining quantities, duplicate IDs and excess protection
  are checked. It does not automatically repair or alert.
- Dashboard safety statements now distinguish logged fixed/trailing protection
  from actual broker verification. Incomplete realized P&L/win rate is withheld;
  benchmark estimates and data age are visible. The XLI historical exit is
  reflected. README/architecture no longer claim risk control is solved.
- CI checks actual integration-test results for skips rather than merely
  collecting test names. Dashboard generation is triggered by builder changes.
- [Forward experiment specification](../../PAPER-EXPERIMENT.md) records the next
  research milestone without pretending the experiment has started.

## Compatibility changes

- Midday trail validation passes `--current-stop` from the broker order. Both
  local and cloud routine files have been updated; stale external prompt copies
  must still be replaced by the documented thin prompts.
- Direct mutation payloads using `day`, unprotected buys, unsupported fields,
  non-equities, bulk commands or live overrides are refused.
- A stale/missing ask, pending buy or full 500-order response prevents new risk;
  the latter fails closed because the weekly count may be incomplete.
- Offline doctor success means its requested local checks passed. It reports
  `broker_verified: false` and does not certify ledger durability.

## Verification

- Full suite against isolated Postgres 16: **280 passed**.
- Maintained audit reproductions: **7 passed** (originally seven failures).
- Dashboard generation matches the committed data file; JavaScript syntax and
  rendering smoke checks passed, including fixed-stop and unverified labels.
- Offline doctor passed; no live broker certification was attempted.
- Python compilation, shell syntax, documentation links and diff whitespace
  checks passed. The temporary audit database was removed after testing.

## Still outstanding

Execution still lacks a durable account-wide coordinator, broker idempotency
and restart-safe cancel/replacement. Validation and HTTP submission are
separate operations: market movement, concurrent routines and ambiguous network
outcomes remain. Market-order fills can exceed quote-based estimates.

Raw protective cancellation still creates a window requiring the next action.
The wrapper verifies cancellation identity and held position, but does not
persist a replacement intent or enforce a recovery deadline. The stop floor
check in the routine must happen before cancellation; a canceled order is not
present in the subsequent open-order snapshot.

The agent still holds credentials and can modify local code. This change is
an application correctness boundary, not credential isolation. Postgres remains
optional; preceding preflight/response recording is still caller-coordinated,
and the complete broker lifecycle is not yet recorded. The new mutation check
does not itself bind an execution to a durable ledger decision ID.

Actual cloud configuration, current broker positions and historical accounting
have not been independently verified in this implementation session. No orders,
emails, production deployment, Git push or real-money changes were made.

Next: implement the coordinator and independently scheduled monitoring, then
reconcile broker exports and run the versioned forward experiment.
