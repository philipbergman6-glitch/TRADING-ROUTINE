# Protection checks have a 90-minute service level, measured by the heartbeat from run history, and a lost alert fails the job

Date: 2026-10-12. Status: accepted. Resolves Wayfinder ticket
[#103](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/103)
(map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93)).

## Context

The repository advertised a 30-minute protection monitor. The run history
([research 0008](../research/0008-protection-monitor-cadence.md)) shows
GitHub's `schedule` delivers ~2 of 16 weekday slots (12 %), the first success
of a session lands 4.8–5.8 market hours after the open, one whole session
(2026-10-05) had no run, and the daily heartbeat cron fires 2.7–3.8 h late.
Alerts went through `scripts/email.sh`, which discarded the Resend id, exited
0 when credentials were unset, and whose failures both Python callers ignored
([research 0009](../research/0009-alert-delivery.md)). Market-open committed
nothing on a no-trade day, so the heartbeat could not tell "did not run" from
"nothing to do".

## Decision

1. **The number: 90 minutes.** While the exchange is open (09:30–16:00 ET on
   Alpaca trading days) the newest *successful* protection check is never
   older than 90 minutes. That is three 30-minute cron slots — it tolerates
   two consecutive dropped slots and is the smallest bound that separates a
   scheduler hiccup from nobody watching. It is a target the deployed
   scheduler is measured against, not a description of it: GitHub cron
   breaches it every session today, and that breach is now reported rather
   than hidden behind the word "30 minutes".
2. **Who measures: the heartbeat, from the GitHub Actions run history.** The
   evidence is the completion time (`updated_at`) of every successful live
   `protection-monitor` run on the session day; `scripts/protection_sla.py`
   turns those into stale windows (pure arithmetic), and `scripts/heartbeat.py`
   reports the windows and total stale minutes as one issue. The monitor does
   not measure itself (it cannot run when it is the thing that did not run)
   and nothing is committed to git or written to the broker to mark a check
   (concurrent cloud pushes and the no-mutation rule both argue against it).
3. **What a miss triggers: an alert and a coverage gate, not a trading
   refusal.** Staleness is an alert (heartbeat exit 5, email). It does not by
   itself refuse new positions: the broker holds the stops, so a stale
   monitor leaves existing protection in force. What market-open must not do
   is add to a book it has not just verified, so it runs the monitor in
   `--dry-run` before any buy and places no buy while coverage is short. A
   rule that refuses trades on staleness alone would be a rulebook change
   (tickets #104/#105), not an engineering one.
4. **Delivery is verified and a lost alert fails the job.** `email.sh`
   captures the Resend id, reads `GET /emails/{id}` back, exits non-zero on
   unset credentials (3), a rejected send (2), a bounce/failure (4) or an
   unverifiable status (5). `heartbeat.py` and `protection_monitor.py` return
   exit 9 when the alert was lost (the monitor keeps 7/8, the more urgent
   broker-state codes), so a failed workflow run is the fallback signal; the
   heartbeat workflow then opens or comments a GitHub issue, the one channel
   that does not depend on Resend. A send-only key is the one exception: see
   *Sent, unverified* under Consequences.
5. **Market-open leaves a record every session**: commit subject
   `market-open trades <date>` or `market-open no-trade <date>`, and the
   heartbeat requires one of them.

## Considered and rejected

- *Set the level to what GitHub cron delivers (~6 h).* Honest, but a level
  that long protects nothing within a session; the cuts and conversions the
  monitor exists for are hours-scale.
- *Keep 30 minutes.* Equal to the cadence, so a single dropped slot is a
  breach; the number would be noise from day one.
- *A second GitHub cron as watcher.* Subject to the same scheduler; adds no
  independence.
- *Resend webhooks.* Need an always-on HTTPS receiver the repo does not
  operate; polling the id from the same job needs nothing new.

## Consequences

- The heartbeat will report a protection-check breach every session until the
  monitor is dispatched from outside GitHub's scheduler. Options and cost are
  in the PR for ticket #103 and in `ARCHITECTURE.md`; choosing one needs a
  new secret, so it is the owner's call.
- Local use of `email.sh` without credentials now exits 3 (the message still
  lands in `DAILY-SUMMARY.md`); routines treat that as "the owner was not
  told".
- Every market-open run pushes a commit, including no-trade days.
- **A dry run is not a protection check** (ticket
  [#131](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/131)).
  A `workflow_dispatch` with `dry_run=true` reads coverage but does no due
  work, so it counts for neither coverage nor the level. The Actions run list
  does not return dispatch inputs, so the workflow's `run-name` stamps the mode
  into `display_title` (`protection-monitor live` / `protection-monitor dry
  run`) and the heartbeat counts only the live title. A successful run with
  any other title (a drifted `run-name`, or a run from before 2026-10-12) is
  rejected rather than guessed, so the heartbeat fails loudly once on the day
  this lands.
- **Sent, unverified: a send-only Resend key is a configuration failure, not a
  lost alert** (ticket
  [#147](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/147)).
  The production `RESEND_API_KEY` is a sending-only key, so every status read
  answered 401 `restricted_api_key`, every alert ended in exit 5, and the
  heartbeat fallback filed a duplicate "ALERT PATH FAILED" issue for an email
  that had gone out (#140, #141, #143). `email.sh` now treats that one answer
  as *sent, unverified*: exit 0, a `delivery=unverified
  reason=restricted_api_key` verdict on stdout (`delivery=verified` otherwise),
  a stderr warning, and a line in `EMAIL_UNVERIFIED_FILE`. The heartbeat and
  the monitor report `alert_delivery` (`verified` / `unverified` / `failed`)
  and keep their exit; only `failed` is a lost alert. Both workflows run
  `scripts/alert_unverified.sh`, which raises it once a day: one workflow
  warning and a dated GitHub issue, skipped when that day's issue already
  exists. A rejected send (2), a verified bounce (4) and any other unreadable
  status (5) still fail. The fix that restores verification is the owner's: a
  full-access key in the repository secret.
