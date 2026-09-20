# Paper experiment and next evaluation phase

Status clarified 2026-09-19: **paper trading is already running**. The owner
reports approximately three months of operation through Claude Desktop cloud
routines; committed logs contain an earlier April baseline and later recovered
entries. Preserve that history and reconcile its provenance rather than treating
the project as an unstarted experiment.

The separately specified, versioned evaluation phase below has not been
established in the inspected repository. Apply it prospectively once durable
execution and broker accounting are available. Existing runs are operational
and exploratory evidence; they do not establish live execution quality or a
profitable strategy by themselves. See [live-readiness recommendations](LIVE-READINESS.md).

Primary objective: learn whether the system operates reliably and whether the
agent's decisions add value before considering real money.

## Record before starting

- Experiment ID, start/end dates and a fixed evaluation schedule.
- Code commit, strategy hash, prompt hash, model identifier and allowed universe.
- Cash-flow and dividend treatment; spread/slippage assumptions; fees and model,
  research and infrastructure costs.
- Benchmark instruments, data sources, rebalance rules, execution timing and
  capital/exposure constraints. Use identical assumptions for every portfolio.
- Rules for outages, incomplete data, corporate actions and strategy changes.

Keep three parallel reference portfolios: passive broad-market exposure,
exposure-matched broad-market/cash, and a fully specified mechanical
sector-momentum policy. These are research comparisons, not instructions to
buy those portfolios in the broker account.

## Each decision record

Record the ticker, observation timestamp, cited evidence available at that
time, forecast direction/horizon/probability, invalidation condition, proposed
entry/protection, reason to pass or trade, strategy version and result from the
risk engine. Retain rejected candidates. A later review must not rewrite the
original forecast.

## Evaluation

Calculate net returns on matching dates with cash-flow adjustments, maximum
drawdown, exposure, turnover, execution shortfall, total operating cost and
relative performance against each baseline. Evaluate forecasts at their
declared horizon, with uncertainty and sample-size limitations. Report missing
or reconstructed data explicitly; do not silently fill gaps.

Keep operational metrics separate: missed routines, incomplete decisions,
unreconciled orders, duplicate submissions, uncovered quantity and incident
duration. One profitable period cannot compensate for unreliable execution.

## Progression gates

The proposed operational gate is 30 consecutive trading sessions with complete
records and no unexplained reconciliation differences, plus successful failure
and restart drills. This is not a profitability test.

Strategy changes create a new version and evaluation segment; the version
pins and the v1/v2 rule sets are in [STRATEGY-SPEC.md](STRATEGY-SPEC.md). Weekly reviews
may propose changes, but do not silently alter the experiment being scored.
No automatic real-money promotion is authorized by this document. Forward
results, costs and uncertainty must support a separate decision later.
