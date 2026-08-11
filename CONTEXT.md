# Trading Routine

An autonomous AI trading bot managing a paper Alpaca account, run through
scheduled daily **routines** plus ad-hoc decision tooling. This glossary fixes
the vocabulary shared across routines, the strategy rulebook, and the logs.

## Language

**Routine**:
A scheduled, repeatable daily workflow run by the bot (pre-market, market-open,
midday, daily-summary, weekly-review). Routines are habitual and run on a clock.
_Avoid_: job, cron, script (those are the mechanism, not the concept)

**Decision skill** (`/conviction`):
An ad-hoc, on-demand workflow that produces a *trade decision*, distinct from a
routine. It is heavier and research-driven, run when the trader wants to act,
not on a schedule. The canonical instance is `/conviction`.
_Avoid_: routine

**Scan**:
The lightweight first pass that surfaces candidate trade ideas (3) from a quick
market sweep. Generates candidates; does not vet them.
_Avoid_: research (reserve that for the deep, citing pass)

_Overloaded_: the log headers `### <date> — Midday Scan` mean something else —
the midday **routine's** position review (cut losers at −7%, tighten stops,
re-check theses). It generates no candidates. The two senses are kept apart by
the `Midday` qualifier; bare "Scan" always means idea generation. Midday
entries are prose-only audit trail and never feed the equity curve, which is a
daily-close series built from `EOD Snapshot` headers alone.

**Verification**:
The deep, citing pass that adversarially vets each candidate — confirms a cited
catalyst and tries to refute the bear case. A candidate survives only if its
thesis holds up.
_Avoid_: review, validation (validation is the mechanical rule-check in /trade)

**Verdict**:
The per-idea outcome of verification: TRADE or PASS, decided by two gates —
(1) cited catalyst + bear case refuted, (2) passes the strategy.
_Avoid_: rating, signal

**Decision**:
The ranked set of surviving TRADE candidates that the decision skill outputs.
It is *advice*, not an order — execution happens separately via /trade.
_Avoid_: order, trade (a trade is the executed thing)
