# Path from the running paper trial to a live pilot

Assessment: 2026-09-19, code baseline `1d2d267`. Recommendations only;
strategy rules, broker endpoints, credentials, and schedules are unchanged.

## Starting point

The owner confirms approximately three months of paper trading through Claude
Desktop cloud routines. The repository contains trading history, not merely a
prototype specification. Retain it as evidence. A new strategy version would
begin a new measurement segment, not erase the earlier trial.

The existing software intentionally rejects real-money endpoints in both the
adapter and risk engine. A live pilot needs an explicit, separately configured
execution path; changing credentials or removing one guard is insufficient.
The previous local verification passed 287 non-integration tests, but neither
the full private cloud configuration nor current broker state was inspected here.
Subsequent screenshot and GitHub verification confirms active schedules and
committed outputs through September 18; see [routine verification](ROUTINE-VERIFICATION.md).

The provisional historical audit reports +2.83% equity change through September
16, a 10.69% maximum observed EOD drawdown, and roughly 1.87 percentage points
of underperformance across the separate weekly comparison ending September 11.
These periods differ; reconstructed entries, estimated benchmark weeks, and
unreconciled accounting prevent treating those numbers as certified returns.
Source: [audit metrics](audits/2026-09-17/metrics.json).

A concrete reconciliation target: the September 17 XLE entry in
`memory/TRADE-LOG.md` describes converting a $57.56 fixed stop to a $57.51
trailing stop, then says no stop was lowered. That is an internal inconsistency
in the record, not proof of the broker sequence or a failure in the current
code version. Resolve it against broker events and the deployed commit before
using the log's compliance claims as live-readiness evidence.

## Recommendation: keep research in routines, make execution a service

Keep the existing routines for candidate research and reporting. Send structured
proposals to a small Python execution service with durable Postgres state. It
should own broker credentials, validate current state, reserve account capacity,
persist intent before submission, and reconcile outcomes by stable client order
ID. Deploy a reviewed code version rather than letting a research session edit
or replace the executing service. A single service plus database is sufficient;
a distributed rewrite is not required.

Run protection checks and the agreed exit triggers independently of the LLM.
An external heartbeat should detect a stopped execution service. Broker-held
protection must continue to exist when research or monitoring is unavailable.
Provide a pause-new-entries control that preserves protective orders, plus a
separate, tested procedure for closing positions safely.

Reason: Claude documents schedule stagger and usage limits that can reject
runs. These routines are useful research automation, but that behavior is
unsuitable as the only time-sensitive exit mechanism. Desktop-created cloud
routines run in the cloud; local Desktop tasks are a different mode. The
owner's actual environment and run history still need inspection.
[Anthropic routine documentation](https://code.claude.com/docs/en/routines)

## Redefine the strategy explicitly before scaling

The current rulebook defines numerous constraints but leaves much of selection
to interpretation. Adopt a versioned strategy contract with a fixed universe,
momentum measurement, ranking/rebalance schedule, entry conditions, position
sizing, exits, and permitted overrides. Record rejected candidates as well as
trades. A second run on the same inputs should produce the same mechanical
eligibility and risk decisions, even if research commentary differs.

Recommended policy questions and changes for the next version:

| Current issue | Proposed direction |
|---|---|
| Sector ETFs and individual catalyst stocks share one loosely defined process | Start with one explicit sector-momentum strategy; evaluate individual-stock selection as a separate variant before combining them. State explicitly whether ETFs are in the universe. |
| Rule 12 can force a purchase after under-deployment | Replace forced purchases with explicit exposure rules. Permit cash when no candidate qualifies; compare against an exposure-matched benchmark so cash does not hide weak selection. |
| A 20% position with a 10% stop implies about 2% account loss at the stop | Size by a predefined loss budget per position and total open stop risk, with an additional concentration cap. Four such positions imply about 8% planned stop risk before gaps; stops do not cap actual loss. |
| A scheduled -7% discretionary exit and roughly -10% broker protection imply different exit behavior | Choose one coherent exit policy, including overnight gaps, market hours, and stop renewal. Encode its mechanical triggers independently of research. |
| "Bear case refuted" and a stated 2:1 target can imply unsupported certainty | Require dated evidence, explicit invalidation, uncertainties, and measurable outcomes. An asserted target is not evidence of positive expected return. |
| Strategy changes during the trial obscure attribution | Freeze each version for its evaluation segment; compare changes prospectively using the same data and cost assumptions. |

These are proposals, not edits to the current trading rulebook. On 2026-09-19
the owner specified **$10,000 initial pilot capital** and **$4,000 maximum
acceptable loss**, equivalent to 40% of starting capital. Planning interpretation:
total net trading loss from initial capital, including realized and unrealized
P&L and trading fees; with no cash flows, $6,000 equity reaches that threshold.
This interpretation is not a peak-to-trough drawdown limit. Cash-flow adjustment,
separate operating costs and a peak drawdown rule belong in the final risk contract.

Treat $4,000 as an outer loss tolerance, not a target risk budget or a guaranteed
loss cap. Proposed earlier control: pause new entries for review at $1,000 net
loss (10% of starting capital), while retaining protection and managing exits.
That earlier threshold is a recommendation, not an accepted or implemented rule.
Position risk and whole-share affordability must be checked against this smaller
account. Recording the budget does not authorize funding, orders, or live enablement.

## Work sequence and acceptance evidence

1. **Recover the evidence already earned.** Import broker orders, fills, cash
   movements and available account activities; reconcile positions and equity.
   Explain differences from markdown rather than overwrite original records.
   Calculate same-period returns, drawdown, exposure, costs and benchmark results.
   Acceptance: no unexplained differences for the evaluation period; unavailable
   history is explicitly excluded or labeled.
2. **Finish and exercise execution recovery in paper.** Add account locking,
   stable buy IDs, partial-fill handling, recovered cancel/close, durable events,
   independent monitoring, and startup reconciliation. Test process death after
   each state change, lost HTTP responses, duplicate/overlapping routine runs,
   market closures, and ledger failure. Prevent new risk on uncertain state;
   design a durable emergency path for protection rather than simply making
   exits depend on a database that may be down. Acceptance: no duplicate or
   oversized exposure, and each failure resolves to known broker state or an
   actionable incident with a tested operator recovery procedure.
3. **Inspect the deployed routines and freeze strategy v1.** Verify enabled
   schedules/timezones, actual prompt and code versions, dependencies, recent
   outcomes, usage capacity and alert delivery without exposing secrets.
   Paper-test the future live configuration at the intended capital scale.
   Use the existing [evaluation gates](PAPER-EXPERIMENT.md); prior running time
   counts where equivalent controls and records can be demonstrated, not merely
   because calendar time elapsed.
4. **Open a bounded, supervised live pilot only after those gates.** Use separate
   deployment, credentials and an allowed account ID. Verify account eligibility,
   restrictions, cash/settlement behavior, market-data entitlement and order
   support on that account. Begin with human-reviewed entries through the same
   execution service. Predeclare allocation, position/portfolio loss budgets,
   drawdown stop condition, and who handles incidents. Keep paper shadow proposals
   for comparison. This pilot measures live execution; it does not demonstrate
   strategy profitability just by running successfully.
5. **Scale only on evidence.** Require complete reconciliation, successful
   failure drills, acceptable measured live costs, and prospective strategy
   performance versus the baselines. Review after a declared period and adequate
   independent decisions; neither a few good trades nor a fixed day count alone
   proves an investment edge. If results disappoint, retain the pilot limit or
   pause instead of increasing capital to compensate.

Alpaca explicitly documents simulation omissions, including market impact,
latency-related slippage and dividends. The live pilot therefore provides
information the paper history cannot establish.
[Alpaca paper trading](https://docs.alpaca.markets/us/docs/paper-trading)

Broker-specific findings and stop-order limitations are recorded separately in
[paper-to-live research](research/0005-paper-to-live-readiness.md).

## Access and scope

The attempted web read of `https://claude.ai/code/routines` failed to return the
private account page. Available integration search did not find a suitable
authenticated browser/routines connector. This is an inspection limitation,
not evidence the routines are inactive. No orders, notifications, live enablement,
remote configuration changes, or capital transfers were performed.
