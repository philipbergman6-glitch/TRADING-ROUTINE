# Freeze-rehearsal drills

The recovery and failure drills that gate the v1 freeze (map #93, ticket #112,
audit 2026-10-12 package 6). Each scenario says how it is induced, the terminal
state that counts as a pass, the evidence that proves it, and where it runs:

- **CI stub**: an offline test against the stubbed broker and a local bare
  repository as the state store (`tests/store_support.py`). Runs on every PR.
- **drill account**: run by hand on the isolated paper account `PA3YVVX6ERYG`
  (`ALPACA_PROFILE=drill`, `docs/ACCOUNTS.md`) in one observed session.
- **both**: the CI test pins the logic; the live run proves what only the real
  broker and GitHub can show (a real lost response, a real non-fast-forward
  rejection, a real stale quote, real Actions history).

## Safety rules

1. Broker mutations happen only with `ALPACA_PROFILE=drill`. The process
   holds only the `DRILL_*` key pair; holding both pairs is exit 6 before any
   HTTP call, and every write first checks the pinned account number (exit 8).
2. Fault injection (`COORDINATOR_FAULT=<point>`, `scripts/coordinator.py`) is
   honoured only with `ALPACA_PROFILE=drill`; on any other profile it is a
   usage error (exit 2) before anything is read or sent.
3. The drill profile coordinates on its own state-store branch,
   `drill-state` on the same origin (`scripts/state_store.py: store_branch`).
   A drill never takes production's lease or reserves production capacity, and
   it still meets GitHub's real non-fast-forward rejection. Never merge
   `drill-state` into `main`.
4. Alerts: the drill key file holds no email credentials, so set
   `EMAIL_FALLBACK_FILE` to a scratch file; `email.sh` would otherwise append
   undelivered alerts to `DAILY-SUMMARY.md`.
5. Tiny size only: 1 share of a broad ETF (SPY).
   A broad ETF with no single name held needs a waiver, so every entry carries
   `--composition-waiver "engineering drill #112 on the drill account; not a trade"`
   (rule 14). Rule 8 allows 3 new trades a week on the drill account too.
6. End flat and stop-free: no position and no open order.

## Session setup

```bash
# Keys come from the drill profile file; never print them. From a worktree,
# source the main checkout's loader (the Bash tool is zsh; _env.sh needs bash).
drill() { env -i HOME="$HOME" PATH="$PATH" bash -c '
  export ALPACA_PROFILE=drill STRATEGY_VERSION=v1 EMAIL_FALLBACK_FILE=/tmp/drill-alerts.md
  source <main checkout>/scripts/_env.sh; "$@"' drill "$@"; }

drill bash scripts/alpaca.sh verify-account            # {"profile":"drill","account_number":"PA3YVVX6ERYG"}
drill bash scripts/alpaca.sh positions                 # []
drill bash scripts/alpaca.sh orders open               # []
drill python3 scripts/coordinator.py status            # drill-state: no holder, nothing unfinished
drill python3 scripts/run_record.py start --routine drill --trigger local \
    --command-file docs/DRILLS.md --model <model id>
```

Give each concurrent writer its own id with `TRADING_RUN_ID=<run id>-<label>`;
otherwise every helper in the checkout writes as the session's run id.

## Catalogue

| # | Scenario | Induce | Expected terminal state | Evidence | Mode |
|---|---|---|---|---|---|
| 1 | Two writers simultaneously | Start two `submit_entry.py --symbol SPY --qty 1` at the same instant. CI: two coordinated actions from one base, and a second writer while the first holds the lease. | Exactly one buy order (`en-<day>-SPY`). The loser either waits (`lease held by … waiting`) or loses the push race (non-fast-forward → `withdraw` line → wait), then reports `already_submitted`/`already_filled`, exit 0. | `drill-state` events: both acquires, one valid, any `withdraw`; broker order list: one buy; both helpers' JSON. A store-level race (`state_store.py append` ×2 at once) shows `attempts: 2` for the loser: GitHub's real rejection. | both |
| 2 | Cross-midnight retry | An entry whose POST answer is lost past the budget just before 00:00 UTC; rerun after midnight without `--intent`. | No second buy: the rerun resolves yesterday's live attempt (`already_submitted`), and the lost intent is settled from broker state. | Store: `recorded` → `lost` → settled; one client order id POSTed. | CI stub (the broker cannot be told the time; a live run would mean an unprotected after-hours order) |
| 3 | Crash after cancel | `COORDINATOR_FAULT=after_cancel` on `replace_stop.py` (exit 97 right after the cancel). | Position naked until the lease is stale (expiry + skew, 12 min); then the next coordinated action or `coordinator.py recover` re-places the old level as `rr-<canceled id>`; intent `dead (restored)`; exit 0. Before 12 min, `recover` reports `lease_held` and does nothing. | Store: `rs-<id>` `recorded`, then `dead` with `reason: restored`; broker: old stop `canceled`, `rr-<id>` `new` at the old stop price. | both |
| 4 | Lost POST response | `COORDINATOR_FAULT=lose_response` on `close_position.py` (first POST answer and first lookup dropped). | The same attempt id is re-POSTed; the broker answers 422 `client_order_id must be unique`; the order is adopted; one sell; exit 0. | Helper JSON (`coordinator_notes`); broker: one `cl-<day>-SPY` order; store: close intent settled `filled`/`complete`. | both |
| 5 | Partial fill | CI: a buy that fills 4 of 10, then is canceled. | Only the unfilled part stays reserved while live; once dead with a fill, the intent is `filled` and counts as a trade this week. | Store intent states; `trades_this_week`. | CI stub (1 share cannot partly fill; paper partial fills are not inducible) |
| 6 | Missing history | The closed-orders read behind rule 8 fails, or returns the 500-row page cap. | Buy refused with exit 4 (`could not establish broker state`); nothing POSTed. | Helper exit code; broker order list unchanged. | CI stub (needs a broker outage) |
| 7 | Unavailable store | `TRADING_STATE_REPO` → a checkout whose `origin` is unreachable. | Buys, closes and replacements refused with exit 10 (`store_unavailable`), nothing sent. Restoring a stop on a held position with none still goes through and alerts `STORE UNAVAILABLE` (ADR 0004 section 1). | Helper JSON (`store_error`, `alerts`, `store_exception`); broker order list. | both |
| 8 | Stale quote | Submit an entry before the open, when the latest SPY quote is minutes old. After the open, submit a fresh one. | Refused by the mutation gate (`quote must be no more than 60 seconds old`), exit 3, refusal recorded; nothing POSTed. A fresh quote passes on a host clock up to 5 s behind the broker's (`QUOTE_CLOCK_SKEW`, #155). | Helper JSON; store: intent `refused`; broker order list empty. | both |
| 9 | Missed monitor | CI: a day whose live protection checks leave a gap over 90 min. Live: replay a real missed day through the real judge (`heartbeat.py --date 2026-10-07 --no-email`), with no dispatcher. | Heartbeat exit 5 naming the stale windows of the session. | Heartbeat JSON `protection_check.breaches`. | both |
| 10 | Failed alert delivery | CI: `email.sh` refuses or hangs. Live: the heartbeat of a missed day with an invalid Resend key; coordinator alerts with no email credentials. | Heartbeat exit 9 (missed AND undeliverable); coordinator JSON `alerts_delivered: false`. | Heartbeat JSON `alert_delivery: failed`; helper JSON. | both |
| 11 | Version mismatch | `STRATEGY_VERSION=v2` while `docs/rulebook-pins.json` approves v1.3. | Entry refused `version_binding_refused`, exit 3; nothing POSTed. Restoration of a naked stop still proceeds under the approved version and raises VERSION BINDING INCIDENT. | Helper JSON; broker order list. | both |

Killed holder (ADR 0010 consequences) is drill 1's second half: kill the first
writer after push 1 (`COORDINATOR_FAULT=after_record`), and the next writer
waits, takes over after expiry + skew and recovers the dead intent
(`dead (holder_died)`) before it acts.

### CI tests

<!-- Each row names the tests that pin it; tests/test_drills.py checks that every named test exists. -->

| # | Tests |
|---|---|
| 1 | `tests/test_coordinator.py::test_two_writers_one_waits_without_mutating_until_the_holder_releases`, `tests/test_coordinator.py::test_racing_writers_from_one_base_the_loser_withdraws_and_waits`, `tests/test_coordinator.py::test_crash_after_push_1_is_taken_over_after_expiry_and_skew_and_recovered_first`, `tests/test_coordinated_helpers.py::test_a_pending_entry_reservation_refuses_a_buy_broker_state_alone_would_allow` |
| 2 | `tests/test_drills.py::test_drill_cross_midnight_retry_adopts_the_lost_entry_instead_of_buying_again`, `tests/test_submit_entry.py::test_live_entry_from_before_midnight_is_found_after_it`, `tests/test_close_position.py::test_live_close_from_before_midnight_is_adopted_after_it` |
| 3 | `tests/test_coordinator.py::test_crash_between_cancel_and_sell_restores_coverage_as_dead_restored`, `tests/test_coordinated_helpers.py::test_close_killed_between_cancel_and_sell_is_restored_then_closed_by_the_next_writer`, `tests/test_coordinated_helpers.py::test_the_monitor_recovers_a_dead_writers_intent_on_every_live_run` |
| 4 | `tests/test_coordinator.py::test_lost_response_404_then_422_on_repost_adopts_the_order`, `tests/test_coordinator.py::test_lost_response_past_the_budget_is_lost_and_keeps_its_reservation`, `tests/test_coordinator.py::test_the_lose_response_drill_hook_drops_the_first_answer_and_lookup` |
| 5 | `tests/test_coordinator.py::test_partial_fill_reserves_only_the_unfilled_part_then_counts_as_filled_once_dead`, `tests/test_coordinated_helpers.py::test_a_buy_partly_filled_then_canceled_counts_as_a_trade_this_week` |
| 6 | `tests/test_drills.py::test_drill_missing_history_refuses_the_buy_with_exit_4` |
| 7 | `tests/test_coordinator.py::test_store_unreachable_refuses_the_mutation`, `tests/test_coordinator.py::test_store_unreachable_still_lets_a_stop_go_on_a_position_with_none`, `tests/test_coordinated_helpers.py::test_replace_stop_without_the_store_refuses_and_leaves_the_old_stop`, `tests/test_coordinated_helpers.py::test_replace_stop_without_the_store_still_restores_a_naked_position`, `tests/test_coordinated_helpers.py::test_validate_order_refuses_buys_when_the_store_is_unreachable` |
| 8 | `tests/test_mutation_validation.py::test_stale_future_or_naive_quote_refuses`, `tests/test_mutation_validation.py::test_fresh_quote_passes_within_the_clock_skew` |
| 9 | `tests/test_heartbeat.py::test_two_afternoon_checks_breach_the_level_and_name_the_windows`, `tests/test_protection_sla.py::test_observed_2026_10_07_first_check_at_19_15z_breaches_from_15_00z` |
| 10 | `tests/test_heartbeat.py::test_alert_failure_fails_the_job_even_when_only_issues_exist`, `tests/test_protection_monitor.py::test_alert_delivery_failure_fails_an_otherwise_clean_run`, `tests/test_drills.py::test_drill_an_undelivered_coordinator_alert_is_reported_not_swallowed` |
| 11 | `tests/test_submit_entry.py::test_unbound_runner_never_submits_an_entry`, `tests/test_replace_stop.py::test_unbound_rerun_after_cancel_restores_protection_under_the_approved_version`, `tests/test_coordinator.py::test_recovery_restores_even_when_unbound_and_raises_the_version_incident` |
| guard | `tests/test_coordinator.py::test_fault_injection_is_refused_outside_the_drill_profile`, `tests/test_coordinator.py::test_a_fault_set_outside_the_drill_profile_is_a_usage_outcome_for_every_helper`, `tests/test_drills.py::test_the_drill_profile_coordinates_on_its_own_store_branch`, `tests/test_account_profiles.py::test_both_key_pairs_present_is_refused_before_any_call`, `tests/test_account_profiles.py::test_both_pairs_refused_even_under_drill_profile` |

## Results

### Session 2026-10-13

Observed session on `PA3YVVX6ERYG`, run record
`drill-20261013T132842Z-c54427` on `drill-state` (`routine: drill`), code
`bfcdf9d` as recorded in the run's start line: `234ccad` plus this runbook's
store-branch change, before the branch was rebased for its PR (whose first
commit carries the same change). Each helper ran as `TRADING_RUN_ID=drill-20261013T132842Z-c54427-<label>`;
the labels below are those writer ids. Writers in the two-writer drills used
separate bare clones of `drill-state` (`TRADING_STATE_REPO`), as two cloud
checkouts would. Times are UTC.

SPY was the planned instrument, but after the open every SPY buy was refused as
a stale quote although the quote was fresh (see #155): drills that need a fill
ran on 1 share of SCHB (Schwab U.S. Broad Market ETF, about $29.85), whose
IEX quotes update less often, so the host-clock lag rarely made their age
negative. SPY results stay recorded as red under drill 8.

### Verdicts by drill

| # | Scenario | Result | Run / evidence |
|---|---|---|---|
| 1 | Two writers simultaneously | green | `writer2-a`/`writer2-b`, 13:33:27, SCHB: b's push was rejected non-fast-forward; b rebased, found its acquire void and pushed a `withdraw` (13:33:40), waited on a's lease, then recovered `en-20261013-SCHB` `acknowledged → filled` and exited 0 `already_filled`. Broker: one buy `b2a02363` (filled 29.86, OTO leg `c00c7554`, stop 26.87). Store-level race `race-a`/`race-b` 13:29:24: b `attempts: 2`. Killed holder: `killed` died with exit 97 after push 1 (13:47:23, no order); `takeover` logged `lease held by … waiting 15s` for 12 min, took over at 13:59:25 (`supersedes`) and recorded `en-20261013-SCHB-k` `dead (holder_died)` before acting. The first attempt on SPY (`writer-a`/`writer-b`, 13:30:29) raced the same way, but #155 refused both. |
| 3 | Crash after cancel | green | `cancelcrash` 13:34:28: exit 97 right after canceling `c00c7554`; `rs-c00c7554…` `recorded`; position naked. `recover-early` 13:34:41: `lease_held`, nothing done. `recover` 13:46:35 (lease stale at 13:46:29): took over, placed `rr-c00c7554…` (`57a42e08`, stop 26.87), intent `dead (restored)`, exit 0. Naked for 12 min, the bound ADR 0010 states. |
| 4 | Lost POST response | green | `takeover` 13:59:39 with `lose_response`: `http_status: "000"`, the same `cl-20261013-SCHB` re-POSTed and adopted; one sell `32220cac`, filled 29.86; intent `complete`. The helper does not log the re-POST's 422; it is inferred from the path (no `coordinator_notes`, one order). |
| 7 | Unavailable store | green | `store2` 13:34: SCHB entry, exit 10 `store_unavailable`, nothing sent. `storerestore` 13:47:08: after `rr-…` was canceled directly with `alpaca.sh cancel`, `replace_stop.py` with the store unreachable placed `rs-57a42e08…` (`8ac6c56e`, stop 26.87) with `store_exception` and alert `STORE UNAVAILABLE`; exit 0. (`store`, 13:28, pre-open: refused exit 3 by the stale-quote gate before the store check.) |
| 8 | Stale quote | green | Stale: `drill-stale-quote` 13:27:46, pre-open: quote stamped 13:19:58, exit 3 `quote must be no more than 60 seconds old`, `refused` recorded, no order. Fresh (red in this session: SPY refused at `writer-a`/`writer-b` 13:30:29, 12 of 15 samples with a negative age, host 0.11 s behind per `sntp`; #155) rerun after the fix, see the rerun below. |
| 9 | Missed monitor | red | #156. `heartbeat.py --date 2026-10-12 --no-email`: exit 5 and a 390-min breach, but `0 run(s) seen` although a live run (21:38Z) and a dry run (15:14Z) exist: runs are matched by `name`, which GitHub now sets to the run-name, so every day reads as missed. `--date 2026-10-07`: a traceback, not exit 4. |
| 10 | Failed alert delivery | green | Heartbeat for 2026-10-12 with an invalid Resend key: exit 9, `alert_delivery: failed` (Resend 401; nothing sent). Coordinator: `storerestore`'s alert with no email credentials, `alerts_delivered: false`, text in the fallback file. |
| 11 | Version mismatch | green | `version` 13:28:53, `STRATEGY_VERSION=v2`: exit 3 `version_binding_refused` (`approved v1.3`), `refused` recorded on `en-20261013-SPY-2`, no order. |

### Rerun 2026-10-13: drill 8 (#155)

Drill 8 only, after the #155 fix (quote ages down to −5 s count as fresh),
from the fix branch. Run record `drill-20261013T140936Z-4a2ddb` on
`drill-state`. Host clock 0.113 s behind (`sntp time.apple.com`); 3 of 10 SPY
quote ages read at 14:09 were still negative.

- `fresh` 14:10:00: `submit_entry.py --symbol SPY --qty 1 --price 777.48`
  passed the gate. `en-20261013-SPY-5` (`2cfe1098`) filled at 777.31, OTO stop
  leg 699.73; exit 0. **Green.**
- `close` 14:10: `close_position.py --symbol SPY` canceled the leg and sold
  `cl-20261013-SPY` (filled 777.32); the first run returned before the fill
  (`acknowledged`), the rerun with `--intent` settled it `close_complete`.
- The stale side keeps the 60 s bound unchanged, so the 13:27:46 refusal above
  stands; CI: `tests/test_mutation_validation.py::test_stale_future_or_naive_quote_refuses`
  and `::test_fresh_quote_passes_within_the_clock_skew`.
- End state: no position, no open order, `drill-state` no holder and nothing
  unfinished.

### Findings

- **#155** (drill 8) and **#156** (drill 9) are the two red drills, filed on
  map #93 with their evidence. Nothing was patched around them. #155 is
  fixed and drill 8 is green on its rerun (above).
- **Fixed before the session, in this change:** every profile shared `main`'s
  state store, so a drill would have taken production's lease and its entry
  intents would have reserved production capacity. The store branch now
  follows the profile (`drill-state` for drill).
- An undelivered coordinator alert leaves the helper's exit code unchanged
  (`storerestore`: exit 0, `alerts_delivered: false`); the monitor and the
  heartbeat fail instead (exit 9). The routines read the JSON, so this passes
  the drill as written; the owner may want the stricter behaviour.
- The drill account's equity is $10,000, not the $100,000 research 0010
  expected; `docs/ACCOUNTS.md` now records what the broker reports.
- Not provable from a local session: non-fast-forward rejection through the
  cloud routines' proxy (the ADR 0004 revisit trigger). This session pushed
  straight to GitHub; a cloud run that loses a race shows it as exit 10 or a
  `withdraw` line on `main`.
- The paper OTO buy took 16 s to fill (13:33:44 → 13:34:00); the losing
  writer's recovery saw it `filled`.
- End state, 14:00Z: no position, no open order; `coordinator.py status` on
  `drill-state`: no holder, no unfinished intent, two takeovers. Run record
  finished with outcome `incident` (the two red drills).

## Freeze criterion

The v1 baseline is tagged when, on one commit of `main`:

1. CI is green on that commit, and locally
   `env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'`,
   `scripts/doctor.py`, `scripts/build_dashboard_data.py --check` pass. The
   suite includes every CI drill above and `tests/test_drills.py`, which fails
   while any live drill lacks a recorded verdict.
2. Every row of "Verdicts by drill" is green from **one** observed session on
   the drill account, run at that commit (or at a later commit that changes
   no file under `scripts/`, `risk_engine/` or `.github/workflows/`), with its
   run id recorded here. A red row is fixed by its child ticket and the whole
   live session is rerun, not just the red row: interleavings are the point.
3. The drill account ends that session flat (no position) and stop-free (no
   open order), checked with `orders open` and `positions`.

Then the owner, after reviewing the session's PR, tags it (annotated, never
moved):

```bash
git fetch origin
git tag -a v1-baseline <commit> -m "v1 hardened baseline (map #93): drills green in session <run id>; rulebook v1.3"
git push origin v1-baseline
```

No agent pushes this tag.
