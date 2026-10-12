# The protection monitor is dispatched every 30 minutes by a Cloudflare cron Worker

Date: 2026-10-12. Status: accepted (deployment pending the owner). Resolves
Wayfinder ticket [#123](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/123)
(map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93)).

## Context

ADR 0007 set a 90-minute protection-check service level. GitHub's `schedule`
delivers ~2 of 16 weekday slots, the first ~5 h after the open
([research 0008](../research/0008-protection-monitor-cadence.md)), so the
heartbeat reports a breach every session. `workflow_dispatch` runs start
within seconds. Something outside GitHub's scheduler has to call the dispatch
endpoint every 30 minutes; whatever it is needs a credential that can start
workflows in this repository.

## Decision

1. **Dispatcher: a Cloudflare Worker with a cron trigger**
   (`dispatcher/worker.js`, `dispatcher/wrangler.toml`). Slots
   `0,30 13-20 * * MON-FRI` UTC, the same slots as the workflow's own cron
   (13:00–20:30Z covers the 09:30–16:00 ET session in EDT and EST). Each slot
   POSTs `workflow_dispatch` for `protection-monitor.yml` on `main` with
   `dry_run=false`, i.e. the live run the schedule would have made.
2. **Credential: one fine-grained PAT, `GH_DISPATCH_TOKEN`**, scoped to this
   repository with *Actions: read and write* only, stored as a Cloudflare
   Worker secret. It is never in the repository, `.env`, or GitHub secrets.
   Cost: $0 (Workers Free: 5 cron triggers, 100k requests/day; this uses one
   trigger and 16 requests a weekday). New accounts: a Cloudflare account and
   the PAT, both the owner's.
3. **Failure is loud on the dispatcher side and judged on the other.** The
   worker refuses missing or malformed config before any request, retries
   once on a network error or 5xx, never retries a 4xx (bad token, scope or
   ref), and throws so Cloudflare's Cron Events record a failed invocation.
   Whether the level was met stays the heartbeat's call, from GitHub's run
   history (ADR 0007) — the dispatcher does not measure itself, so a dead
   worker, an expired PAT or a deleted account all surface as the same
   "protection check: stale" issue.
4. **The workflow is unchanged.** Concurrency group `protection-monitor`
   (no cancel) serialises dispatched, scheduled and manual runs; manual
   dispatches still default to `dry_run=true`; GitHub's own cron stays as a
   free second source.
5. **Owner provisioning is a script**, `dispatcher/setup.sh`: create the PAT,
   prove it with a dry-run dispatch, log in to Cloudflare, deploy, store the
   secret (each live step behind a confirm). Re-run it to rotate the PAT.

## Considered and rejected

- *Self-chaining Actions workflow* (a job that sleeps 30 min and dispatches
  itself plus the monitor with `GITHUB_TOKEN`, which may trigger
  `workflow_dispatch`). No new secret and free on a public repo, but one lost
  link stops the chain until GitHub's unreliable cron restarts it, it keeps a
  runner asleep all session, and it rests on the same platform whose
  scheduling it is meant to escape.
- *cron-job.org or another hosted HTTP cron.* Free and zero code, but the PAT
  sits in a third-party dashboard with no secret store, no SLA on the free
  tier, and the request is not reviewable in the repository.
- *GCP Cloud Scheduler.* Reliable and free for three jobs, but needs a GCP
  project with a billing account (a card), and the PAT ends up as a plain
  header in the job unless a function is added in front.
- *A small VPS crontab* (~$5/month). Costs money and adds a machine to patch.
- *Claude cloud routine.* An LLM session every 30 minutes to make one HTTP
  call; usage cost and its own scheduler are both worse than a cron trigger.

## Consequences

- Until the owner runs `dispatcher/setup.sh` nothing changes: the heartbeat
  keeps reporting a breach every session.
- A fine-grained PAT expires (max one year). Expiry shows as a stale session
  in the heartbeat and as failed Cron Events; rotation is a re-run of the
  wizard.
- Cloudflare does not promise cron timing to the minute; the 90-minute level
  tolerates two consecutive lost slots, and the heartbeat measures the result.
- Dispatched runs and scheduled runs can both fire in the same slot; the
  concurrency group runs them one after the other, so the second plans from
  the broker state the first left.
- CI gains a Node step (`node --test dispatcher/worker.test.js`, no npm
  install); `tests/test_protection_dispatcher.py` fails if the worker's cron,
  target workflow or the workflow's dry-run default and concurrency drift.
