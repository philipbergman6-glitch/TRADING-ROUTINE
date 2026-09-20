# Versioned strategy specification

Written 2026-09-19. This document defines strategy **v1** (the rulebook as
run, frozen as the baseline) and **v2** (the proposed successor). It is the
contract that `docs/PAPER-EXPERIMENT.md` scores against. It changes nothing
in `memory/TRADING-STRATEGY.md`, the routines, or the risk engine: v2 becomes
operative only when its rules are written into those files and the pins in
section 5 are recorded for the new segment.

Evidence behind every v2 change is in
[STRATEGY-ASSESSMENT.md](STRATEGY-ASSESSMENT.md) and
[research 0006](research/0006-paper-results-reconciliation.md). Where this
spec and that evidence disagree, the evidence wins and this spec is wrong.

## 1. What a version is

A strategy version is the tuple below. Any change to an item creates a new
version and a new evaluation segment; a segment is never re-scored under a
later version.

| Pin | Where it lives | v1 value |
|---|---|---|
| Rulebook hash | `sha256 memory/TRADING-STRATEGY.md` | `84e53ed1…516fa` at commit `07603ef` |
| Prompt hash | `sha256` of `routines/*.md` and `.claude/commands/*.md` concatenated in `ls` order | `a9cbb897…bc12` at `07603ef` |
| Code commit | Git SHA the routine synced to | `07603ef` (verified GitHub main, 2026-09-18) |
| Model ID | Cloud routine configuration | **Not recorded anywhere in the repository.** Must be captured per run before a segment is scored |
| Universe | Section 2.2 / 3.2 | v1: undefined in writing; observed universe listed in 2.2 |
| Capital | Account starting equity | v1: $100,000 paper |
| Benchmarks | Section 4 | Identical for every version |

Full v1 hashes:

```
rulebook  84e53ed169eec0265d59317fc60725759d1de9edf834b2552c60a37df46516fa
prompts   a9cbb8970d51670053f90b904cb9a15125ac0dc314c0be6831ebc4bc77cb4c12
```

Note on v1's prompt pin: the cloud prompts were thin pointers to `routines/*.md`
only from 2026-09-17. Before that, the cloud copies were stale pastes of
June-era prompts (see `routines/README.md`). The v1 segment scored in research
0006 therefore ran under **more than one effective prompt version**. That is
recorded as a known limitation of the v1 baseline, not corrected retroactively.

Enforcement classes used below:

- **Engine**: rejected by `risk_engine` before any broker mutation.
- **Script**: computed by a script and reported; the routine must act on it.
- **Advisory**: text the routine is expected to follow; nothing checks it.

## 2. Strategy v1 (frozen baseline)

Status: **running**. Segment start for scoring: 2026-04-27 close. Rules are
quoted from `memory/TRADING-STRATEGY.md` at `07603ef`; nothing here amends them.

### 2.1 Rules and how each is enforced today

| # | Rule (as written) | Enforcement | Observed in the v1 segment |
|---|---|---|---|
| 1 | No options, ever | Engine (`STOCKS_ONLY`) | Held |
| 2 | 75–85% deployed | Engine upper bound only (`MAX_DEPLOYMENT_PCT` = 85); lower bound Script (`deployment_status.py`) | Below band 46 of 98 sessions |
| 3 | 5–6 positions, max 20% each | Engine (`MAX_POSITIONS`, `MAX_POSITION_PCT`) | Held; four 20% sector ETFs was within the rule and was the main loss |
| 4 | Live GTC protective stop at 10% at all times; OTO fixed leg then convert to trailing (ADR 0002) | Engine (`STOP_REQUIRED`, `STOP_DISTANCE`); coverage check in `protection.py` | Every position covered; worst single loss −9.2% |
| 5 | Cut losers at −7% manually | Advisory (midday routine) | Fired at −8.1% (MSFT); preempted by the trail at −7.46% (XLI) |
| 6 | Tighten trail: 7% at +15%, 5% at +20% | Engine validates a proposed change (`required_trail_percent`); nothing triggers it | Helped PLTR, MU; cut AMD's run short; XOM never reached +15% |
| 7 | Stop never within 3% of price; never lowered | Engine on the change (`STOP_NEVER_LOWERED`, `STOP_DISTANCE`); standing state unchecked | XLB's renewed fixed stop sits 2.4% below the Sep 18 close |
| 8 | Max 3 new trades per week | Engine (`MAX_TRADES_PER_WEEK`) | Bound in weeks 1–2 only |
| 9 | Follow sector momentum | Advisory | As a filter (May): +7.5% vs SPY +4.7%. As the holding (ETFs): −3.9% vs +2.3% |
| 10 | Exit a sector after 2 consecutive failed trades | Advisory; no sector field in the trade log, so not computable | Three tech losers in June; rule not invoked |
| 11 | Patience > activity | Advisory | Used to justify 0–60% deployment for weeks |
| 12 | Deployment backstop: forced add after 3 under-band sessions, one deferral max | Script (`deployment_status.py`) | Fired twice (XLK Aug 10, XLE Sep 17); both low-conviction ETF adds |
| 13 | Cash only, never margin | Engine (`SUFFICIENT_CASH` on `cash`) | Held |
| — | Entry checklist: catalyst, sector, stop 7–10%, target ≥ 2:1 | Advisory | No trade ever exited at target |

### 2.2 Universe as actually traded

v1 never defined a universe in writing. Observed: US large-cap single names
(AMD, NVDA, PLTR, XOM, MU, AVGO, MSFT, GOOGL, WMT) through June, then SPDR
sector ETFs (XLF, XLB, XLI, XLP, XLK, XLE). Seven F fills on 2026-08-11 were
engineering tests and are excluded from the v1 record.

### 2.3 Known gaps in v1, left as-is

These are frozen with the version. They are inputs to v2, not v1 patches.

- **Standing-state violation of rule 7.** The rule constrains a *change*. When
  price drifts to within 3% of a fixed stop (XLB, Sep 18), the rulebook gives
  no instruction, and both available actions (leave it; convert to a wider
  trail) conflict with some reading of the rule. Until v2, the v1 handling is:
  leave the stop, record the condition in the trade log each session it
  persists, do not lower. This is an interpretation note, not a rule change.
- Rule 5 cannot fire at −7% because it is a scheduled check, not a resting order.
- Rule 6 tightening is never triggered automatically.
- Rule 10 is not computable from the record.
- The trade log has no sector, catalyst, invalidation, or version field.

### 2.4 v1 as a shadow

From the start of the v2 segment, v1 continues as a **shadow**: each session
the routine records what v1 would have proposed (entries, exits, stop changes)
in the decision record with `strategy_version: v1-shadow`. Shadow proposals
are scored on the same quotes and never executed. This gives a
contemporaneous v1-vs-v2 comparison without a second broker account.

## 3. Strategy v2 (proposed)

Status: **not operative.** Segment start: the first session after (a) the
execution controls in section 6 are merged and tested, (b) the pins in
section 5 are recorded, (c) the paper account is reset to $10,000 or a
separate $10,000 paper account is opened. Whichever account is used, the
scored account carries no test orders.

Capital: **$10,000**. Every dollar figure below scales from that.

### 3.1 Rules

Changed rows are marked. Unchanged rows carry v1's text and enforcement.

| # | v2 rule | Change vs v1 | Enforcement target |
|---|---|---|---|
| 1 | No options, ever | — | Engine |
| 2 | Target deployment 75–85% of equity in the active sleeve **plus fallback** (rule 12). Total invested (active + SPY fallback) must be ≥ 75% at every EOD unless a declared cash condition is in force | **Modified**: the band is now filled by the fallback, not by forced sector bets | Engine lower bound at buy time cannot enforce a floor; Script computes EOD and the market-open routine must act. Cash condition is a dated record |
| 3 | Max 5 active positions, max 20% each; **at most 2 positions in the same GICS sector**; SPY fallback does not count toward the 5 or the sector limit | **Modified**: adds the sector concentration cap | Engine (new `MAX_SECTOR_POSITIONS` check; sector supplied by the proposal and recorded) |
| 4 | Live GTC protective stop on every active position at all times, entered via OTO fixed leg (ADR 0002). **Initial fixed leg at −7%** (6.5–7.5% below entry) | **Modified**: initial distance is 7%, not 10% | Engine (`STOP_DISTANCE` band parameterised per version) |
| 5 | **No manual cut.** The −7% fixed stop is the loss exit. When the position closes ≥ +5% above entry, the fixed stop is replaced by a **10% trailing stop** | **Replaced**: rule 5 becomes a resting order; the conversion is a triggered action | Engine validates; a new scheduled protection monitor (section 6) triggers the conversion without Claude |
| 6 | Tighten trail to **7% at +15%**. No 5% step | **Modified**: drops the +20%/5% step that exited AMD before a further +28% | Engine (`_TRAIL_LADDER` per version); monitor triggers it |
| 7 | Never place or move a stop to within 3% of current price; never lower a stop. **If price drifts to within 3% of a resting fixed stop, leave it**; record the condition daily | **Clarified**: standing-state case now has an instruction | Engine on change; monitor reports the standing condition |
| 8 | Max 3 new active entries per ISO week; fallback SPY buys and sells are exempt | **Clarified**: fallback exempt | Engine (`MAX_TRADES_PER_WEEK`, symbol SPY excluded) |
| 9 | Sector momentum is an **entry filter** for single names: a candidate's sector ETF must have outperformed SPY over the trailing 20 sessions on the observation date. **Sector ETFs are not eligible as active positions** | **Modified**: momentum filters; it is not the holding | Script computes the filter from daily bars and records it in the decision record; Engine rejects sector ETF symbols in the active sleeve |
| 10 | After 2 consecutive closed losers in the same sector, no new entry in that sector for 20 sessions | **Made computable**: sector recorded per trade; the counter is computed from broker fills | Script (blotter from fills); Engine rejects the entry when the counter is in force |
| 11 | *(deleted)* | **Discontinued**: "patience" replaced by rule 12's explicit cash conditions | — |
| 12 | **Fallback**: capital that would leave total invested below 75% with no qualifying signal is held in **SPY**. Cash below 75% is permitted only under a **declared market-wide risk condition** with a dated expiry (max 10 sessions, renewable with a new record). No forced active entry ever | **Replaced**: SPY fallback instead of forced leadership add | Script (EOD deployment incl. fallback); the market-open routine executes the fallback; the cash declaration is a record the script checks |
| 13 | Cash only, never margin; sizing reads settled `cash` | — | Engine |
| 14 | **Cooldown**: no re-entry in a name within 10 sessions of a stop-out or cut in that name | **New** | Engine (from the fill-based blotter) |
| 15 | **Target**: each entry records a target at ≥ 2:1 reward-to-risk against the 7% stop (so ≥ +14%). At target, **trim one third** and leave the remainder on the trailing stop | **Modified**: the checklist target becomes operative | Engine validates the record exists; monitor triggers the trim |

Whole-share sizing at $10,000: a 20% position is $2,000. Candidates priced
above $500 are excluded (a single share would exceed 25% of the position's
rounding tolerance); price floor $10 per section 3.2.

### 3.2 Universe

- Active sleeve: US-listed common stocks and ADRs, price between $10 and $500
  on the observation date, 20-session average dollar volume above $50M.
- Excluded from the active sleeve: ETFs and ETNs of any kind, options, OTC,
  anything the engine already rejects.
- Fallback instrument: SPY only.
- Sector assignment: GICS sector as reported by the data provider on the
  observation date, recorded in the decision record. The sector ETF used for
  rule 9 is the SPDR sector fund for that sector.

### 3.3 Decision record fields (both versions from the v2 segment start)

Per `docs/PAPER-EXPERIMENT.md`, each candidate, traded or not, records:
symbol, observation timestamp, sources cited, sector, rule-9 filter result,
forecast (direction, horizon in sessions, probability), invalidation
condition, proposed entry, stop, target, reason to trade or pass,
`strategy_version` (`v2` or `v1-shadow`), and the risk-engine result. A
later review never edits a prior record; it appends.

## 4. Benchmarks and scoring (identical for every version)

- **SPY total return** on identical dates, IEX daily closes, `adjustment=all`.
- **Exposure-matched SPY**: SPY's daily return scaled by the prior day's
  invested fraction. Under v2 the fallback should make this converge on SPY;
  divergence measures declared cash conditions.
- **v1 shadow**: the shadow book marked at the same closes.
- Bot equity from **broker daily closes** (`portfolio/history`, shifted one
  day per research 0006), never from the EOD log's intraday snapshot.
- Metrics: net return, max drawdown on closes, average invested fraction,
  turnover, execution shortfall (fill vs decision-record quote), fees,
  operating cost per month (model, research, hosting; currently unrecorded
  and must be logged from the segment start), relative return to each
  benchmark. Forecasts scored at their declared horizon.
- Operational metrics reported separately: missed routines, incomplete
  decision records, unreconciled orders, duplicate submissions, uncovered
  quantity-minutes, incident duration.

## 5. Segment start checklist (v2)

Record in `docs/PROJECT-STATUS.md` and in the first decision record of the
segment:

1. Rulebook hash and prompt hash after the v2 rules are written into
   `memory/TRADING-STRATEGY.md`, `routines/*.md`, `.claude/commands/*.md`.
2. Code commit the routines sync to; confirm the cloud prompts are the thin
   pointer template.
3. Model ID from the cloud routine configuration, per routine.
4. Account ID, starting equity ($10,000), and confirmation that no test order
   has ever been placed in it.
5. Operating-cost log started (monthly model, research, hosting spend).
6. Benchmark data source and adjustment setting.
7. Owner decision on the two open items in section 7.

## 6. Execution controls v2 depends on

v2 cannot start before these exist and are tested; they are the engineering
milestone in `docs/PROJECT-STATUS.md`.

| Control | Why v2 needs it | Status (2026-09-20) |
|---|---|---|
| Idempotent buys (stable client order ID, durable intent before submit) | Rule 8 and rule 14 counts are meaningless if a retry double-submits | `scripts/submit_entry.py`: client ID `en-<YYYYMMDD>-<SYM>`, lookup before submit, confirm by ID. Intent is the ID itself, not a durable store. |
| Recovered cancel-to-close exits | Rule 15 trim and any thesis-break close must complete after process death | `scripts/close_position.py`: cancel confirmed by poll, sell `cl-<YYYYMMDD>-<SYM>`, resumes on rerun, exit 8 if naked. |
| Full broker lifecycle recording, blotter rebuilt from fills | Rules 10 and 14 are computed from fills, not from markdown | `risk_engine/blotter.py` + `scripts/blotter.py`: FIFO round trips from `/account/activities/FILL`; cooldown and sector streaks derived from it. |
| Protection monitor that runs without Claude and without the ledger | Rules 5, 6, 7 (standing) and 15 are triggered actions; the Sep 8–16 outage showed protection must not depend on the ledger | `risk_engine/monitor.py` + `scripts/protection_monitor.py` + `.github/workflows/protection-monitor.yml` (30-min cron, paper endpoints hardcoded). Repo secrets not yet configured; not yet observed running. |
| Version-parameterised engine constants (stop band, trail ladder, sector cap, cooldown) | v1 shadow and v2 are validated by the same engine under different parameters | `risk_engine/versions.py`: `V1`, `V2`, `STRATEGY_VERSION` env selects at every CLI boundary. |

Rule 15 (trim at target) has no script yet; it waits on the owner decision in
section 7.

## 7. Open decisions for the owner

Neither blocks writing v2 into code; both must be answered before the segment
starts (section 5, item 7).

1. **Review threshold definition.** `docs/LIVE-READINESS.md` proposes pausing
   new entries at $1,000 net loss from initial. Scaled v1 history never hit
   that but would have hit a $1,000 **peak-to-trough** rule on Sep 16. Choose
   one; the spec recommends peak-to-trough because it catches the failure
   mode v1 actually exhibited (a long decline from a high).
2. **Rule 15 target trim vs delete.** The spec proposes the one-third trim.
   The alternative is to delete the target from the record entirely. Deleting
   is simpler; trimming is the only way the 2:1 checklist item ever becomes
   evidence.

## 8. Funding criterion (restated from the assessment)

Open a supervised live pilot only if the v2 segment passes the 30-session
operational gate in `docs/PAPER-EXPERIMENT.md` with zero unexplained
reconciliation differences, **and** v2 is at or above exposure-matched SPY
after costs over its segment. Thirty sessions cannot prove edge; they can
prove the machinery and rule out obvious harm. No document in this repository
authorizes live trading.
