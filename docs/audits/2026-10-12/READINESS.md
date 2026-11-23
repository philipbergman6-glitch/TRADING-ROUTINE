# Trading Routine v2 readiness assessment

**Scope correction:** this assessment answers readiness to activate and score v2, not the owner's intended question of whether v1 is ready to serve as the foundation for building v2. Use [the corrected v1 foundation assessment](V1-FOUNDATION.md) for project grades and prerequisite work. The v2 findings remain future implementation evidence; they must not be counted as current v1 defects.

Assessment date: 2026-10-12. Code baseline: `73da017e15fdb5d2ee283760e8032b634910b673`, initially clean `main`. Scope: the proposed $10,000 v2 paper evaluation in `docs/STRATEGY-SPEC.md`, not live trading.

**Verdict: do not start the scored v2 segment yet.** The project has a sound deterministic core and meaningful safety controls, but v2 is only partially implemented. Switching the environment variable would expose execution bugs and run conflicting policies. Continue engineering toward v2; a wholesale rewrite is unnecessary.

Grades below are engineering judgments against the proposed phase, not measured probabilities of safety. Scale: 9–10 ready with strong proof; 7–8 sound with bounded gaps; 5–6 material gaps; below 5 incomplete. Overall readiness is constrained by blockers, not an average that lets good documentation compensate for broken protection.

| Area | Grade | Basis |
|---|---|---|
| Architecture | 7/10 | Pure Decimal risk engine, explicit broker boundary, injectable adapters, optional ledger. Missing durable account-wide execution owner; protection depends on entry-only history checks. |
| End-to-end flow | 5/10 | Resumable scripts exist, but routines still mix v1 and v2 rules and the agent coordinates recording/retries. |
| Operational reliability | 5/10 | Coverage monitoring and heartbeat work; actual monitor cadence, recovery identity and version enforcement remain insufficient. |
| Tests and verification | 7/10 | 384 offline tests pass; 21 real Postgres tests pass in CI. New boundary probes expose gaps hidden by the green suite. |
| v2 policy completeness | 4/10 | Some constants implemented; fallback, sector lockout, momentum/universe checks and target decision remain incomplete. |
| Research and measurement | 4/10 | Good prospective specification; no complete pinned v2 segment, structured decision contract or reproducible scoring pipeline established. |
| Overall phase readiness | 5/10 | Useful experimental platform, not ready to score v2. |

## Evidence and limits

- Local `env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'`: **384 passed, 21 deselected**, 8.19 seconds.
- Offline doctor: `ok: true`, dashboard current, last parsed log 2026-10-09; `broker_verified: false`, ledger unconfigured in this process.
- Dashboard reproduction check and `git diff --check`: passed.
- [Latest CI at the assessed commit](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/38154362445): risk job 383 passed, 1 skipped, 2 deselected; ledger job **21 passed**, with the no-skips guard passing. Integration tests were observed in CI, not rerun against a local database.
- [October 9 monitor](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/38002673365): non-dry v1 run, coverage OK, no actions; XLP conversion held to preserve the stop floor. This is dated operational evidence, not current broker certification.
- Recent monitor history: October 6 at 18:50/22:56 UTC; October 7 at 19:15/23:41; October 8 at 19:11/23:51; October 9 at 18:42/23:05. The 30-minute cron does not establish a 30-minute service guarantee. Cause of the sparse execution was not established in this audit.
- [October 9 CI failure](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/37991483501) was an unauthenticated Docker image pull rate limit. The [daily heartbeat](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/38014993904) correctly reported it; that heartbeat failure is evidence of detection, not a missed routine.
- The repository variables API returned no `STRATEGY_VERSION` entry. Rulebook and pins declare v1.1 using the v1 engine. Full private cloud prompts, model selections and environment settings remain unverified.

No broker mutations, workflow dispatches, notifications, strategy changes or deployments were performed. The assessment does not establish investment edge or real-money readiness.

## Reproduced blockers

The archived [offline probes](repro_v2_readiness.py) assert intended behavior, so failures are expected at this baseline. They sit outside `tests/` to avoid silently adding a failing normal suite. Run from the repository root:

```bash
.venv/bin/python -m pytest -q docs/audits/2026-10-12/repro_v2_readiness.py --tb=short
```

Result: **8 failed**. These represent five finding groups, not eight independent production incidents. Broker inputs are synthetic; all execution remains offline.

### 1 Long-held exits can disable v2 protection operations

**Priority P0 before v2 activation.** `scripts/validate_order.py:76` reconstructs cooldown state using only the last 34 days of fills. A buy before that cutoff followed by a recent sell becomes a sell without an opening lot; FIFO reconstruction raises and the CLI exits 4.

`read_portfolio()` computes this state for every mutation, including sells and stop cancellations (`scripts/validate_mutation.py:108`). The probes show both the cooldown failure and refusal of an unrelated MSFT protective-stop cancellation after an AMD sale. The same dependency affects protective placements/restorations. Resting stops are not canceled by these probes; the concern is disabled intervention and recovery.

Fix: use full history or a reconciled opening-lot checkpoint, then isolate entry eligibility data from risk-reducing operations. Acceptance: old-entry/recent-exit scenarios, including unrelated symbols, cannot disable required protection or exits.

### 2 SPY fallback activity consumes the active-entry allowance

**Priority P1.** `trades_this_week()` counts all filled buys. The engine exempts a proposed SPY buy, but does not remove earlier SPY buys from the count used for the next active entry. Three SPY fills make an otherwise eligible AMD buy fail as trade four.

Fix the broker-derived count to use version-aware active entries. Cover mixed SPY/active activity and partial fills; verify the specification's meaning of an entry versus a top-up.

### 3 The v2 universe is only partially checked

**Priority P1.** `risk_engine/engine.py:196` rejects eleven named SPDR sector ETFs, not every ETF/ETN excluded by section 3.2. Pure-engine probes accept VTI and hypothetical stock prices of $5 and $600. The mutation boundary checks `us_equity`, active/tradable status and fresh asks, but carries no broader instrument classification, $10–$500 filter or 20-session dollar-volume evidence.

Fix: establish a dated eligible-universe record and make the execution path require it. Acceptance: generic ETFs/ETNs, ineligible listing types, out-of-range prices and insufficient liquidity are rejected or explicitly excluded by a revised pinned specification.

### 4 Exit identity is a day and symbol, not a position lifecycle

**Priority P1.** `scripts/close_position.py:124` returns `already_closed` for a prior filled `cl-<day>-<symbol>` before checking whether a new position now exists. A same-day re-entry can therefore be left open despite a new close request. v1 permits re-entry; v2 explicitly exempts SPY from name cooldown, so the architectural case remains relevant.

The archived probe uses AMD to demonstrate the execution helper's behavior; it does not claim the normal v2 entry gate permits an immediate AMD re-entry. Separately, entry IDs depend on the current date: retrying after UTC midnight changes identity. That is a code-level risk, not a reproduced duplicate broker fill.

Fix: persist an intent/position-lifecycle identifier across retries and dates; reconcile current holdings before declaring an exit complete. Drill lost responses, rejected attempts, partial fills, process death and same-day new positions.

### 5 The independent monitor bypasses the rulebook version check

**Priority P1.** `scripts/protection_monitor.py:90` reads environment parameters but never verifies the declared rulebook/pin. Its workflow also omits `strategy_version.py`. The probe demonstrates a v2 dry-run succeeding while the repository's v1.1 rulebook fails the version check. Mutation CLIs likewise select parameters without binding them to the rulebook pin.

Fix: bind every autonomous execution path to an approved version consistently, while preserving emergency protection during configuration failures. Acceptance must cover mismatched and missing environment variables across both cloud routines and the independent monitor.

## Missing policy and flow

| Requirement | Current gap | Completion evidence |
|---|---|---|
| Rules 2/12, SPY fallback | `deployment_status.py` still implements the v1 three-session leadership-add mandate; pre-market/market-open still direct forced leadership/sector ETF adds. No dated cash-condition expiry handling. | Deterministic fallback/cash decision, versioned cloud and local instructions, and EOD compliance check. |
| Rule 9, momentum | No implementation found for the specified trailing 20-session sector-ETF return versus SPY filter. Current research instructions use broader/YTD momentum. | Reproducible daily-bar calculation saved with each candidate, including rejected candidates. |
| Rule 10, sector lockout | `sector_failure_streaks()` computes counts; the portfolio/engine has no 20-session sector-ban input or rejection path. | Timestamped sector-ban state, expiry and entry refusal tests. |
| Rule 14, session semantics | `sessions_between()` counts weekdays, including exchange holidays. Its comment claims conservative behavior, but overcounting lets cooldown expire early. All exits, including winners/partial realizations, can feed cooldown rather than only classified stop-outs/cuts. | Exchange-session calendar and explicitly defined exit classification; tests for closures, winners and trims. |
| Rules 5/6, protection transitions | Midday still commands a manual −7% cut; convergence sections lack the +5% gate; `/trade` still specifies a 10% initial stop. Monitor uses current marks although the spec says the position “closes” at +5%. | Decide close-versus-intraday semantics and align every caller; test whole flows under both versions. |
| Rule 15, target | No target field validation or trim executor; owner decision remains open. | Either implement one-third trimming with residual protection, or delete the rule in the pinned v2 spec before evaluation. |
| Review threshold | Initial-capital versus peak-to-trough loss threshold remains undecided. | One defined rule, owner decision and tested pause/resume behavior. |

The status handoff's claim that section 6 controls exist is too broad. Stable client IDs are useful, but do not satisfy “durable intent before submit”; fills reconstruction is useful, but does not constitute full broker lifecycle recording.

## Architecture and reliability work

Keep the pure risk engine and version data. Keep the adapter, stop-floor checks and restoration logic. Improve the execution boundary around them:

1. One account-wide execution coordinator must serialize competing routines and monitor actions, reserve capacity, persist intent before submission, and reconcile outcomes. The workflow concurrency group only serializes monitor jobs with each other. It does not protect against a cloud routine acting concurrently.
2. Separate entry prerequisites from emergency exit/protection prerequisites. An optional research/history dependency must not disable a risk-reducing operation.
3. Record the complete lifecycle at the execution boundary. Current ledger recording is optional and caller-coordinated, with submission/stop responses but no complete automatic fill/cancel/reconciliation loop. A database being enabled alone would not solve this.
4. Give monitoring an explicit maximum delay, measure that delay and alert on staleness. Current heartbeat accepts one successful monitor run per day and exempts market-open; commits prove an output was saved, not that every intended operation completed. Capture an outcome for no-trade market-open runs too.
5. Verify post-action holdings and coverage before declaring convergence. Distinguish permitted HOLDs from failure to meet a due transition; `worst_exit()` does not inspect HOLDs, and notification subprocess failures are not consistently propagated.

The agent still has credentials and can edit the checks. This is an application correctness boundary, not independent credential isolation. For this single-user paper phase, tenancy/RBAC or a UI rewrite are not the pressing work.

## Research validity and the release gate

The repository describes a worthwhile experiment but cannot yet produce the complete evidence it promises. Before session one:

1. Resolve target, loss threshold, trigger timing and benchmark inconsistencies. `PAPER-EXPERIMENT.md` asks for a mechanical sector-momentum reference while `STRATEGY-SPEC.md` names a v1 shadow; specify whether both are required and how each operates.
2. Finish the execution defects and missing v2 rules above. Build rule-to-test traceability at the CLI/routine seam, not just pure-engine examples.
3. Run failure/restart drills on an isolated engineering paper account: simultaneous proposals, cross-midnight retry, crash after cancel, ambiguous POST, partial fill, missing history, unavailable ledger, stale quote, missed monitor and failed alert delivery.
4. Verify deployed thin prompts, model IDs, strategy configuration and actual monitor service level. Record code, rulebook and prompt hashes. No v2 pin currently exists.
5. Establish the clean $10,000 scored account and experiment ID without test-order contamination. Preserve the existing account's historical evidence separately.
6. Require structured append-only candidate records with observation time, sources, sector/filter, forecast probability/horizon, invalidation, proposed prices, verdict and version/model provenance. Add operating costs and incident timing.
7. Produce reproducible daily broker-equity reconciliation and the agreed benchmark/shadow series. Current quantity reconciliation is useful but does not establish complete equity, fees, cash-flow or performance accounting.

Only then begin the **30 consecutive trading-session operational gate** with complete records, no unexplained reconciliation differences and successful failure/restart drills. The 30 sessions are the evaluation after readiness work, not a prerequisite to starting session one. Strategy profitability remains unproven and requires the separately specified comparisons after costs.

No implementation was changed by this audit. The archived failing probes should become normal regression tests as the corresponding fixes are made.
