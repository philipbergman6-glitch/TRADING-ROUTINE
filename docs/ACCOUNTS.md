# Broker accounts and profiles

Two Alpaca **paper** accounts under one login, selected per invocation by
account profile (see `CONTEXT.md`, ADR 0004). Keys are never recorded here;
only identifying fields. Both accounts use the same paper endpoint, which
`scripts/alpaca.sh` hard-pins.

| Profile | Purpose | Key names | Local file | Pinned in |
|---|---|---|---|---|
| `production` (default) | The scored account every routine and Action trades | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `.env` | `scripts/accounts.json` |
| `drill` | Isolated engineering account for recovery rehearsals and destructive tests | `DRILL_ALPACA_API_KEY`, `DRILL_ALPACA_SECRET_KEY` | `.env.drill` | `scripts/accounts.json` |

## Identifying fields

| Field | production | drill |
|---|---|---|
| `account_number` | `PA38JXAA3CY1` | `PA3YVVX6ERYG` |
| `id` | `433b0293-7c1c-4f67-87b3-52466b8403bb` | `fe69e15b-bcab-4ece-b80f-5da1d95bffc0` |
| `created_at` | 2026-04-17T11:01:16Z | `2026-10-13T13:16:43Z` |
| Starting equity | $100,000 (one JNLC deposit, research 0006) | $100,000 fixed (research 0010) |
| GitHub secrets | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `DRILL_ALPACA_API_KEY`, `DRILL_ALPACA_SECRET_KEY` |

Verified read-only on 2026-10-12 with `bash scripts/alpaca.sh verify-account`.
The drill row is filled in by the setup wizard (it writes
`scripts/accounts.json`; commit that change together with this table).

## Selecting a profile

```bash
bash scripts/alpaca.sh verify-account                      # production
ALPACA_PROFILE=drill bash scripts/alpaca.sh verify-account  # drill
bash scripts/alpaca.sh --account drill positions           # same thing, flag form
```

Rules enforced by `scripts/alpaca.sh` and `scripts/heartbeat.py`:

- Exit 6: both key pairs present in one process, an unknown profile, the
  flag and `ALPACA_PROFILE` disagreeing, or the selected pair missing.
- Exit 8: before any `order`, `close`, `close-all`, `cancel`, `cancel-all`
  the broker's `account_number` must equal the profile's pin; an unpinned
  profile refuses all writes.

## Provisioning or resetting the drill account

Run `bash scripts/setup_drill_account.sh`. It walks the owner through:

1. Identifying the three active E2BOT routines (`docs/ROUTINE-VERIFICATION.md`)
   and confirming they do not hold, and will not be given, the drill keys.
2. Opening a new paper account in the Alpaca dashboard (paper account number
   in the top-left → "Open New Paper Account"), then generating its keys.
3. Writing the pair to `.env.drill` (gitignored) and to the two `DRILL_*`
   GitHub secrets.
4. Reading the new account read-only, pinning its number and id in
   `scripts/accounts.json`, and confirming production is unchanged.

A reset is delete-and-recreate in the dashboard, which rotates keys and the
account number; rerun the wizard afterwards. Until then drill writes fail
with exit 8, which is intended.

## E2BOT routines

Recorded by the wizard; append one dated line per run.

- 2026-10-13: attached to this repo with the production Alpaca, Perplexity and email keys; they never receive the DRILL_* pair (owner confirmed in the wizard).
