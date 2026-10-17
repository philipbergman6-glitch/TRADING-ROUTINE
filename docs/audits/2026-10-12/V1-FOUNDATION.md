# V1 foundation assessment before building v2

Assessed 2026-10-12 at code baseline `73da017`. The active system is rulebook v1.1 with v1 engine parameters. The owner wants to finish a high-quality v1 foundation before building v2. This is different from readiness to activate the v2 paper experiment.

**Verdict: retain the architecture and complete a bounded v1 hardening milestone. Overall v1 project grade: 6.5/10.** The deterministic core is credible; execution coordination, recovery, operational verification and accounting need more work before adding strategy complexity. v2 design can proceed now; its implementation should build on the hardened boundary. A rewrite is not justified by these findings.

These scores are engineering judgments, not a measured percentage of completion or a prediction of investment returns.

| Area | V1 grade | Reason |
|---|---|---|
| Architecture | 7.5/10 | Pure Decimal engine, broker adapter and ledger separation are good. Caller-coordinated execution lacks one durable account-wide owner. |
| Execution flow | 6/10 | Exact-payload checks and resumable stop/exit helpers exist. Recovery identity and incident classification still have defects. |
| Reliability | 5.5/10 | Protection checks and heartbeat provide value, but scheduling and cross-process operation have incomplete guarantees. |
| Tests | 7.5/10 | Fast offline suite, real Postgres CI and wrapper-level stop tests. Lifecycle scenarios still escape coverage. |
| Policy clarity and maintenance | 6/10 | Pinned rulebook and documented deferrals help. Several rules depend on prose judgment; standing-stop semantics and enforcement claims are inconsistent. |
| Accounting and observability | 5.5/10 | Fill-based quantity checks and useful dashboard; full lifecycle/equity reconciliation and run provenance are not automatic. |

## Correction of the first assessment

The previous 5/10 was a v2 activation score and should not have been presented as the answer to this request.

| Earlier finding | Correct classification |
|---|---|
| 34-day cooldown history failure | V2-only defect; V1 returns before reading that history. Explicitly verified offline. |
| SPY exemption and weekly counting | V2-only requirement. V1 has no fallback exemption. |
| $10–$500 universe, broad ETF exclusion, momentum calculation, timed sector ban | New v2 requirements. Their absence is not failure to implement the v1 contract. V1's advisory sector rules still need honest labeling. |
| V1 −7% cut, 10% initial stop, leadership-add mandate | Correct v1 behavior, not defects merely because v2 changes them. |
| No clean $10,000 scored account, v2 trim decision or 30-session segment | Future experiment setup, not prerequisites to begin building v2. |
| Same-day exit identity, lack of durable coordination, sparse monitoring, version guard gap | Shared foundation issues, relevant to v1. |

## Confirmed v1 recovery defects

The [v1 offline probes](repro_v1_foundation.py) produce **2 passed, 2 failed** at the baseline:

```bash
.venv/bin/python -m pytest -q docs/audits/2026-10-12/repro_v1_foundation.py --tb=short
```

The passing probes confirm that v1 does not read v2 cooldown history and does not impose the v2 price ceiling. Failures assert intended recovery behavior, not current broker incidents.

1. **A completed exit can conceal a later position.** `scripts/close_position.py` treats a filled `cl-<day>-<symbol>` as authoritative before checking holdings. V1 permits a same-day new entry, including the explicit entry tag mechanism, so a new close request can incorrectly report `already_closed`. Completion must be tied to the position lifecycle and reconciled holdings.
2. **Recovery can downgrade an unprotected incident.** If a previous process canceled protection and died, a rerun sees the held position and no stops. A preflight refusal returns exit 3, although the CLI contract describes exit 3 as a refusal with protection still resting. This should remain an incident until coverage or exit is confirmed. Error classification must derive from broker coverage, not just mutations performed in this process.

Related risks require drills rather than claims of observed failure: entry IDs change at UTC midnight; independent processes can validate against the same available capacity; partial fills can change remaining quantities during cancellation. Existing tests cover many stop restoration paths but do not prove all these interleavings.

## Six bounded work packages

This is a medium engineering hardening milestone: roughly six reviewable work packages, potentially split into smaller PRs. A calendar estimate would depend heavily on scheduler access and the chosen durable coordinator; there is not enough implementation design here to give a defensible fixed duration.

| Order | Work | Size | Done when |
|---|---|---|---|
| 1 | Correct exit identity and incident classification | Small to medium | Both new v1 regressions pass; repeated close, new same-day position, missing stop and rejected recovery are exercised through the real boundary. |
| 2 | Add durable execution coordination | Largest package | Intent survives restart and midnight; one account-wide owner serializes competing writers and reserves capacity; duplicate/lost-response scenarios cannot silently create extra orders. A process-local lock is insufficient across cloud routines and Actions. |
| 3 | Make protection monitoring and alerts dependable | Medium | Define a maximum protection-check delay, verify the deployed scheduler meets it, detect stale monitoring, verify alert delivery, and record no-trade market-open outcomes. An independent daily heartbeat cannot certify a 30-minute guard. |
| 4 | Align v1 policy, instructions and version enforcement | Small to medium | Every v1 rule has an explicit engine/script/advisory classification and owner. Cloud/local instructions agree; all execution paths check the approved version. Resolve contradictory standing-stop guidance without silently changing the pinned strategy. |
| 5 | Make records and accounting reproducible | Medium | Every routine records run ID, code/rulebook/prompt/model provenance, result and incident state; broker fills, fees and cash movements reconcile to holdings/equity; dashboard distinguishes current reconciled data from historical curated material. |
| 6 | Rehearse release and recovery | Medium verification effort | Isolated paper drills pass for concurrency, lost responses, crash after cancel, partial fills, service outages, version mismatch and missed monitor; deployed configuration is checked and recovery instructions are usable. |

Package 2 should reuse the current risk engine and broker adapter. It needs a durable store shared by all writers; simply setting `DATABASE_URL` does not supply execution coordination. The store, locking/reservation model and recovery transitions need a focused design before implementation. No microservice split is required just to achieve this.

For package 4, distinguish behavior preservation from strategy decisions. The current v1 rulebook permits a fixed entry leg only transiently, while routines deliberately hold some fixed stops to avoid lowering the floor. Rule 7 does not clearly distinguish a new stop placement from price drifting near an existing stop. Rule 10's sector-failure instruction and rule 14's composition exception rely on the agent rather than deterministic enforcement. These need a clear contract; changing trading policy requires a versioned decision, not an incidental refactor.

For package 5, preserve historical evidence. Existing logs need provenance and reconciliation, not invented backfilled forecasts or model identifiers. Historical uncertainty should remain labeled. Structured run records and automated accounting can be added without migrating every narrative note to SQL.

## What should remain

- The deterministic, I/O-free risk engine and Decimal money boundary.
- Paper endpoint restrictions, exact-payload validation, fresh quote and pending-buy checks.
- OTO entry protection, actual resting stop-floor preservation and resumable restoration.
- Existing tests, real Postgres integration checks, documentation and ADR approach.
- Markdown as human-readable research and narrative, with structured authoritative records for execution and accounting.

Do not delay the foundation milestone for a dashboard redesign, multi-user permissions, a framework migration, additional strategies, or implementing v2-only rules. “Best possible v1” should mean a reliable, explainable paper system with proved recovery, not unlimited feature expansion.

## Gate for starting v2 implementation

Freeze a v1 engineering baseline after the recovery defects are fixed, durable coordination is proved, deployed monitoring and alerts meet the agreed service level, and accounting/run records explain every operation. Require the normal suite plus the new lifecycle/concurrency/recovery checks to pass and complete an observed deployment rehearsal.

No 30-session v2 evaluation or evidence of v2 profitability is needed to begin building v2. The existing 30-session requirement belongs to the later scored experiment. Software quality and trading edge remain separate questions; the latter was not established by this engineering diagnosis.

Verification reused from the same unchanged code baseline: 384 local offline tests passed; dashboard reproduction and doctor passed offline; latest CI ran 21 passing Postgres integration tests. The monitor's last inspected October 9 report showed coverage under v1, but current broker state and full private cloud configuration were not inspected. The v1 probes above were additionally run for this corrected scope. No execution code or strategy was changed.
