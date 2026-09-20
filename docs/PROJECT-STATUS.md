# Engineering handoff

Updated: **2026-09-19**. Local `main` is synchronized to verified GitHub main
**`07603ef`**. Nine commits since the original inspection at `1d2d267` update
trading/research/weekly logs and dashboard data through September 18; execution
code and routine instructions are unchanged. GitHub issue status was not checked.

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

Complete durable execution and independent reconciliation while continuing the
existing paper trial, then apply the [versioned evaluation](PAPER-EXPERIMENT.md).
The owner now wants a path to testing with real money; recommendations are in
[LIVE-READINESS.md](LIVE-READINESS.md). No live capability has been enabled.
The owner specified $10,000 initial capital and $4,000 maximum acceptable loss
(40%) on 2026-09-19. The readiness plan records that tolerance and a proposed
earlier review threshold; these are not implemented trading controls.
The documented remaining work is:

1. An account-wide execution coordinator: durable intent, cross-process
   reservations, stable buy idempotency, and recovery after ambiguous outcomes.
2. Recovered cancel-to-close exits and independently scheduled protection
   monitoring. Stop replacement is recoverable, but its cancel/place window
   is not atomic.
3. Complete broker lifecycle recording and accounting reconciliation. The
   optional ledger currently records only part of the lifecycle; historical
   markdown is evidence, not independently reconciled accounting.
4. Verify actual scheduler prompts/configuration and runtime version reporting;
   then establish the experiment's versioned inputs and proof gates
   ([STRATEGY-SPEC.md](STRATEGY-SPEC.md) now defines the inputs).

These are existing documented priorities, not work completed by the onboarding
changes. Detailed scope and limitations remain in the implementation status
and [architecture](../ARCHITECTURE.md).

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
