# Trading Routine

**An autonomous paper-trading system where a language model proposes trades and
deterministic code decides whether the broker ever sees them.**

Five scheduled routines run a $100,000 Alpaca paper account on a Chicago-time
clock. The model does research, picks entries and writes the narrative. It
cannot place, change or cancel an order without passing a pure Python risk
engine, a second validation of the exact payload against live broker state, and
a paper-only endpoint guard that has no override. Every protective stop is
repaired by a GitHub Actions monitor that runs without the model and without the
database. The account has traded live paper since 2026-04-28 and the results are
reconciled to the broker's own fills.

[Dashboard](https://philipbergman6-glitch.github.io/TRADING-ROUTINE/dashboard/) ·
[Architecture](ARCHITECTURE.md) ·
[Strategy spec](docs/STRATEGY-SPEC.md) ·
[Broker-reconciled results](docs/research/0006-paper-results-reconciliation.md) ·
[Strategy assessment](docs/STRATEGY-ASSESSMENT.md) ·
[Engineering handoff](docs/PROJECT-STATUS.md)

---

## If you have five minutes

```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'   # 384 pass, offline
.venv/bin/python scripts/doctor.py                                         # log + dashboard consistency
.venv/bin/python scripts/build_dashboard_data.py --check                   # committed data reproduces
.venv/bin/python scripts/segment_record.py --check                         # open segment hashes match the tree
```

Then read, in order:

1. `risk_engine/engine.py`: every mechanised rule, with the ones deliberately
   left to judgment named in `UNMECHANISED` rather than silently dropped.
2. `scripts/alpaca.sh`: the only path to the broker. Refuses any non-paper
   endpoint before it reads credentials. Refuses every mutation unless the
   exact payload re-validates.
3. `scripts/replace_stop.py`: how a stop is tightened without ever leaving the
   position naked, and how a crash mid-replacement resumes instead of
   duplicating.
4. `docs/research/0006-paper-results-reconciliation.md`: the track record,
   rebuilt from broker fills rather than from the model's own log.
5. `docs/experiments/`: the open scoring segment, with the rulebook hash,
   every prompt hash and the model ids frozen at open. CI fails if any of
   them drift while the segment is open.

---

## How the whole system flows

```mermaid
flowchart TB
    subgraph SCHED["Scheduler (Claude cloud routines, America/Chicago)"]
        PM["06:30 pre-market<br/>research, 2-3 ideas, HOLD by default"]
        MO["08:30 market-open<br/>validate and execute"]
        MD["12:00 midday<br/>cut at -7%, tighten trails, re-check theses"]
        EOD["15:00 daily summary<br/>EOD snapshot and P&L"]
        WR["Fri 16:00 weekly review<br/>stats, grade, rule proposals"]
    end

    subgraph MEM["Working memory (memory/*.md, git-committed)"]
        STRAT["TRADING-STRATEGY.md<br/>rulebook, sha256-pinned per version"]
        RLOG["RESEARCH-LOG.md"]
        TLOG["TRADE-LOG.md"]
        WLOG["WEEKLY-REVIEW.md"]
    end

    subgraph GATE["Deterministic gate (no model judgment past this line)"]
        SV["scripts/strategy_version.py<br/>env version must match pinned rulebook"]
        VO["scripts/validate_order.py<br/>preflight on live account state"]
        RE["risk_engine/<br/>pure: no I/O, no clock, Decimal only<br/>returns every broken rule"]
        SH["scripts/alpaca.sh<br/>paper endpoint only, no override<br/>exit 5 without caller intent flag"]
        VM["scripts/validate_mutation.py<br/>re-validates the exact JSON body<br/>fresh ask, no pending buy, stop floor"]
    end

    subgraph EXEC["Idempotent execution (resume by client_order_id)"]
        SE["submit_entry.py<br/>en-DATE-SYM, GTC market OTO<br/>with fixed protective leg"]
        RS["replace_stop.py<br/>rs-ID / rr-ID<br/>validate, cancel, confirm, place, restore on failure"]
        CP["close_position.py<br/>cl-DATE-SYM<br/>cancel stop, confirm, sell, confirm"]
    end

    BROKER[("Alpaca paper API<br/>orders, positions, fills")]
    PPLX["Perplexity<br/>research only"]

    subgraph IND["Independent of the model (GitHub Actions)"]
        MON["protection-monitor<br/>coverage, renew, convert, tighten<br/>no Claude, no ledger"]
        HB["heartbeat<br/>did every routine and workflow run today?<br/>emails on any miss"]
        CI["tests<br/>pure suite + real Postgres ledger job"]
        DASH["dashboard-data<br/>regenerates docs/dashboard from logs"]
    end

    LEDGER[("Postgres ledger<br/>optional, fails closed when configured")]
    EMAIL["Email alerts (Resend)"]
    PAGES["Public dashboard<br/>GitHub Pages"]

    PM --> PPLX
    PM --> RLOG
    MO --> STRAT
    MO --> RLOG
    MD --> TLOG
    EOD --> TLOG
    WR --> WLOG

    MO --> SV --> VO --> RE
    MD --> SV
    RE -->|"refused: exit 3, nothing sent"| TLOG
    RE -->|approved| SH --> VM --> BROKER
    VM -->|refused| TLOG
    VO -.->|every verdict| LEDGER

    MO --> SE
    MO --> RS
    MD --> RS
    MD --> CP
    SE --> SH
    RS --> SH
    CP --> SH
    BROKER -->|fills, positions, open orders| VO
    BROKER -->|fills| BLOT["risk_engine/blotter.py<br/>FIFO round trips, cooldown, sector streaks"]
    BLOT --> VO

    MON -->|reads positions and stops| BROKER
    MON -->|acts only via| RS
    MON --> EMAIL
    HB --> EMAIL
    TLOG --> DASH --> PAGES
    WLOG --> DASH
    MEM -->|git push| CI
```

The line that matters is the boundary of the **Deterministic gate**. Above it,
the model reads, researches and proposes. Below it, nothing accepts a model
opinion as input. A buy that reaches Alpaca has passed the pure engine once on
the preflight and again on the exact bytes the wrapper is about to send.

---

## What a risk committee would ask, and the answers in code

**Can the model bypass the risk engine?**
Not through anything in this repository. The broker wrapper is the only HTTP
path, it refuses `order`, `close` and `cancel` without the intent flag, and the
flag alone proves nothing: the wrapper then runs the mutation validator on the
exact body it will send. Bulk `cancel-all` and `close-all` are refused outright.
The paper-only check is enforced twice, in the wrapper before credentials are
read and again inside the engine, so one refactor cannot remove it.
Tests: `tests/test_broker_boundary.py`, `tests/test_mutation_validation.py`,
`tests/test_t1_validate_gate.py`.

**What happens if the process dies halfway through an order?**
Every mutation carries a deterministic client order id. Entry is
`en-<date>-<symbol>`; the script looks it up before submitting and confirms it
after, so a rerun never buys twice. Stop replacement validates while the old
stop still rests, cancels, polls for `canceled`, submits `rs-<old id>`, and on
failure re-places the old level as `rr-<old id>`. Exit is cancel, confirm,
sell, confirm, and an unconfirmed sell after a confirmed cancel is a named
incident with its own exit code. Each step is re-derived from broker state, so
the same command after a crash resumes.
Tests: `tests/test_replace_stop.py`, `tests/test_submit_entry.py`,
`tests/test_close_position.py`, `tests/test_t3_unprotected_windows.py`.

**How do you know every position is protected right now?**
Three ways, none of which trust the model's log. The mutation gate requires
every buy to be a GTC market OTO with a fixed protective leg at the version's
entry distance. The protection monitor on GitHub Actions compares held
quantities against resting, unexpired GTC stops and renews, converts or
tightens through the same resumable script. `scripts/doctor.py --broker` does
the same check read-only on demand. The monitor has run on schedule since
2026-09-29; GitHub throttles its 30-minute cron to about two runs a day, so the
repository describes it as a coverage check, not continuous protection.

**Can a stop ever move down?**
No. `validate_stop_change` refuses any new level below the current one and any
level within 3% of price. Because a replacement must cancel the old stop first,
the gate reads the canceled stop's price through its client id, or any
same-symbol stop canceled in the last 15 minutes, so the old high-water mark
still binds after the cancel.

**Is the track record real?**
The P&L is. On 2026-09-19 the account's full order, fill, fee and deposit
history was pulled read-only and reconciled to equity to the cent. Every logged
entry and exit exists as a broker fill at the logged quantity. The narrative
has stated gaps: five trading days lack an end-of-day log entry, and May to
early June output was recovered from deleted branches. Seven one-to-three-share
test fills on 2026-08-11 are excluded and flagged as a mistake not to repeat in
a scored account.

**Where do the numbers live?**
In `risk_engine/versions.py`, as frozen dataclasses, one per strategy version.
`STRATEGY_VERSION` selects at each command-line boundary. Unset means v1,
unknown is a hard error. The rulebook file is sha256-pinned per version and the
market-open, midday and `/trade` paths refuse to run if the environment, the
rulebook marker and the pin disagree. Money is `Decimal` throughout and float
input is rejected at the boundary rather than converted.

**What did you deliberately leave to judgment?**
Sector momentum, catalyst quality, patience over activity, and the
minimum-deployment mandate. Each is named in `risk_engine.UNMECHANISED` with
the reason. A safety layer refuses orders; it should never compel one, so the
deployment backstop is enforced by the routine and measured by
`scripts/deployment_status.py`, not by the engine.

---

## Results, stated the way they were measured

Two different measurements, two different dates. Do not mix them.

**Broker-reconciled, 2026-04-27 close to 2026-09-18 close, identical dates for both series**
([research 0006](docs/research/0006-paper-results-reconciliation.md)):

| Metric | Bot | SPY |
|---|---|---|
| Total return | +3.28% | +7.04% |
| Max drawdown, daily closes | −10.32% | −4.46% |
| Daily volatility | 0.94% | 0.77% |
| Correlation of daily returns | 0.31 | |
| Average invested fraction | 62% | 100% |
| Round trips | 15 | |

The honest reading, from the project's own
[strategy assessment](docs/STRATEGY-ASSESSMENT.md): the risk machinery works
and the selection engine did not beat the benchmark. Two trades made $9,820,
the other thirteen lost $6,169. The single-name phase to June 30 beat SPY by
2.8 points; the sector-ETF phase after it trailed by 6.1. The recommendation
on record is not to fund the current rulebook, to freeze it as v1, and to run
a specified v2 against it in paper.

**Scored segment.** Segment 0001 opens on 2026-10-13 under rulebook v1.1
([record](docs/experiments/)). Everything before it is exploratory evidence by
the project's own definition. Returns inside the segment are scored on broker
closes, not on the log.

**Log-derived since the reconciliation, not independently reconciled** (dashboard and
`memory/TRADE-LOG.md`, 2026-10-09 close):

| | |
|---|---|
| Equity | $105,778.92 (+5.78% from $100,000) |
| Positions | 5, all protected, 4 trailing and 1 fixed |
| Deployment | 80.5%, inside the 75–85% band |
| Latest week | +2.43% vs S&P +0.91% |

The dashboard shows both dates separately so that curated commentary can never
pass for live data.

---

## What is enforced in code versus instructed in prose

| Rule | Where | How |
|---|---|---|
| Paper account only | wrapper and engine | hard refusal, no override exists |
| US equities only | engine and mutation gate | symbol format, then broker asset class |
| Max positions, max 20% per position, max 3 new trades a week | engine | on every proposal |
| Cash only, never margin | engine | sizing reads settled `cash`, never `buying_power` |
| 85% deployment ceiling | engine | on every buy |
| Every buy carries protection | mutation gate | GTC market OTO with fixed leg inside the version's band |
| Stop never lowered, never within 3% | engine via `validate_stop_change` | on every stop change, against the broker's actual stop price |
| Trail ladder 10% → 7% at +15% → 5% at +20% | engine via `required_trail_percent` | midday and monitor ask the engine, then validate |
| No pending buy while adding risk, quote under 60 seconds old | mutation gate | at submit |
| v2: sector cap, no sector ETFs, 10-session re-entry cooldown | engine and fill-based blotter | cooldown from broker fills, not markdown |
| Cut losers at −7% | routine instruction | exit trigger, then the same validated close path |
| Deployment backstop after 3 sessions under band | routine instruction plus `deployment_status.py` | measured, never compelled by the engine |
| Sector momentum, catalyst quality, patience | judgment | named in `UNMECHANISED` |

---

## What is not done, on purpose

This is an experimental research platform and the documentation says so
throughout. The gaps below are tracked, not hidden.

- **The agent holds broker credentials.** They are exported as process
  environment variables in the routine's sandbox. Credential isolation from
  the model is future work.
- **No cross-process reservation.** Two routines running at once could both
  pass validation against the same cash. Idempotency is per client order id,
  not a durable intent store.
- **Cancel then place is recoverable, not atomic.** A sub-second unprotected
  window exists on every stop replacement. Whether Alpaca's PATCH can resize a
  trailing stop in place is an open research question, not an assumption.
- **Markdown is still the operational store.** The Postgres ledger is
  additive and mandatory when configured, but the cloud routines run without
  a database and read `memory/*.md` for state.
- **The protection monitor runs about twice a day,** not every 30 minutes,
  because GitHub throttles cron on quiet repositories. Routines must not defer
  protection work to it.
- **Live trading does not exist.** Both guards reject real-money endpoints. A
  live pilot needs a separately designed execution path, not a config change.
  See [LIVE-READINESS.md](docs/LIVE-READINESS.md).

---

## Repository map

| Path | What it is |
|---|---|
| `risk_engine/` | Pure rules, versioned parameters, protection payload builders, fill-based blotter, coverage planner. No I/O. |
| `scripts/validate_order.py` | Proposed-order preflight on live account state, optional ledger decision record |
| `scripts/validate_mutation.py` | Re-validates the exact broker mutation immediately before transport |
| `scripts/alpaca.sh` | The only broker path. Paper endpoint only, mutation gate, bounded transport, HTTP status capture |
| `scripts/submit_entry.py`, `replace_stop.py`, `close_position.py` | Idempotent entry, stop replacement and exit |
| `scripts/protection_monitor.py` | Scheduled coverage check and repairs, no model, no ledger |
| `scripts/heartbeat.py` | Daily liveness check across routines and workflows |
| `scripts/blotter.py`, `deployment_status.py`, `strategy_version.py`, `doctor.py` | Round trips from fills, deployment band, rulebook pin check, offline health |
| `scripts/segment_record.py`, `docs/experiments/` | Predeclared scoring segments: frozen rulebook and prompt hashes, model ids, benchmarks; `--check` fails on drift |
| `ledger/` | Postgres decisions, broker responses, append-only audit events |
| `memory/` | Rulebook, trade log, research log, weekly reviews, sector map. Agent context, not the accounting record |
| `routines/` | The five scheduled instruction files. The cloud scheduler holds only a thin sync-and-run prompt |
| `.claude/commands/` | Local `/trade`, `/conviction`, `/portfolio` and local copies of the routines |
| `.github/workflows/` | tests, protection-monitor, heartbeat, dashboard-data |
| `docs/` | Strategy spec, assessment, ADRs, audits, research notes, generated dashboard |

---

## Scheduled routines

| Routine | Chicago time | Places orders? | Commits |
|---|---|---|---|
| Pre-market | 06:30 weekdays | No | `pre-market research <date>` |
| Market-open | 08:30 weekdays | Yes, through the gate | `market-open trades <date>`, or `market-open held <date>` when it did nothing |
| Midday | 12:00 weekdays | Exits and stop changes only, through the gate | `midday scan <date>` |
| Daily summary | 15:00 weekdays | No | `EOD snapshot <date>` |
| Weekly review | 16:00 Fridays | No | `weekly review <date>` |

Each cloud routine fetches `origin/main`, hard-resets, reads its
`routines/<name>.md` in full and executes it. The repository is the single
source of truth for routine behavior; see [routines/README.md](routines/README.md).
`/conviction` produces advice only. `/trade` executes through the same gate.

---

## Local checks and the ledger

```bash
env -u DATABASE_URL .venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python scripts/doctor.py            # add --broker for a read-only live coverage check
.venv/bin/python scripts/build_dashboard_data.py --check
git diff --check
```

The ledger tests run against a real Postgres, never a mock, and CI fails if
they silently skip:

```bash
.venv/bin/pip install -e ".[dev,ledger]"
docker compose up -d
DATABASE_URL=postgresql://trading:trading@localhost:5433/trading .venv/bin/python -m pytest -q
```

Configuration names are in `env.template`. Never commit a `.env`.

---

## Next milestone

Score segment 0001 on broker closes, then run the versioned v2 paper experiment specified in
[STRATEGY-SPEC.md](docs/STRATEGY-SPEC.md) and
[PAPER-EXPERIMENT.md](docs/PAPER-EXPERIMENT.md): a $10,000 segment with
predeclared benchmarks, model id recorded per run, and a funding criterion
written down before the first trade. Engineering prerequisites still open: a
durable execution coordinator with cross-process reservations, and an
independent reconciliation loop that makes the ledger authoritative rather
than additive. Decisions and status live in [docs/adr/](docs/adr/) and
[docs/PROJECT-STATUS.md](docs/PROJECT-STATUS.md).
