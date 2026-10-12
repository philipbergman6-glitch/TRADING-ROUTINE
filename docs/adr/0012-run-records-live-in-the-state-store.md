# 0012. Run records: two lines per run in the state store, written by the run itself

Date: 2026-10-12. Status: accepted. Resolves
[#108](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/108)
on map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93).
Builds on ADR 0004 (store: append-only `state/events.jsonl` on `main`, push is
the compare-and-swap, fail closed) and ADR 0010 (read-only routines report in
their run record, never take the lease).

## Context

No run ID, model ID, commit or prompt hash is recorded per run
(`docs/STRATEGY-SPEC.md` §1: Model ID "Not recorded anywhere in the
repository"). Routines quote the `STRATEGY_VERSION` line into TRADE-LOG; the
monitor's JSON report carries `strategy_version` and is printed, not kept. A
scored segment needs the code, rulebook, instructions and model of every run
(`docs/PAPER-EXPERIMENT.md`), and "did the run happen and end" is today read
from commit subjects.

Facts this leans on:

- The writers are the five Claude routines (cloud copies in `routines/`, local
  copies in `.claude/commands/`; #78, which merges them behind
  `scripts/preflight.sh` / `scripts/persist.sh`, is still open) and the
  protection monitor on GitHub Actions.
- **No environment we run in is known to expose the model ID.** The cloud
  trigger pins `claude-opus-5` in the scheduler configuration, outside the
  repo. A local Claude Code session exposes `CLAUDE_CODE_SESSION_ID` and
  `CLAUDE_EFFORT` but no model variable (checked 2026-10-12); the cloud
  environment is unverified. The model does know its own ID: the system prompt
  states it.
- The monitor's pushes with `GITHUB_TOKEN` trigger no workflow, and
  `dashboard.yml` regenerates `docs/dashboard/data.js` only on `memory/**`
  pushes; the golden check requires data.js to reproduce exactly.

## Decision

### 1. Store: the intent store, not a second file

Run records are lines of `kind: "run"` in `state/events.jsonl`, written with
ADR 0004's protocol (`scripts/state_store.py`), commit subject
`state: <run id> run-start|run-finish [skip ci]`. One store means one fetch,
one validator and one replay for every reader, and a run's `intents` point at
lines in the same file.

### 2. Two lines per run

- **start**, before the run does anything else: `run`, `routine`, `trigger`,
  `code_sha`, `code_subject`, `code_dirty`, `rulebook_version`,
  `rulebook_sha256`, `rulebook_pinned`, `command_file`, `command_sha256`,
  `model_id`, `model_source`, `host_ref`.
- **finish**, at the end: `outcome`, `actions`, `refusals`, `incidents`,
  `intents`.

Start and end are the envelope `at` of each line. The run ID is
`<routine>-<YYYYMMDDTHHMMSSZ>-<6 hex>` and is also the line's `writer`. A start
with no finish is an **unfinished** run, shown as such: a crash cannot leave a
false "no-trade". Field rules worth stating:

- `code_subject` is kept beside `code_sha` because the cloud proxy rewrites
  SHAs; verification is by subject everywhere else too.
- `rulebook_pinned` records whether the file matches its pin. The record
  states the fact; `scripts/strategy_version.py` stays the gate.
- `command_file` is the instruction file the run follows (`routines/<r>.md`,
  `.claude/commands/<r>.md` or the monitor workflow), hashed per run. This
  replaces the spec's concatenated "prompt hash" for per-run provenance.
- `model_source` is one of `self-reported` (the agent passes the ID its system
  prompt states), `env:ANTHROPIC_MODEL`, `unexposed` (`model_id` null) or
  `not-applicable` (the monitor runs no model). A self-reported ID is the
  best evidence available, and labelled as exactly that.
- `trigger` is `cloud` or `local` for a Claude routine (a cloud run cannot
  tell its cron from "run now") and `schedule` or `workflow_dispatch` for the
  monitor. `host_ref` is `github-actions:<run id>/<attempt>` or
  `claude-code-session:<id>` when the environment provides one.
- `outcome` is derived, never chosen: `incident` if any incident, else
  `actions`, else `refused`, else `no-trade`. A line whose outcome
  contradicts its lists is malformed.

Every line has exactly its op's fields. A malformed line, a finish without a
start, a second start or finish, or a writer that is not the run ID is a hard
failure for every reader (`scripts/run_record.py fold`), the dashboard build
included. The writer validates against the stored lines before pushing, so
it cannot land one.

### 3. Writer: the run, through one helper

`scripts/run_record.py start|finish` is the only writer. `start` remembers the
run ID in the checkout's git directory (never committed, survives
`git reset --hard`), so `finish` names the same run. The helper is what #78's
`preflight.sh` and `persist.sh` call when that ticket lands; until then the
routine files call it directly, in both copies.

- **Claude routines**: start right after the sync, finish after the memory
  push is verified, and finish with an incident before any early STOP. Local
  copies pass `--local` (ADR 0004 §3's dedicated clone). If start fails,
  market-open and midday STOP (no mutation without the store, ADR 0004 §1);
  the read-only routines alert and continue unrecorded, because their log is
  still due and they change nothing.
- **Protection monitor**: start, monitor, finish from its JSON report. A
  failed start never blocks protection; the job fails afterwards with exit 10
  so the heartbeat sees it. A missing or unreadable report is recorded as the
  incident.

### 4. History is unprovenanced, never backfilled

Runs before the first run record have no record and get none. No model ID,
commit or hash is reconstructed from logs or git history: a backfilled line
would be indistinguishable from evidence. The dashboard and the glossary call
these runs **unprovenanced**.

### 5. Dashboard: a generated section, apart from the curated ones

`build_dashboard_data.py` emits `RUNS` (counts, outcomes, the 12 most recent
runs) between the generated `BOOK` and the curated block dated by
`ANALYSIS_ASOF`, and the page renders it as its own panel. Only runs whose
lines are dated before `LOG_ASOF` (the latest EOD snapshot, UTC dates) are
shown: every such line was on `main` when that log's rebuild ran, so monitor
records pushed afterwards cannot make the committed data.js stale. The cost
is a lag of at least one trading day.

## Considered and rejected

- **A separate committed JSONL for runs.** A second file with the same
  protocol doubles the readers' work and splits run from intent for no gain.
- **The coordinator writes run records.** Read-only routines never reach the
  coordinator (ADR 0010 §5), and a run's start must land before it acts.
- **One line at the end of the run.** A run that dies leaves nothing, and
  "did not run" becomes indistinguishable from "died".
- **Read the model from the scheduler configuration.** Not reachable from the
  run, and it records what was configured, not what ran.
- **Show every run on the dashboard.** The golden check would fail after each
  monitor run, because nothing regenerates data.js on those pushes.

## Consequences

- Two `state:` commits per run: ten a trading day from the routines, two per
  monitor run (up to about 32 monitor runs a day with the dispatcher and
  GitHub's own schedule both firing). At roughly 0.5 KB a line that is about
  40 KB a day, so ADR 0004's 5 MB revisit trigger is reached in roughly six
  months of trading; the revisit (or archiving old lines) is due before
  then, not a surprise. Each routine's
  memory push now always takes the rebase path once; that path is already in
  every routine.
- The model ID is only as good as the agent's report. If a model variable is
  ever exposed, `env:` takes it without a schema change.
- Read-only routines will add non-terminal intents and lease takeovers as
  incidents once the coordinator (#100) exists; the field is already there.
- #78 moves the start and finish calls into `preflight.sh` / `persist.sh` and
  deletes the `routines/` copies; the wiring test then follows the commands.
- `/trade` and `/conviction` are not runs of a routine and write no run
  record; adding one is a new routine name in `scripts/run_record.py`.
