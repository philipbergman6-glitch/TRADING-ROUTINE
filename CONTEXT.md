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

**Approved version**:
The strategy version named by `"active"` in `docs/rulebook-pins.json`, with a
pin and no `until`. The one source for which rules may trade (ADR 0011).
_Avoid_: active version (the rulebook marker only declares it), STRATEGY_VERSION (the deployment's echo)

**Version binding**:
A run's agreement with the approved version: `STRATEGY_VERSION` names it, and
the rulebook's marker and hash match its pin. An unbound run may mutate only
by protective-stop restoration.
_Avoid_: version check (it is a refusal, not a report)

**Protective-stop restoration**:
Placing the `rs-`/`rr-` stop for a held position without verified coverage
after an earlier run's cancel, with no cancel of its own. The one mutation an
unbound run may make; it runs under the approved version and raises an incident
alert.
_Avoid_: renewal, conversion, tightening (each cancels a resting stop first)

**Protection check**:
One successful verification of protection for every open position against
live broker state, including any due renewal, conversion or tightening. A
check that could not read the broker, that left protection short, or that ran
as a dry run (planning only), is not a check.
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

### Execution identity

**Intent**:
One requested action on one symbol — enter, close, or replace a stop — minted
by the caller and recorded before anything is sent to the broker. It is the
unit of idempotency and recovery: a rerun on any later day resolves the same
intent. The day in its name says when it was minted, not what it is.
_Avoid_: order, request, client order id (an order is what the broker holds;
the client order id names one attempt)

**Attempt**:
One submission of an intent to the broker, carrying its own client order id.
An intent has an ordered list of attempts; a new one is made only after the
broker confirms the previous one dead, and an attempt's id is never reused.
_Avoid_: retry (names the act, not the thing), resubmission

**Position lifecycle**:
One episode of holding a symbol, from the buy fill that takes the quantity
from zero until reconciled holdings return to zero, including every add and
stop replacement in between. It is read from broker fills and holdings, never
minted; once flat it is a blotter *round trip*. A filled close attempt proves
an earlier lifecycle ended, not that the current one has.
_Avoid_: position (ambiguous between the holding and the episode), trade

### Coordination

**Coordinator**:
The single account-wide owner of execution state: it records intents before
anything reaches the broker, holds reservations, and reconciles every
unfinished intent against the broker before accepting a new one. Every writer
that changes the broker goes through it.
_Avoid_: lock manager, scheduler, order router

**Lease**:
The exclusive, expiring right to change execution state for the whole account,
held by one writer for one coordinated action. There is one lease, not one per
symbol. When a holder dies, its lease is taken over only after it expires, and
the taker reconciles the dead holder's intents before doing anything else.
_Avoid_: lock (a lock is held until released; a lease ends by itself), mutex

**Reservation**:
The capacity an unfinished entry intent holds against position slots, position
size, deployment, the weekly trade count and cash, until the broker's own
account state shows it. It belongs to its intent, is taken only once the
intent passes validation, and ends when the intent fills or dies; it is
counted by the rules, never subtracted from the broker's figures.
_Avoid_: hold, pending order (a pending order is a broker object; a reservation
exists before any order does)

### Provenance

**Run**:
One execution of a routine or of the protection monitor, from the moment it
starts until it records how it ended. A run that started and never recorded
an end is *unfinished*: it died or stopped before saying what it did.
_Avoid_: session, job, execution (the mechanism, not the concept)

**Run record**:
The machine-written account of one run: what triggered it, the code, rulebook
and instructions it ran under, the model that drove it where one did, and its
outcome (actions taken, refusals, incidents, or no trade) with the intents it
created. It is reconciled evidence; the trade and research logs are narrative.
_Avoid_: log entry, audit trail (the logs are prose written by the run itself)

**Unprovenanced**:
Said of a run with no run record, which is every run before run records
began. What code or model it used is unknown and is never reconstructed after
the fact; its narrative log stands, labelled as such.
_Avoid_: legacy, unverified (unverified suggests a check could still be run)

### Accounting

**Reconciliation**:
The daily proof that broker cash, holdings and equity are fully explained by
the broker's own activity record: deposits, fills and fees rebuild cash to the
cent, fills rebuild holdings share for share, and cash plus held lots at the
session close rebuilds each past session's equity. Equity figures in the logs
are narrative; the reconciliation is the record.
_Avoid_: audit, P&L check (an audit judges process; this checks arithmetic)

**Unexplained difference**:
A reconciliation gap that no activity accounts for: any cash or holdings
mismatch, or a session's equity beyond tolerance that is not recorded as a
known broker snapshot artefact at the same size. It stops the daily summary.
_Avoid_: drift, discrepancy (both suggest something tolerable)
