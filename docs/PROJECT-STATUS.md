# Engineering handoff

Updated: **2026-10-16**. Baseline: GitHub main **`397ddc7`** (code tip
`518cd3f`, PR #188; later commits are routine logs and state records). The
v1 freeze milestone (#93) closed on 2026-10-13 and is tagged `v1-baseline`
(`4a66583`). Open GitHub issues were reviewed on 2026-10-15.

## Session 2026-10-16 (later): a "Midday" header broke the publish chain three times; heartbeat noise

Baseline `397ddc7`. No broker calls. Branch `ccr-870adb35-6yx7ir`.

- The 2026-10-16 midday run (stopped at the STRATEGY_VERSION gate, so it
  improvised its entry) wrote `### 2026-10-16 — Midday (Day 124, …)`.
  `build_brain_index.py` knows "Midday Scan", "Midday Cut", "Midday Exits";
  plain "Midday" is an unknown kind and the build hard-fails by design. Every
  `memory/**` push after it (midday 17:12Z, EOD 20:18Z, weekly review 21:10Z)
  failed `dashboard-data` and `tests`, each one also firing a heartbeat
  "WORKFLOW FAILED" email. Fix: the header now reads "Midday Scan" (the
  entry text is unchanged); `data.js`, `index.json` and `INDEX.md`
  regenerated through the 10-16 EOD and weekly review.
- `build_brain_index.py --parse`: parse every input, write nothing. Every
  log-writing routine (pre-market, market-open, midday, daily-summary,
  weekly-review; both the cloud and the local copy) runs it before committing,
  with the header kinds it may use spelled out. It replaces the dashboard-only
  `--parse` the daily summary gained in PR #188, which could not have caught a
  header kind. Pinned by `test_every_log_writing_routine_runs_the_parse_gate_before_committing`.
- heartbeat.yml: `heartbeat.py` exit 5 (misses found AND emailed) now leaves
  the job green — the email is the signal; a red run only added GitHub's own
  "Run failed" mail. The ALERT PATH FAILED issue opens only when the run is
  red for a reason other than exit 4 (exit 9, the workflow_run email step, or
  a step before the script). Exit 4 and 9 still fail the job. The five issues
  that rule opened on exit-5 nights (#141, #143, #164, #167, #187) were
  closed as not planned.
- Checks: offline suite green (see commit), `doctor.py` OK, `--check` OK for
  both builders, `git diff --check` clean. heartbeat.yml parsed as YAML; the
  step-output wiring is pinned by a test, not exercised here (no Actions run
  until the branch is on main).
- Still owner-only: `STRATEGY_VERSION` unset in the cloud routine
  environment — the 10-16 market-open and midday both stopped at the gate, so
  no cut/tighten/renewal logic ran that day (trailing stops at the broker
  held); Resend key send-only (#147); dispatcher unprovisioned (#130).

## Session 2026-10-16: EOD snapshot bolded a value, the publish chain fell over

Baseline `3eddf2c`. No broker calls.

- The 2026-10-15 EOD snapshot wrote `**Day P&L:** **-$796.54 (-0.74%)**`.
  The `PORTFOLIO` regex in `build_dashboard_data.py` did not allow bold around
  a value, so `dashboard-data` (run 38800828297) and `tests` (run 38800828500)
  failed on `f7bde99`, the nightly heartbeat exited 5 (issue #187), and the
  2026-10-16 pre-market STOPPED at STEP 2c because `deployment_status.py`
  imports the same parser (run record `pre-market-20261016T113253Z-cfea06`).
  Fix: the regex tolerates `\**` around each value (the stop column already
  did); regression test `test_portfolio_line_tolerates_bold_wrapped_values`.
  The log line itself is unchanged.
- `build_dashboard_data.py --parse` parses both logs and writes nothing. Both
  daily-summary copies now say the Portfolio line is machine-read, values
  stay plain, and run `--parse` before committing the snapshot.
- `docs/dashboard/data.js`, `docs/brain/index.json` and `INDEX.md`
  regenerated through the 2026-10-15 EOD (118 snapshots, 21 blotter rows).
- Checks: offline suite 986 passed, `doctor.py` OK, `--check` OK for both
  builders, `git diff --check` clean.
- Still owner-only, unchanged this session: `STRATEGY_VERSION` unset in the
  cloud routine environment (pre-market counted a sixth session on 10/16; it
  was set for the 10/15 market-open run only); no market-open run record on
  10/12-10/14 and no midday run record since 10/09, so those schedules are
  not reaching a run-record start at all; Resend key send-only (#147);
  dispatcher unprovisioned (#130). Until this branch is on main the
  market-open and midday gates fail the same way pre-market did on 10/16.

## Fund Brain (session of 2026-10-15, later)

Map [#169](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/169)
charts the brain as decision tickets (trade id → ADR 0014 #172, thread per
trade #176, thesis record #178, outcome review #180, brief reads the brain
#184) with map #69 as first consumer. Landed in this session:

- `scripts/build_brain_index.py` → `docs/brain/index.json` + `INDEX.md`
  (ticket #174): the committed record joined per symbol and per UTC date;
  `--check`, `--symbol SYM`, `--refusals YYYY-MM`. Hard-fails on an unknown
  entry-header kind, a traded symbol without a sector, a week without a
  grade, a malformed run record. Tests `tests/test_build_brain_index.py`
  (golden + hard-fail). `dashboard.yml` regenerates and commits both files
  with `data.js`.
- Research 0012 (`research/brain-post-exit-closes`, #182 closed): nothing
  committed reproduces the post-exit table; SIP daily bars are readable with
  the paper key; recommended `memory/CLOSES.json` written forward-only by
  daily-summary. Research 0011 (`research/brain-entry-forms`, by a parallel
  session): header-form inventory; three launch-day lifecycles have no
  research entry.
- Next: ticket #172 (trade id, HITL grilling, owner needed), then #176.
  Checks this session: brain `--check` OK, dashboard `--check` OK, offline
  suite 984 passed (same one workstation-only email failure).

## Where the project stands

Paper trading has run on the Alpaca paper account since 2026-04-27 through
scheduled cloud routines (pre-market, market-open, midday, daily summary,
Friday weekly review), with an independent protection monitor and heartbeat
in GitHub Actions. The code has a pure risk engine, a broker mutation gate,
resumable protective-stop replacement, the coordinator (ADR 0010: one
account-wide lease, intents recorded before submission, reservations,
coverage-only recovery), a committed append-only state store with per-run
records (ADR 0004, 0012), a sha256-pinned versioned rulebook (ADR 0011), an
optional Postgres ledger, and a dashboard generated from the markdown logs.

Checks on 2026-10-15 from this baseline: offline suite 962 passed (one
`test_email_sh` case fails only on a workstation whose `_env.sh` provides real
Resend credentials; it passes in CI, run 2026-10-15 `tests` success),
`build_dashboard_data.py --check` OK, `doctor.py` offline OK, dashboard data
current through the 2026-10-14 EOD snapshot.

## Open operational items (owner-only)

1. **`STRATEGY_VERSION` is unset in the cloud routine environment**
   (`TRADING-ROUTINES`). Since 2026-10-13 `strategy_version.py` exits 5 at the
   top of market-open and midday, so neither has traded or touched a stop;
   pre-market records the incident each morning (5 sessions by 2026-10-15).
   The GitHub Actions variable is set, so the protection monitor is
   unaffected. Fix: add `STRATEGY_VERSION=v1` to the environment at
   claude.ai/code (routine bodies carry no env), then confirm the next
   market-open run record shows `outcome` other than `refused`.
2. **Protection dispatcher unprovisioned** (#130): needs the owner's
   Cloudflare account and a PAT. Until then the monitor runs on the GitHub
   cron only and its 90-minute level is not met.
3. **Resend key is send-only** (#147, recurring ALERT DELIVERY UNVERIFIED
   issues): alerts send but bounces cannot be read back. Replace the
   `RESEND_API_KEY` secret with a full-access key.
4. **Heartbeat exits 5 nightly** while item 1 stands (expected market-open and
   midday records are missing), filing an ALERT PATH FAILED issue each night.
   Close those issues once item 1 is fixed and a clean heartbeat runs.

## Next engineering milestone

Remaining before the 30-session $10,000 v2 paper run:

1. Set `STRATEGY_VERSION=v2` in both the Actions variable and the routine
   environment and flip `Active strategy version` in
   `memory/TRADING-STRATEGY.md` in the same change; `strategy_version.py`
   hard-fails when they disagree.
2. **Owner decisions** in spec section 7 (review threshold definition; rule 15
   trim vs delete). Rule 15 has no script until decided.
3. **Sector data.** `memory/SECTORS.json` holds the symbols traded so far; each
   v2 candidate needs its GICS sector recorded before `validate_order.py`
   accepts the buy.
4. **Segment start.** Move test orders out of the scored account, record the
   model ID per run, run the segment-start checklist in spec section 5.
5. Still open by design: the cancel→place window is recoverable, not atomic
   (#40); validate↔submit token binding stays #19/#26; the state brief that
   replaces log tails in routines is map #69.

Session notes below are in reverse order of when they were written, newest
first, then the sessions of 2026-10-12 and 2026-10-13 and the September work.

## Session 2026-10-15: dashboard blotter from broker fills

Baseline `f35e7ca`. One read-only broker call (`blotter.py --json`).

- The dashboard's trade blotter was a hand-written list ending 2026-08-10. It
  is now generated: the daily summary writes `scripts/blotter.py --json` to
  `memory/BLOTTER.json` beside the EOD snapshot, and `build_dashboard_data.py`
  emits `TRADES` from it (open lots first, then closed round trips newest exit
  first, engineering test symbol `F` excluded by name). The build hard-fails
  if the open lots disagree with the latest EOD book or a symbol lacks a
  sector. Realized P&L and win rate on the page now come from the same rows
  (+$2,703.45 over 16 round trips at 2026-10-14; matches research 0006 plus
  the XLB exit).
- Decision tape, risk panel, insights and chart notes refreshed through
  2026-10-13; `ANALYSIS_ASOF` 2026-10-15. Decision tape is newest first.
- Both `routines/daily-summary.md` and `.claude/commands/daily-summary.md`
  write and commit `memory/BLOTTER.json`.
- Checks: offline suite 962 passed (same local-only `test_email_sh` failure),
  `build_dashboard_data.py --check`, `doctor.py`, `git diff --check`.

## Session 2026-10-14: dashboard publish race

Baseline `f7adfd5`. No broker calls.

- `dashboard.yml` failed on the last two routine pushes (runs 203, 204): its
  `git push` was rejected as non-fast-forward because the routine's run-record
  finish line (ADR 0012) lands on main seconds after the memory push. The
  publish step now refetches main, rebuilds `data.js` on that tip and pushes,
  up to five attempts. `docs/dashboard/data.js` regenerated (log 2026-10-13).
- Checks: offline suite (958 passed), `build_dashboard_data.py --check`,
  `doctor.py` offline, `git diff --check`.
- Still owner-only, found by the same overview: `STRATEGY_VERSION` is set as
  the Actions variable (the monitor applied MPC's tighten on 2026-10-13) but
  not in the cloud routine environment (pre-market 2026-10-14 still exit 5);
  the dispatcher is unprovisioned (#130), so the monitor ran twice on
  2026-10-13 and not at all on 2026-10-14 before 17:20Z; no market-open or
  midday run record on 2026-10-14; Resend key still send-only (#147).

## Session 2026-10-12: execution identity (#96)

Implements ADR 0005 (audit defect 1). Baseline `65acb7a`. No broker calls.

- `scripts/execution_identity.py`: the one resolver both helpers use. Intent
  `<en|cl>-<YYYYMMDD>-<SYM>[-<seq>]`; attempts are the intent id then
  `-r1`..`-r5`, a new one only after the broker confirms the last dead; an
  unexpected status hard-fails. Without `--intent` it adopts a live attempt
  from today or yesterday (UTC midnight rule); terminal ones from yesterday
  are history. Seq is a `--tag` or the next integer (`-2`..`-9`); tags
  matching `r<digits>` are rejected.
- `close_position.py`: `already_closed` removed. Complete only when not held
  and no buy is live (`close_complete`, `position_gone`,
  `stop_filled_position_gone`, exit 0). A filled intent with the symbol still
  held mints a new intent (same-day re-entry). New states:
  `position_gone_buy_live` (3), `close_resting_without_position` (2),
  `close_intents_exhausted_manual_exit_required` (8 or 3 by coverage). A
  filled stop re-reads holdings and sells the remainder.
- `submit_entry.py`: a dead `en-` attempt is retried as `-r1`.. (no manual
  `--tag`); `already_filled` vs `already_submitted`; `entry_retries_exhausted`
  (3, or 8 if held uncovered).
- Both print `intent` and a `rerun` command carrying `--intent` in the JSON,
  and the intent/attempt on stderr before each POST (the ADR's interim
  "recorded" until the state store is wired, #100). Routine text in both
  copies (#78 open), `trade.md`, `ARCHITECTURE.md`, ADR 0003 status updated.
- Tests: `tests/test_execution_identity.py`; the audit probe
  `repro_v1_foundation.py:31` is
  `test_new_same_day_position_is_not_reported_closed_from_old_exit`, plus
  repeated close, same-day re-entry, missing stop, rejected recovery and
  cross-midnight cases in `test_close_position.py` / `test_submit_entry.py`.
- Not done then, done in #100 (below): the in-process lost-response re-POST
  and intent records in `state/`. Still open: drills on the isolated account
  (#112).

## Session 2026-10-12: committed state store (#115)

Implements ADR 0004's mechanics; nothing calls it yet (wiring is #100, run
records #108). Baseline `565562d`.

- `scripts/state_store.py`: `fetch` (always `git fetch origin main`, reads
  `FETCH_HEAD`), `replay` (hard-fails on any line failing the
  `id`/`kind`/`at`/`writer`/`schema` envelope, a duplicate id, or a torn final
  line), `new_event`, and `StateStore.commit` — push-as-CAS with subject
  `state: <writer> <intent> [skip ci]`; on rejection refetch, rebase, re-run
  the caller's `still_wins` predicate, retry up to the budget; a lost claim
  appends a `release` line and raises `ClaimLost`. Verified by subject plus
  event ids, never SHA. All failures are `StoreUnavailable`; the CLI
  (`replay`, `append`) exits **10** (`EXIT_STORE_UNAVAILABLE`).
- State file: `state/events.jsonl`. Commits are built with git plumbing on the
  fetched tip, so the writer's HEAD, index and working tree are never touched.
  Local mode (`local_store`, CLI `--local`) uses a bare clone at
  `~/.cache/trading-routine/state.git`, never the development checkout.
- Provisional, owned by #99: push budget `PUSH_BUDGET = 3` and the `release`
  kind name. Settled by #100: budget 5, kind `withdraw` (field `withdraws`).
- `.gitattributes`: `state/*.jsonl merge=union`. `protection-monitor.yml`:
  `permissions: contents: write` (no push yet).
- Checks: `tests/test_state_store.py` (50, offline, local bare repo as origin)
  plus the commands in AGENTS.md "Verification".

## Session 2026-10-13: the coordinator (#100)

Implements ADR 0010 on ADR 0004/0005. Baseline `df39494` (PR #135). Landed as
two PRs on the same ticket: #142 (core), then the helper wiring. No broker
calls; tests are offline (bare repo as origin, stub broker, fake clock).

- `scripts/coordinator.py`: `coordinate(body, ...)` is the one entry point;
  `submit_entry.py`, `close_position.py` and `replace_stop.py` run their logic
  as its body, so routine call sites are unchanged. Lease replay (`fold`),
  wait / takeover after `expires_at` + 2 min, recovery per the §4 table (only
  `rr-<canceled id>` restoration, pushed before the restoring POST), push 1
  (`recorded`/`refused`), 5-minute mutation deadline, lost-response budget
  (3 re-POSTs of the same id, 5 s apart; 422 proves existence), push 2
  (outcome settled from broker state + release).
- Exit codes: 10 store unavailable (unchanged), **11** lease wait exhausted,
  **12** acted, outcome not recorded (alerts). Monitor: 10 when recovery could
  not run, 12 propagated from an action.
- Reservations reach the engine from the store in `submit_entry` (preflight),
  `validate_order.py` (buys; exit 10 if the store is unreachable) and
  `validate_mutation.py` (inside `alpaca.sh`, own intent excluded).
  `trades_this_week` counts any buy with `filled_qty > 0`: Alpaca probably
  leaves `filled_at` null on a partly filled then canceled order (forum and
  ccxt evidence, low–medium confidence; not observed on our account).
- The monitor runs recovery every live run (`--dry-run` reports the store's
  unfinished intents). `scripts/coordinator.py status|recover` CLI.
- Store selection: this checkout's origin by default; `TRADING_STATE_STORE=local`
  for local `/trade` (dedicated clone, ADR 0004 §3; the local commands set it
  since #144); `TRADING_STATE_REPO` for tests
  and drills. Tests can never reach the real origin (conftest points
  `TRADING_STATE_REPO` at a nonexistent path).
- Drill hooks for #112: `COORDINATOR_FAULT=after_record|after_cancel|after_post|before_release|after_recovery_push`
  exits 97 there; `lose_response` drops the first POST answer and lookup.
  Drill profile only. Routine text: #144 (below).
- Tests: `tests/test_coordinator.py`, `tests/test_coordinated_helpers.py`;
  existing helper tests now run each call against its own empty store
  (`tests/store_support.py`). Suite ~100 s locally (was ~47 s): every
  coordinated action does real git pushes.
- An independent review of the branch found five bugs, all fixed with
  regression tests: a lookup failure right after a POST could free the intent,
  and the rerun would buy again; a released `recorded` intent was resolved
  before expiry + skew; a store failure during recovery crashed the monitor;
  a failed push 1 after a recovery push raised `KeyError` and kept the lease;
  one unrestorable gap blocked every later action.
- Not verified: behaviour against GitHub's real push rejection through the
  cloud proxy, and a real lost response — both are #112 drills (real lost
  response and direct-to-GitHub rejection: green on 2026-10-13, see below).

## Session 2026-10-13: routine text for the coordinator (#144)

Text and wiring tests only; no code, no broker calls. #78 is still open, so
`routines/` and `.claude/commands/` were edited identically.

- Mutating copies (market-open, midday, `/trade`) carry a `## Coordinator
  exits (ADR 0010)` block, and every `ENTRY_EXIT` / `CLOSE_EXIT` /
  `REPLACE_EXIT` legend ends with 10/11 (nothing changed: no further mutation
  this run, email) and 12 (acted, outcome not recorded: do NOT rerun, log the
  JSON, email, `--incident` + `--intent`). `/trade` gained the entry and close
  legends it lacked. Buy validation handles `validate_order` exit 10; the
  market-open `protection_monitor --dry-run` handles exit 10 and any other
  exit.
- Every `.claude/commands` call to a script that touches the store carries
  `TRADING_STATE_STORE=local` (each Bash call is a fresh shell, so no
  `export`).
- Read-only routines run `coordinator.py status` (STEP 2b) and pass each
  non-terminal intent, stale lease and recent takeover (24 h, 72 h on a
  Monday, 7 days for the weekly review) to `run_record.py finish --incident`.
- Wiring tests: `tests/test_t3_unprotected_windows.py` (legends, buy exit
  10, monitor exits, local prefix) and `tests/test_run_record.py`
  (read-only status step).
- Not verified: an agent following the new text in a live routine; the
  takeover windows can report one takeover twice, which is intended.

## Session 2026-10-13: freeze-rehearsal drills (#112)

Baseline `234ccad`. Runbook `docs/DRILLS.md`: 11 scenarios with induce /
expected terminal state / evidence / mode, the CI tests behind each, the
2026-10-13 live session's verdicts, and the freeze criterion with the tag
command (the owner tags; no agent does).

- Code: the state-store branch follows `ALPACA_PROFILE` (`main` production,
  `drill-state` drill; `scripts/state_store.py: store_branch`), used by the
  coordinator, run records and the store CLI. Before this, a drill would have
  held production's lease and reserved its capacity. `drill-state` is seeded on
  origin; never merge it. `run_record.py` accepts `--routine drill --trigger
  local`, drill profile only.
- Tests: `tests/test_drills.py` (store isolation, drill run records,
  cross-midnight lost entry, missing history ×2, undelivered coordinator alert,
  and three checks that the runbook names real tests and records every live
  drill's verdict). `tests/store_support.make_origin` seeds `drill-state`.
- Live session `drill-20261013T132842Z-c54427` on `PA3YVVX6ERYG`: 6 of 8 live
  drills green (two writers incl. killed holder, crash after cancel, lost
  response, unavailable store, failed alert delivery, version mismatch). Red:
  drill 8 → #155 (fresh quotes refused when the host clock lags), drill 9 →
  #156 (heartbeat matches monitor runs by `name`, which is now the run-name,
  so it sees none). Account left flat and stop-free.
- Not verified: non-fast-forward rejection through the cloud proxy (local
  session pushed directly).
- Next: #155, #156, then the full live rerun and the owner's tag (child
  ticket on #93).

## Session 2026-09-20: execution controls for v2

- `risk_engine/versions.py`: `StrategyParams` with `V1` (frozen) and `V2`;
  `STRATEGY_VERSION` read once per CLI (`validate_order`, `validate_mutation`,
  `validate_stop_change`, `build_oto_order`, monitor, entry). Engine functions
  take `params`; v2 adds sector cap, sector-ETF exclusion, re-entry cooldown,
  7% entry band, conversion only at +5%, ladder 7% at +15%.
- `risk_engine/blotter.py` + `scripts/blotter.py`: FIFO round trips from
  `/account/activities/FILL` (`alpaca.sh activities`), `--check` against
  positions, `--cooldown`, `--sector-streaks`. Cooldown in `validate_order.py`
  comes from fills, not markdown.
- `scripts/heartbeat.py` + `.github/workflows/heartbeat.yml` (added 2026-09-29):
  daily liveness check after the close — every expected routine commit for a
  trading day (Alpaca calendar), one monitor success, no dashboard/tests
  failure — emails on a miss; also emails immediately when a watched workflow
  fails (`workflow_run`). Closes the "merged but never observed" gap.
- `risk_engine/monitor.py` + `scripts/protection_monitor.py` +
  `.github/workflows/protection-monitor.yml`: cron every 30 min on weekdays,
  but GitHub throttles it to ~2 runs/day (observed Sep 21-29: ~17:45Z and
  ~21:15Z); treat as a twice-daily coverage check, not a 30-min guard. No
  Claude, no ledger; renew, convert (v2: only at +5%), tighten per ladder;
  HOLD/STANDING reported; exit 5/7/8 emailed. Acts only via `replace_stop`.
  Service level since 2026-10-12 (ADR 0007): 90-min maximum protection-check
  delay during market hours, measured by the heartbeat from run history and
  reported as stale windows; alerts are delivery-verified (`email.sh` reads
  the Resend `last_event`; exit 9 = alert lost); market-open commits
  `market-open no-trade <date>` on no-trade days. Meeting the level needs an
  external dispatcher (owner decision, see PR for #103).
- `scripts/submit_entry.py` (`en-<day>-<sym>`, lookup before submit) and
  `scripts/close_position.py` (`cl-<day>-<sym>`, cancel confirmed, sell
  confirmed, exit 8 if naked). Both wired into `routines/market-open.md`,
  `routines/midday.md` and the `.claude/commands` copies as the only buy and
  exit paths. `memory/SECTORS.json` added. ADR 0003 records the design.
- Not done: routine wiring for rule 15; secrets for the workflow; any broker
  call, email, order or push from this session (all tests are offline).

## Verification on 2026-09-20

| Check | Result |
|---|---|
| `env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'` | 358 passed; 21 integration tests deselected |
| `.venv/bin/python scripts/doctor.py` | ok; last log 2026-09-18; dashboard current; ledger not configured; broker not verified |
| `.venv/bin/python scripts/build_dashboard_data.py --check` | Committed generated data reproduced |
| `git diff --check` | Clean |

The Postgres integration suite, the broker, the email path and the GitHub
Actions workflow were not exercised. `STRATEGY_VERSION` is unset in every
cloud routine until the owner sets the repository variable, so cloud runs
stay on v1.

## Session 2026-09-19: paper results audit

- Pulled the paper account's full order, fill, fee and portfolio history
  read-only and reconciled it to equity exactly. Results, benchmark comparison,
  trade table and dated operational events are in
  [research 0006](research/0006-paper-results-reconciliation.md).
- Wrote [STRATEGY-ASSESSMENT.md](STRATEGY-ASSESSMENT.md): keep/modify/discontinue
  per rule, evaluation of the deployment backstop, $10,000 implications, and
  a predeclared funding criterion. Recommendation: do not fund on the current
  rulebook; freeze it as v1, specify v2, finish execution controls, run v2 in
  paper at $10,000.
- Live-state item for the next trading session: XLB's renewed fixed stop is
  2.4% below the Sep 18 close, inside rule 7's 3% buffer. The rulebook has no
  instruction for this case.
- Wrote [STRATEGY-SPEC.md](STRATEGY-SPEC.md): v1 frozen with its rulebook
  and prompt hashes at `07603ef`, per-rule enforcement class (engine, script,
  advisory), v1 known gaps and shadow procedure; v2 rules 1–15 with the
  engine/script/monitor target for each, $10,000 universe, decision-record
  fields, benchmarks, segment-start checklist, and the execution controls v2
  depends on. Model ID is not recorded anywhere in the repo and must be
  captured per run before a segment is scored. Two owner decisions are open
  in section 7 (review-threshold definition; target trim vs delete).
- Next engineering steps: version-parameterise the engine constants (stop
  band, trail ladder, sector cap, cooldown), productize the fill-based
  reconciliation as a script with tests, build the protection monitor that
  runs without Claude and without the ledger, move test orders out of the
  scored account.
- No orders, notifications, pushes or configuration changes were made.

## Session 2026-09-19: project access and workflow

- Corrected the distinction between the running paper trial and the proposed
  next evaluation phase following the owner's clarification. Reviewed strategy
  and execution gaps for a staged live pilot; recommendations do not change
  trading rules or authorize orders.
- Tried the Claude routines website through web access; it did not expose the
  private routine configuration. Plugin discovery found no suitable authenticated
  browser/routines integration. The owner subsequently supplied a screenshot:
  all five project routines are marked Active, and their displayed times match
  the documented Chicago schedules converted to Jerusalem for September 18.
  Full saved prompts, selected environment and timezone configuration remain
  uninspected. See [routine verification](ROUTINE-VERIFICATION.md).
- GitHub commits confirm research, midday, EOD and weekly outputs through
  September 18. Latest relevant tests, dashboard generation and Pages deployment
  succeeded. Local checkout was fast-forwarded while preserving our edits.

- All 80 files tracked at the inspected baseline were readable, including
  hidden command and CI files. The working tree was initially clean.
- Added root `AGENTS.md` with a short startup sequence, task map, project
  constraints, validation commands, and handoff maintenance instructions.
- Replaced duplicated Claude instructions with a pointer to the shared guide.
  README and project memory now distinguish engineering from trading startup.
- These onboarding changes are local and uncommitted. No scheduler
  update, broker operation, email, Git push, or deployment was performed.

## Verification on 2026-09-19

| Check | Result |
|---|---|
| `env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'` | 287 passed; 21 integration tests deselected at `1d2d267` |
| `.venv/bin/python scripts/doctor.py` | Passed; dashboard current; latest parsed EOD 2026-09-18 after synchronization; process ledger configuration absent; broker not verified |
| `.venv/bin/python scripts/build_dashboard_data.py --check` | Committed generated data reproduced |
| `.venv/bin/python -m pytest -q tests/test_build_dashboard_data.py` | 24 passed after synchronization to `07603ef` |

The Postgres integration suite was not run in this session. Broker credentials,
current positions/protection, full cloud configuration, hosted ledger availability,
and rendered published dashboard contents were not verified. The screenshot
confirms displayed schedules; GitHub confirms successful Pages deployment. Local file access does not
establish external service access. Credential values were not inspected.

## Keeping this useful

At the next material engineering handoff, replace stale sections here with the
new baseline, changes, verification, and next work. Check Git for changes since
the baseline before acting. Keep task routing in `AGENTS.md`, design rationale
in ADRs, and trading history in `memory/`; avoid copying those documents here.
