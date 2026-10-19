# 0013 — What a second set of cloud routines on the drill account requires

Ticket [#196](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/196)
on map [#191](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/191).
Date: 2026-10-19. Read-only on the broker and the cloud; no trigger or
environment was created or changed. Tags: **[DOC]** official documentation,
**[API]** a response observed this session, **[REPO]** a file in this repo at
`origin/main` (ffeb19d) unless a branch is named, **[SUPPORT]**/**[FORUM]**
Alpaca support page or staff forum post (not docs), **[INFER]** my inference.

## Summary

A second routine environment is ordinary: Claude Code cloud environments are
per account, not per repo, carry their own environment variables, and each
routine picks one explicitly (`job_config.ccr.environment_id`). The repo
already has three (`Default`, `QLD_bot`, `TRADING-ROUTINES`). The real costs
are elsewhere: (3) the memory-file pushes of two routine sets to `main` are
serialised only by the routines' `git pull --rebase` retry, which is one
attempt with no verification of the other writer's work, and the `state/`
store is already split per profile (`drill-state`); (4) the monitor and the
heartbeat are single-profile by construction (one key pair per process, exit
6 on both), so the drill account needs either a matrix job or a second
workflow plus a heartbeat that reads commit subjects per profile; (5) a second
schedule set is five more routines drawing the same subscription usage, not a
separate bill. Everything that creates the environment, sets its variables, or
schedules a routine is owner-only.

## 1. Can a second environment exist beside `TRADING-ROUTINES`, with its own env vars?

Yes.

- **[DOC]** "Each routine uses a cloud environment that controls network
  access, environment variables, and setup scripts." —
  https://code.claude.com/docs/en/routines
- **[DOC]** "Add, edit, and archive environments from the environment
  selector... Environments you create are personal to your account." No count
  limit is stated; "You can't delete an environment, only archive it." —
  https://code.claude.com/docs/en/cloud-environments
- **[DOC]** Variables are entered per environment in `KEY=value` lines; "Anyone
  who uses the environment can read the values." API keys may instead be
  "network secrets" the proxy attaches, "available on Pro, Max, Team, and
  Enterprise plans." —
  https://code.claude.com/docs/en/cloud-environments#set-environment-variables
  and `#add-network-secrets`
- **[API]** The `schedule` skill's environment listing for this account (served
  from the routines API when the skill loads) shows three environments:
  `Default` (`env_012MFmR3emd4nipiQBu3Cgip`), `QLD_bot`
  (`env_01JL4hovRLBA5CDVnX4Y9EaV`), `TRADING-ROUTINES`
  (`env_012uP6D8mWiht1LpoiK1uDcx`), all `kind: anthropic_cloud`. Two
  trading-bot environments already coexist in one account, so a fourth
  (`TRADING-ROUTINES-DRILL` or similar) is the same operation again.
- **[REPO]** The repo's own rule for its contents: `routines/README.md:40-43`
  "Never set `DRILL_ALPACA_API_KEY` / `DRILL_ALPACA_SECRET_KEY` or
  `ALPACA_PROFILE` on a production routine ... Drill runs get only the
  `DRILL_*` pair plus `ALPACA_PROFILE=drill`." `scripts/alpaca.sh:52-55` exits
  6 when both pairs are present; `scripts/heartbeat.py:199-212` applies the
  same rule. So the new environment holds exactly: `DRILL_ALPACA_API_KEY`,
  `DRILL_ALPACA_SECRET_KEY`, `ALPACA_PROFILE=drill`, `ALPACA_ENDPOINT`,
  `ALPACA_DATA_ENDPOINT`, `PERPLEXITY_API_KEY`, `PERPLEXITY_MODEL`,
  `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM` (`routines/README.md:30-36`), and
  `STRATEGY_VERSION` for the v3 pin (`scripts/strategy_version.py` exits 5
  without it; see memory note of the 2026-10-13..17 gap). It must never hold
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`.
- **[DOC]** Variables are not visible through the routines API: the trigger
  body carries `environment_variables: {}` for every existing trigger (memory
  `cloud-prompts-stale-june`, observed via RemoteTrigger on 2026-10-18), and
  the public `/fire` endpoint takes only `text`
  (https://platform.claude.com/docs/en/api/claude-code/routines-fire). Setting
  them is a dashboard action at https://claude.ai/code (environment dialog).

Not found: a documented cap on environments or routines per account.

## 2. How a trigger selects its environment

- **[API]** The create/update body shape the `schedule` skill documents and
  that memory confirms from `RemoteTrigger get` on the five live triggers:
  `job_config.ccr.environment_id` is the only environment reference; there is
  no `environment` name field and `environment_variables` is always `{}`. The
  skill text: "Every routine requires an `environment_id` in the job config.
  This determines where the cloud agent runs." A partial update must send the
  full `job_config` (memory `cloud-prompts-stale-june`: a bare partial
  `model` change was rejected on 2026-10-18).
- **[DOC]** Web UI equivalent: "Select an environment. Pick a cloud
  environment for the routine." —
  https://code.claude.com/docs/en/routines#create-from-the-web. "Anything
  configured with the environment explicitly, such as a routine, can't start
  new sessions in it" once the environment is archived —
  https://code.claude.com/docs/en/cloud-environments#archive-an-environment
- **[INFER]** Because the environment is chosen per routine and the repo is
  listed separately in `session_context.sources`, two routines on the same
  repo can point at different environments. The docs do not state this
  sentence; it follows from the form and from the `QLD_bot` triggers, which
  run a different repo in the same account.
- **[REPO]** The RemoteTrigger tool could not be loaded in this session
  (ToolSearch returned no match three times), so the existing five trigger
  bodies were not re-read today; the shape above is from the skill and the
  2026-10-18 memory note. Re-verify with `RemoteTrigger {action: "get"}` before
  cloning a trigger.

Consequence: five new triggers (pre-market, market-open, midday,
daily-summary, weekly-review) each with `environment_id` of the new
environment, the same thin prompt as `routines/README.md:12-18`, and a
`routines/<name>.md` that reads `ALPACA_PROFILE` (today only one routine
does; map #191 facts). Cron minimum is 1 hour, so the existing five slots can
be reused verbatim or offset by whole hours only (skill text: "Minimum
interval is 1 hour").

## 3. Two routines pushing to this repo in the same minute

Two paths exist and they behave differently.

**Memory-file commits** (`memory/*.md`, the heartbeat's evidence):

- **[REPO]** STEP A in every routine is `git fetch origin main && git reset
  --hard FETCH_HEAD` (`routines/pre-market.md:28`, `market-open.md:105`,
  `midday.md:104`, `daily-summary.md:26`, `weekly-review.md:26`); the cloud VM
  is a fresh clone each run (`routines/pre-market.md:24`; **[DOC]** "Each
  repository you add is cloned on every run" —
  https://code.claude.com/docs/en/routines#repositories-and-branch-permissions).
- **[REPO]** The push step is one line in all five:
  `git push origin HEAD:main || { git pull --rebase origin main && git push
  origin HEAD:main; }` (`pre-market.md:124`, `market-open.md:366`,
  `midday.md:329`, `daily-summary.md:106`, `weekly-review.md:130`), then a
  verify-by-subject (`market-open.md:370-374`) that emails "PUSH NOT ON MAIN"
  on failure and records an incident.
- **[REPO]** `main` is not protected (**[API]** `gh api
  .../branches/main/protection` → 404 "Branch not protected"), so GitHub's
  only guard is the non-fast-forward rejection.
- **[INFER]** Same-minute race, two writers A and B both based on tip T:
  the first push lands; the second is rejected, `git pull --rebase` replays
  its one commit on top, and the second push lands. Both routines append to
  different files when the profiles are namespaced (map #191's hard
  criterion), so the rebase has no textual conflict. If v3 writes the same
  file as v1 (`memory/TRADE-LOG.md` is named in 5 routines today), the rebase
  can conflict and the routine stops with a dirty rebase, "PUSH NOT ON MAIN",
  and an incident; nothing is lost on `main`, the run's entry is. The retry
  is a single attempt: a third writer in the same window makes the second
  push fail again and the routine has no further fallback.
- **[REPO]** Two routine commits in one minute is realistic: on 2026-10-16
  `market-open no-trade` landed at 13:37:53Z, `midday scan` 17:11:51Z, `EOD
  snapshot` 20:17:39Z, `weekly review` 21:09:15Z (`git log origin/main`), each
  minutes after its cron; a second set on the same five crons lands inside
  the same minute window with the LLM's variable run time as the only jitter.
- **[REPO]** Every push to `memory/**` on `main` triggers the dashboard
  workflow (`.github/workflows/dashboard.yml:6-10`), which rebuilds on the
  tip and retries its own publish push (its comment, lines 40-43). Two sets
  double the dashboard builds and give the dashboard the same race against
  the next routine push.

**State store** (`state/events.jsonl`, intents, leases, run records):

- **[REPO]** The store has a real protocol: push is the compare-and-swap, on
  rejection it refetches, rebases the lines, replays, re-asks `still_wins`,
  pushes a withdraw when the claim lost, and gives up after `PUSH_BUDGET = 5`
  (`scripts/state_store.py:37`, `:206-254`; ADR 0004
  `docs/adr/0004-durable-intent-lives-in-a-committed-state-file.md:74-93`;
  ADR 0010 `docs/adr/0010-...md` "one account-wide lease").
- **[REPO]** The store is already split per profile: `PROFILE_BRANCHES =
  {"production": "main", "drill": "drill-state"}` (`state_store.py:54`),
  `run_record.py:380-382` uses `store_branch(environ)`, and the branch exists
  with drill run records on it (**[API]** `git ls-remote origin drill-state`
  → `7fb5ad8 state: drill-20261013T143742Z-9367d9 run-finish`). `docs/DRILLS.md:157-160`
  rehearsed two writers on separate bare clones of `drill-state`, "as two
  cloud checkouts would".
- **[INFER]** So v1 and v3 state writes never race each other: different
  branches, different leases (ADR 0010's lease is per account, and the
  branch is per profile). The drill routines' `run_record.py` calls go to
  `drill-state` automatically once `ALPACA_PROFILE=drill` is in the
  environment. Only the memory-file push shares `main`.

What this does not settle (ticket for the namespacing decision): whether v3's
memory files live on `main` (one push race, one dashboard trigger) or on
`drill-state` beside its store (no race, but `heartbeat.py:229-233` reads
`origin/main` only and the dashboard reads `memory/**` on `main`).

## 4. Heartbeat and protection monitor per profile, and the 200 req/min budget

**Single-profile by construction today.**

- **[REPO]** `protection-monitor.yml:52-58` injects `ALPACA_API_KEY` /
  `ALPACA_SECRET_KEY` from repository secrets; `alpaca.sh:52-55` refuses a
  process with both pairs, so one job cannot cover two accounts. The
  `concurrency: group: protection-monitor` (`:44-46`) serialises runs of
  this workflow; `run-name` (`:28`) stamps "protection-monitor live", which
  `heartbeat.py:79-80` counts as the protection check.
- **[REPO]** `heartbeat.py:63-70` `EXPECTED_DAILY` maps one routine set to
  commit-subject prefixes on `origin/main` (`:229-233`); `:199-212` resolves
  one profile from `ALPACA_PROFILE`; `heartbeat.yml:39-44` passes production
  keys only.
- **[API]** Repository secrets already present: `ALPACA_API_KEY`,
  `ALPACA_SECRET_KEY`, `DRILL_ALPACA_API_KEY`, `DRILL_ALPACA_SECRET_KEY`
  (`gh api .../actions/secrets`); one Actions variable `STRATEGY_VERSION=v1`
  (`gh api .../actions/variables`); the only GitHub environment is
  `github-pages`. `docs/ACCOUNTS.md:21` records the same secret split.

**Three ways to run it twice, with what each costs.**

| Option | Change | Isolation of the two key pairs | Heartbeat | Dispatcher (ADR 0009) |
|---|---|---|---|---|
| (a) Matrix job `profile: [production, drill]` in `protection-monitor.yml` | one file; `env:` becomes `${{ matrix.profile == 'drill' && secrets.DRILL_ALPACA_API_KEY || secrets.ALPACA_API_KEY }}` mapped onto the profile's own names, plus `ALPACA_PROFILE` and a per-profile `STRATEGY_VERSION` variable | job-level `env:` is per matrix job, so each job holds one pair (**[INFER]** from Actions matrix semantics; verify in a dry run) | `heartbeat.py:103-120` counts runs by `display_title`; a matrix gives one run with two jobs, so the count stays per run but a drill-job failure fails the run and the production check reads as failed; needs `_is_live`/`run_summary` to read jobs | one `workflow_dispatch` covers both; `concurrency` group still one |
| (b) Second workflow `protection-monitor-drill.yml` | copy of the file with `DRILL_*` → profile names, `ALPACA_PROFILE=drill`, `run-name: protection-monitor-drill live`, own `concurrency` group | strict: two workflows, two secrets sets | `WORKFLOW_PATH` (`heartbeat.py:72-76`) and `MONITOR` gain a second entry; `protection_check_status` runs per profile | dispatcher `WORKFLOW_FILE` is one value (`dispatcher/worker.js:38`); a second cron or a second dispatch call in the same worker |
| (c) Per-profile Actions variable `ALPACA_PROFILE` on one workflow | smallest diff | one profile at a time: it flips the single monitor from v1 to drill; does not run both | unchanged | unchanged |

**[INFER]** (c) is not a solution for "alongside v1"; it only retargets.
Between (a) and (b), (b) keeps `concurrency`, `run-name`, the heartbeat's
display-title counting and the dispatcher's single `WORKFLOW_FILE` unchanged
per workflow, at the price of a duplicated YAML; (a) is one file but touches
the heartbeat's run-level judgement (`heartbeat.py:103-145`) and the
dispatcher dispatches both profiles whether or not the drill account holds
positions. The heartbeat itself needs, in either case: `EXPECTED_DAILY` keyed
by profile (subject prefixes for the v3 routines), the monitor count per
profile, and a second credential resolution (today it reads the calendar
with one pair, `:214-226`; the calendar is account-independent, so the
production pair can stay for that call).

**Broker request budget.**

- **[DOC]** docs.alpaca.markets states no Trading API rate limit at all:
  `/docs/rate-limit` is a 404 and the site index
  (https://docs.alpaca.markets/llms.txt) lists rate-limit pages for the
  Broker API only (https://docs.alpaca.markets/us/docs/broker-api-rate-limits.md,
  "applied at the correspondent level"). Market data:
  "Historical API calls | 200 / min" on the Basic plan —
  https://docs.alpaca.markets/docs/about-market-data-api
- **[SUPPORT]** "the API is throttled, currently 200 requests per minute, per
  account"; over it "a '429- Too Many Requests' status will be returned" —
  https://alpaca.markets/support/usage-limit-api-calls (dated Dec 2022).
- **[FORUM, staff]** Dan_Whitnable_Alpaca 2025-03-24: "default API rate limit
  of 200/min per account (ie each paper and live account is separate)";
  market data is "200/min per owner" —
  https://forum.alpaca.markets/t/what-constitutes-an-api-call/16502; 2025-11-07
  "Each owner is currently allowed 3 paper accounts and 1 live account" and
  data limits are "enforced per owner and not per account" —
  https://forum.alpaca.markets/t/feature-request-more-paper-trading-accounts/18125
- **[INFER]** So the trading budget is per account: v1 and v3 each get their
  own 200/min on `paper-api`; the one shared bucket is market data
  (`data.alpaca.markets`, per owner), which the routines' `quote` calls and
  the pre-market research touch. Not stated anywhere official in 2026; the
  numbers rest on a 2022 support page and 2025 staff posts.
- **[REPO]** `docs/adr/0004-isolated-drill-account-...md:44` already counts
  "One extra `GET /v2/account` per write on production (200 req/min budget)";
  `alpaca.sh:70-79` makes that call before every write.
- **[REPO]** A monitor pass reads `positions` and `orders open`
  (`protection_monitor.py:157-158`) after `recover` (`:134`), then per
  action `replace_stop.py` reads `order-info` and `order-by-client`
  (`:203`, `:220`, `:277`, `:302`) and polls at most 20 × 1 s per
  confirmation (ADR 0010 context). **[INFER]** A pass with no due work is
  2-4 requests; a pass with k stop replacements is roughly 4 + 5k, well under
  200 even at k = 6 positions.
- **[API]** Observed cadence: 11 monitor runs in 2026-10-12..18, about 2 per
  trading day (`gh run list --workflow protection-monitor.yml`), consistent
  with research 0008 ("~2 runs a day, the first ~5 h after the open",
  `protection-monitor.yml:11-13`). Even at the designed 30-minute cadence
  per profile, two monitors are two short bursts per half hour, each on its
  own key pair and account.
- **[INFER]** With per-account trading buckets the two monitors do not
  compete at all; even if they shared one bucket their demand is two orders
  of magnitude below 200/min, and the routines' demand (`account`,
  `positions`, a `quote` per ticker, `orders`; `market-open.md:128-133`) is of
  the same order. The one place two sets add up is the per-owner market-data
  bucket, where two pre-market runs in the same minute still use a few dozen
  calls. The budget is not a constraint for two monitors; it would be for a
  design that polls.

## 5. Cost of a second schedule set

- **[DOC]** "Routines draw down subscription usage the same way interactive
  sessions do." Overage only "with usage credits turned on ... Without usage
  credits, additional runs are rejected." Hourly caps: scheduled runs 100 per
  hour per account; "None of these hourly limits has overage." —
  https://code.claude.com/docs/en/routines#usage-and-limits
- **[DOC]** "there's no separate charge for the cloud VM"; "cloud sessions
  share rate limits with all other Claude and Claude Code usage within your
  account. Running multiple tasks in parallel consumes more rate limits
  proportionately." —
  https://code.claude.com/docs/en/claude-code-on-the-web#limitations
- **[REPO]** Today's set is five routines on weekday crons, 21 runs a week
  (`routines/README.md:22-28`), model `claude-opus-5-5` since 2026-10-18
  (memory `cloud-prompts-stale-june`). A second set doubles that: 42 runs a
  week, concurrent in the same slots, drawing one subscription's usage.
- **[INFER]** Cost is therefore (i) subscription usage, roughly 2x the
  routine share; the exact token usage per run is not exposed by the API
  (only `list_runs`/`get_run_log` per routine), so measure it from one week of
  v1 run logs before deciding; (ii) GitHub Actions minutes: one more monitor
  workflow at ~2 runs/day plus dashboard builds doubled, inside the free tier
  for a public repo; (iii) zero broker cost on paper; (iv) owner time for
  the provisioning below. Not found: a documented routine count limit or a
  per-run price.

Not found in docs: environment/routine count caps, concurrent-session caps,
token cost per routine run.

## Owner-only

Each item needs the account owner at https://claude.ai/code or the GitHub
settings page; none can be done from a routine or this session.

1. Create the second cloud environment (name suggestion:
   `TRADING-ROUTINES-DRILL`) and set its variables: `DRILL_ALPACA_API_KEY`,
   `DRILL_ALPACA_SECRET_KEY`, `ALPACA_PROFILE=drill`, `ALPACA_ENDPOINT`,
   `ALPACA_DATA_ENDPOINT`, `STRATEGY_VERSION=<v3 pin>`, Perplexity and
   Resend vars. Never `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`.
2. Create five triggers with `job_config.ccr.environment_id` of that
   environment (RemoteTrigger `create` is scriptable once the owner approves
   the body; the environment id is only known after step 1).
3. Confirm the GitHub App on this repo may push `main` (unchanged) and, if
   the namespacing ticket chooses `drill-state` for v3 memory files, that the
   proxy allows that branch (it "doesn't limit which branches a push can
   update" — https://code.claude.com/docs/en/cloud-environments#github-proxy).
4. Add the Actions variable for the v3 `STRATEGY_VERSION` (per-profile name
   or matrix value), and if option (b) is chosen, a dispatcher secret/var for
   the second workflow file (`dispatcher/setup.sh`).
5. Decide whether drills move to a fourth paper account (Alpaca allows three
   per login, research 0010) before v3 starts trading the drill account.

## Verification against the ticket's done-when

Each of the five points cites a doc URL, an API response observed this
session, or a repo file and line; inferences are tagged. The RemoteTrigger
re-read of trigger bodies is the one source that could not be refreshed
today and is flagged in section 2.
