# 0003. Versioned strategy parameters and an independent protection monitor

Date: 2026-09-20. Status: accepted.

## Context

The v1 rulebook ran for three months as prose interpreted by scheduled Claude
routines. `docs/STRATEGY-SPEC.md` freezes v1 and specifies v2 with different
constants (7% entry stop, +5% conversion threshold, sector cap, cooldown).
During the Sep 8–16 outage no protection work happened because it depended on a
Claude session and on the optional ledger. Retries of buys and exits could
double-submit because nothing identified an order across runs.

## Decision

1. Engine constants live in `risk_engine/versions.py` as frozen `StrategyParams`
   (`V1`, `V2`). Every engine function takes `params`; every CLI reads
   `STRATEGY_VERSION` once at its boundary. Unset means v1; unknown is a hard error.
2. Protection is enforced by `scripts/protection_monitor.py` on a GitHub Actions
   cron, planned by the pure `risk_engine/monitor.py`, executed only through
   `scripts/replace_stop.py`. It never consults the ledger and never opens or
   closes positions.
3. Buys and exits carry deterministic client order IDs (`en-<day>-<sym>`,
   `cl-<day>-<sym>`) and look the ID up before submitting and after, so a rerun
   resumes instead of repeating.
4. Round trips, cooldown and sector streaks are computed from broker fills
   (`risk_engine/blotter.py`), not from markdown or the ledger.

## Consequences

- v1 shadow and v2 run through the same code under different parameters.
- A second entry of the same symbol on the same day needs an explicit `--tag`.
- The monitor's actions are visible only in its run logs and emails until the
  ledger records them; the blotter remains the accounting source.
- The cancel→place window is recoverable, not atomic (ADR 0002 unchanged).
