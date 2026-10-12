# 0004. Isolated drill account: separate key names, one pair per process, committed account pin

Date: 2026-10-12. Status: accepted. Wayfinder ticket #111 (map #93), research 0010.

## Context

The freeze gate needs an observed recovery rehearsal on an isolated paper
account. Alpaca allows up to three paper accounts per login, all on the same
host, and no Trading API payload says which account answered; the only handle
on an account is its key pair, and the only in-band identifier is
`account_number`. Resetting a paper account is delete-and-recreate, which
rotates keys and the number together. Three "E2BOT" routines of unknown
account are active in the same cloud workspace.

## Decision

- Drill credentials use distinct names, `DRILL_ALPACA_API_KEY` /
  `DRILL_ALPACA_SECRET_KEY`, in a separate local file `.env.drill` and separate
  GitHub secrets. The `ALPACA_*` names stay production-only.
- `scripts/alpaca.sh` (and `scripts/heartbeat.py`) select the pair by
  `ALPACA_PROFILE` (`production` default, or `drill`; also `--account`). A
  process holding both pairs is refused (exit 6) before any HTTP call, so a
  drill can never silently pick up production keys or vice versa.
- Each profile's expected `account_number` (and `id`) is committed in
  `scripts/accounts.json`. Every mutating subcommand reads `/v2/account` as its
  last gate before the write and refuses (exit 8) on mismatch or when the
  profile is unpinned. `verify-account` exposes the same check read-only.
- Production routines and Actions must never receive `DRILL_*`; drill runs
  receive only `DRILL_*` plus `ALPACA_PROFILE=drill`.

## Considered options

- *Pin in env next to the keys*: rejected; a wrong paste would carry its own
  matching pin, and a reset would silently retarget. A committed pin fails
  loudly until the repo is updated with the secrets.
- *Separate wrapper script for drills*: rejected; every validator shells out
  to `alpaca.sh`, so a second entry point would fork the broker boundary.
- *Reusing `ALPACA_*` names with a different value per environment*:
  rejected; it is exactly the mix-up the pin exists to catch, and nothing
  downstream could tell the two apart.

## Consequences

- One extra `GET /v2/account` per write on production (200 req/min budget).
- A drill reset is: delete and recreate in the dashboard, then rerun
  `scripts/setup_drill_account.sh`, which rotates the secrets and the pin in
  one pass. A stale pin blocks drill writes until then.
- The pin file is public in the repo; account numbers are identifiers, not
  credentials, and the paper endpoint is hard-pinned.
