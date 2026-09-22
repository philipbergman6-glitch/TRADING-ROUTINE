# Engineering handoff

Updated: **2026-09-20**. Baseline for this session: verified GitHub main
**`8de4a1b`** (PR #82, the versioned strategy spec). This session's work is on
branch `exec/controls-v2` and lands as one squash-merged PR. GitHub issue
status was not checked.

## Where the project stands

The paper system has a pure risk engine, a broker mutation gate, resumable
protective-stop replacement, an optional Postgres ledger, scheduled agent
instructions, and a dashboard generated from markdown logs. It is still an
experimental research platform. **Paper trading is already running**: on
2026-09-19 the owner confirmed approximately three months of operation through
Claude Desktop cloud routines. The separate versioned evaluation specification
in `PAPER-EXPERIMENT.md` is a proposed next phase, not the start of paper trading.

The September 17 audit has already led to fixes. Start with
[implementation status](audits/2026-09-17/IMPLEMENTATION.md), not the older
[diagnosis](audits/2026-09-17/REPORT.md), when identifying remaining work.
Implemented controls include exact paper endpoints, exact-payload validation,
fresh-quote/pending-buy gates, preservation of the actual resting stop floor,
bounded order-history queries, and resumable stop replacement/restoration.

## Next engineering milestone

The execution controls in [STRATEGY-SPEC.md](STRATEGY-SPEC.md) section 6 now
exist in code with offline tests (see the status column there). Remaining
before the 30-session $10,000 v2 paper run:

1. **Owner configuration.** Add repository secrets `ALPACA_API_KEY`,
   `ALPACA_SECRET_KEY`, `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM` and the
   variable `STRATEGY_VERSION` (`v2` for the run; unset means `v1`), then
   trigger `protection-monitor` by `workflow_dispatch` with `dry_run=true` and
   read the report. The workflow has not been observed running.
   Set `STRATEGY_VERSION=v2` in the cloud routine environment too, and flip
   `Active strategy version` in `memory/TRADING-STRATEGY.md` to `v2` in the same
   change: `scripts/strategy_version.py` (run first by market-open, midday,
   /trade) hard-fails when the two disagree, so an unset variable can no longer
   trade v1 rules silently.
2. **Owner decisions** in spec section 7 (review threshold definition; rule 15
   trim vs delete). Rule 15 has no script until decided.
3. **Sector data.** `memory/SECTORS.json` holds the symbols traded so far; each
   v2 candidate needs its GICS sector recorded before `validate_order.py`
   accepts the buy.
4. **Segment start.** Move test orders out of the scored account, record the
   model ID per run, run the segment-start checklist in spec section 5.
5. Still open by design: cross-process reservations / durable intent store
   (#19, #26); the cancel→place window is recoverable, not atomic (#40).

## Latest session: execution controls for v2 (2026-09-20)

- `risk_engine/versions.py`: `StrategyParams` with `V1` (frozen) and `V2`;
  `STRATEGY_VERSION` read once per CLI (`validate_order`, `validate_mutation`,
  `validate_stop_change`, `build_oto_order`, monitor, entry). Engine functions
  take `params`; v2 adds sector cap, sector-ETF exclusion, re-entry cooldown,
  7% entry band, conversion only at +5%, ladder 7% at +15%.
- `risk_engine/blotter.py` + `scripts/blotter.py`: FIFO round trips from
  `/account/activities/FILL` (`alpaca.sh activities`), `--check` against
  positions, `--cooldown`, `--sector-streaks`. Cooldown in `validate_order.py`
  comes from fills, not markdown.
- `risk_engine/monitor.py` + `scripts/protection_monitor.py` +
  `.github/workflows/protection-monitor.yml`: every 30 min on weekdays, no
  Claude, no ledger; renew, convert (v2: only at +5%), tighten per ladder;
  HOLD/STANDING reported; exit 5/7/8 emailed. Acts only via `replace_stop`.
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

## Latest session: paper results audit (2026-09-19)

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

## Earlier session: project access and workflow

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
