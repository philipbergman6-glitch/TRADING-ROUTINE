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

### Accounts

**Account profile**:
Which of the bot's paper accounts an invocation talks to: *production* (the
scored account every routine trades) or *drill*. One invocation holds exactly
one profile's key pair; holding both is refused.
_Avoid_: environment, mode (those name paper vs live, which never changes here)

**Drill account**:
The isolated second paper account reserved for recovery rehearsals and
destructive tests, with its own keys and its own pinned account number. Nothing
scored ever happens on it; a reset is a delete-and-recreate that rotates both.
_Avoid_: test account, sandbox, staging

**Account pin**:
The committed account number a profile is expected to answer as. Every write
compares the broker's answer with the pin, because no Alpaca payload otherwise
says which paper account a key pair belongs to.

### Protection

**Protection**:
The invariant that an open position always has a live protective stop capping
its downside at the rule-4 distance. This is what strategy rule 4 guarantees;
trailing is the mechanism, not the guarantee.
_Avoid_: stop-loss, risk management (both name a mechanism or a discipline, not
the invariant)

**Protective stop**:
The order that satisfies protection for one position. It is addressable — it has
a broker id — and it is either trailing or fixed. Both kinds protect; only a
trailing one ratchets.
_Avoid_: the stop, trailing stop (a trailing stop is one kind of protective
stop, not a synonym for it)

**Verified coverage**:
The broker-observed state in which a position's full held quantity is matched
by protective stops that are live, unexpired and good-till-cancelled. A stop
that is pending, held, expired or short does not verify; recovery outcomes are
judged against this, never against what one process remembers doing.
_Avoid_: protected (ambiguous between the invariant and the observation), has a
stop (a resting order is not yet verified coverage)

**Unprotected window**:
An interval in which an open position has no live protective stop. Some are
deliberate and bounded — converting a fixed stop to a trailing one, or the
cancel-then-sell that a fully reserved position requires. An unbounded or
undetected one is an incident.
_Avoid_: naked position, the buy/stop gap (each names one instance of a general
state)

**Floor**:
The current level of a position's protective stop. Rule 7 says the floor never
moves down: a stop may be raised, held, or renewed at the same level, never
lowered. Converting a fixed stop to a trailing one is only allowed when the
trail's initial stop sits at or above the floor.
_Avoid_: stop level, stop price (both name a number; the floor names the
one-way constraint on it)

**Standing stop**:
A resting protective stop evaluated as *state* rather than as an *act*. Rule 7's
3% minimum constrains acts — placing or moving a stop. Price drifting to within
3% of a standing stop is a hold to record, not a violation to fix.
_Avoid_: stale stop, violating stop

**Held fixed stop**:
A fixed protective stop kept past entry, or renewed at expiry, because converting
it to a trailing stop would lower the floor. It is permitted protection under
rule 4, not a transient; it converts the first session a trailing stop would sit
at or above it.
_Avoid_: leftover stop (names the pre-conversion leg right after entry, which is
transient), legacy stop

**Protection check**:
One successful verification of protection for every open position against
live broker state, including any due renewal, conversion or tightening. A
check that could not read the broker, or that left protection short, is not a
check.
_Avoid_: monitor run, cron slot (a run can fail; a slot can produce no run)

**Stale window**:
An interval while the exchange is open during which the newest protection
check is older than the maximum protection-check delay. A stale window is a
monitoring miss, not an unprotected window: the broker still holds the stops.
_Avoid_: outage, downtime (both suggest nothing was protected)
### Rule enforcement

**Enforcement class**:
How a rulebook rule is held to: **Engine** (an order that breaks it is refused
before any broker mutation), **Script** (a script computes the state and
reports it; the routine must act), or **Advisory** (routine text only; nothing
checks it). Every rule has exactly one class.
_Avoid_: mechanised, hard rule, soft rule

**Broad ETF**:
A sector or index fund on the repo's maintained list (the SPDR sector funds
plus the index trackers). Holding one adds factor exposure, not an
idiosyncratic thesis.
_Avoid_: ETF (too wide: a single-country or commodity fund is not on the list)

**Single name**:
Any tradable symbol that is not a broad ETF. The only kind of position that
satisfies the composition mandate.
_Avoid_: stock, idiosyncratic position

**Composition mandate**:
The rule-14 state in which the book holds zero single names (an empty book
counts), so the next new position must be a single name. It constrains what a
deployment-mandate add buys, never whether the add happens; the two mandates
never waive each other.
_Avoid_: rule 14 (the number; use the name in prose)

**Composition waiver**:
The recorded reason, written in the pre-market research log, that no single
name passed the entry checklist today, which alone permits a broad ETF to be
bought while the composition mandate is active.
_Avoid_: override, exception

**Sector failure streak**:
The count of consecutive closed round trips in one sector that ended at a
loss, computed from broker fills. At two, that sector is closed to new entries
(including its own broad ETF) for 20 sessions from the second loss; open
positions in it stay on their stops.
_Avoid_: sector exit, consecutive losers
