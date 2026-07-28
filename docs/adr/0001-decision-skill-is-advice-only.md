# Decision skill is advice-only; execution stays in /trade

The research-driven decision skill produces a ranked **decision** (TRADE/PASS
verdicts + rationale) but never places orders. Execution — order placement,
GTC trailing stop, and trade logging — remains the sole job of `/trade`, which
already enforces the hard mechanical rules at the boundary.

**Why:** Two experiments depend on this seam. (1) Reliability: the decision is
written down and gradeable *before* any money moves, so we can later audit
whether the agent's judgment respected the strategy independent of the outcome.
(2) System coherence: keeping a human confirm + the validated `/trade` path
between the decision and the live position keeps the existing routines reacting
to a *real, rule-checked* position rather than to an unvetted auto-order.

**Considered and rejected:** Having the skill place the order directly (one
clean run, but it collapses the auditable gap and removes the human gate).
