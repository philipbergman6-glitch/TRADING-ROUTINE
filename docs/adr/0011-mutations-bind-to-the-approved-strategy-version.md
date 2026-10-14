# 0011. Mutations bind to the approved strategy version; only restoration is exempt

Date: 2026-10-12. Status: accepted. Amends ADR 0003 §1 ("unset means v1").
Wayfinder ticket #106.

## Context

`scripts/strategy_version.py` was run only by routine prose (market-open,
midday, `/trade`). The mutation CLIs (`submit_entry.py`, `close_position.py`,
`replace_stop.py`), the adapter gate (`validate_mutation.py`) and the
protection monitor selected engine parameters straight from `STRATEGY_VERSION`
through `params_from_env`, where unset silently meant v1. `STRATEGY_VERSION`
is unset in GitHub Actions (READINESS finding 5), so the monitor has never been
bound to anything. A routine whose prose skipped the gate, or a runner that
lost the variable during a v2 segment, would trade under rules nobody approved.

## Decision

1. **One source for the approved version: `"active"` in
   `docs/rulebook-pins.json`.** The approved version is the one named there,
   with a pin (sha256) and no `until`.
   - A GitHub repository variable lives outside git and outside review, and
     reaches only Actions: cloud routines and local sessions never see it.
     It cannot be the one source for all three contexts.
   - The rulebook marker sits in the file whose integrity is in question. The
     weekly review once edited the rulebook without a bump (rule 14,
     `c92afde`). A marker cannot vouch for the text around it.
   - The pins file is changed only by a deliberate, owner-reviewed bump (map
     #93 decision: a policy change lands as a versioned bump plus a new pin).
     It authenticates the rulebook by hash. It still names a version when the
     rulebook or the environment is broken, and restoration needs that version.

2. **Everything else must agree with it.** `scripts/strategy_version.bind()`
   returns the approved version, its engine parameters, and an error. The
   error is `None` only when all three of these hold:
   - `STRATEGY_VERSION` is set and equals the approved engine (`v1`) or the
     full approved version (`v1.1`). Unset, empty, malformed (`V1`, `" v1"`,
     `1`, `v1.x`) and different (`v2`, `v1.2`) all fail. Unset no longer means
     v1.
   - The rulebook carries exactly one marker, and it equals the approved
     version.
   - The rulebook's sha256 equals the approved pin.

   Pins that cannot name an approved version raise `VersionBindingError`, and
   then nothing proceeds. `STRATEGY_VERSION` stays required as the deployment's
   acknowledgement: merging a bump approves it, and setting the variable
   starts the segment on that runner.

3. **Bound in code, at every mutation path.** Without a binding:
   - `submit_entry.py` refuses with `version_binding_refused`.
   - `close_position.py` refuses with `version_binding_refused`.
   - `replace_stop.py` refuses with `version_binding_refused`, except for
     restoration (§4).
   - `validate_mutation.py` (the gate every `alpaca.sh` mutation passes)
     refuses with "strategy version binding failed". It refuses closes and
     cancels before any broker read.
   - `protection_monitor.py` plans with the approved parameters and hands
     every action to `replace_stop`, which refuses all but restoration. It
     exits 6 and always alerts. With unreadable pins it still verifies and
     reports coverage, but acts on nothing.

   Refusals keep ADR 0006: a refusal on a held position without verified
   coverage is exit 8 (`version_binding_refused_position_unprotected`), never
   exit 3. Read-only resume reports (`already_submitted`, `already_replaced`,
   `close_complete`) still answer, because they mutate nothing. Broken pins
   are a usage error (exit 2) before any broker read.

4. **The exception: protective-stop restoration.** It runs under the approved
   version's parameters, and an incident alert goes out. An operation
   qualifies only if all of these hold:
   - It is `replace_stop` on an old stop whose status is already `canceled` or
     `pending_cancel`. That cancel was sent by an earlier run; this run sends
     no cancel.
   - The symbol is held.
   - Its live coverage (`risk_engine.reconciliation`) is not verified.

   It then places the `rs-<old id>` replacement or, failing that, the
   `rr-<old id>` exact-level restore. On the gate's side, the exempt mutation
   is an `order` for a sell `stop` or `trailing_stop` whose client id carries
   the `rs-` or `rr-` prefix. The existing floor check then proves the named
   stop is confirmed canceled and that nothing protective rests. The gate
   validates it under the approved version's floor, trail band and order
   rules.

   Nothing else qualifies: entries, closes, cancels, and renewing, converting
   or tightening a stop that still rests (all of those cancel first). The
   `rs-` and `rr-` client-id prefixes are reserved for `replace_stop`.

5. **Alerting from unattended runs.**
   - Cloud routines: the prose gate (`strategy_version.py`, exit 5 or 1) emails
     "STRATEGY_VERSION MISMATCH" and stops. The CLI refusals are a second
     line, not the alert.
   - Monitor: exit 6 fails the job (the heartbeat and GitHub notifications
     fire), and the report email carries "VERSION BINDING FAILED". A lost
     alert is still exit 9.
   - `replace_stop.py` run as a CLI under the exception sends "VERSION BINDING
     INCIDENT" through `scripts/email.sh` and records `alert_delivered`.
   - The gate writes a "VERSION BINDING EXCEPTION" line to stderr.

## Considered options

- *Leave the check in routine prose.* Rejected: prose can be skipped, and the
  monitor has no prose.
- *Derive parameters from the pins file and drop `STRATEGY_VERSION`.*
  Rejected: the ticket keeps the variable as the deployment acknowledgement,
  and the rulebook already says it MUST match the major version.
- *Let the binding fail open for all protection work* (renew, convert,
  tighten). Rejected: each of these cancels a resting stop first. Under an
  unbound runner, a resting stop protects better than a cancel. The renewal
  window (10 days) leaves time to fix the variable while the monitor alerts
  on every run.

## Consequences

- **Deployment step.** `STRATEGY_VERSION=v1` must be set wherever these
  scripts run:
  - the GitHub Actions repository variable (`gh variable set STRATEGY_VERSION
    --body v1`), read by `protection-monitor.yml`;
  - each cloud routine's environment. Since 2026-10-14 the repository's
    `.claude/settings.json` exports `STRATEGY_VERSION=v1` into every Claude
    Code session of this checkout, so a routine session is bound as soon as
    it syncs main; a value set in the cloud environment still wins. The
    routines ran three sessions unbound (2026-10-13 market-open through
    2026-10-14 midday) before this, each stopping at its gate;
  - local shells. The Python CLIs read the process environment, not `.env`.

  Until the variable is set, every routine stops at its gate, and the monitor
  exits 6 on every run with maintenance refused. Resting stops are not
  touched.
- **Bumps.** A minor bump changes the rulebook marker, adds a pin, moves
  `active` and closes the old entry with `until`, all in one commit. Runners
  that set the engine (`v1`) keep working; runners that set the full version
  need the new value. A major bump also needs `STRATEGY_VERSION` changed
  everywhere: that is the deliberate segment start (spec §5).
- `params_from_env` remains for the read-only and advisory tools
  (`validate_order.py`, `validate_stop_change.py`, `build_oto_order.py`,
  `blotter.py`). Any mutation they lead to is bound at the gate.
- Unchanged gap: nothing places a stop on a held position that has no
  canceled predecessor (an expired stop, or one that was never placed). The
  monitor reports it (exit 5 or 6); a human acts.
