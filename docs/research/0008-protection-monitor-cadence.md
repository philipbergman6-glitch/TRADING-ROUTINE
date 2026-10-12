# 0008 — Protection-monitor cadence, 2026-09-12 to 2026-10-12, and why it diverges from the cron

Date: 2026-10-12 (data pulled 14:00Z). Resolves wayfinder research ticket #101
(parent map #93). Read-only pull of the GitHub Actions run history for
`protection-monitor.yml` and `heartbeat.yml` via
`gh api repos/philipbergman6-glitch/TRADING-ROUTINE/actions/workflows/<file>/runs?created=>=2026-09-12 --paginate`
(130 runs total; nothing was dispatched). Three kinds of statement are kept
apart below: **observed** (API data in this document), **documented** (GitHub
docs, quoted) and **inferred** (my reading of the two).

## Summary

| Question (ticket #101) | Answer |
|---|---|
| Actual cadence | **~2 scheduled runs per weekday**, not 16. 29 scheduled runs over the 15 weekdays the workflow has existed (2026-09-21 to 2026-10-09) against 240 cron slots: **12 %**. Zero runs on weekends (cron day filter holds). |
| When they fire | Two clusters: **17:33–20:02Z** (median ~18:30Z, i.e. 4.5–7 h after the first 13:00Z slot) and **21:01–00:28Z** (median ~22:30Z, i.e. after the last 20:30Z slot). No run has ever fired in the 13:00–17:30Z range. |
| Queue delay (`run_started_at − created_at`) | **0 s on all 130 runs** (both workflows). The lateness is entirely in *event creation*: GitHub creates ~2 schedule events a day, each is then started immediately. |
| Never started vs started late | 29 scheduled runs were created and started at once; the cron slots in between produced **no run object at all** (211 of 240 slots). **One** run (2026-10-05 21:01Z, id 37373280099) was created but never executed: annotation "The job was not acquired by Runner of type hosted even after multiple attempts", cancelled after exactly 15 min (= `timeout-minutes`). |
| Skipped by concurrency group | **None.** No two monitor runs ever overlapped (minimum spacing 3.5 h; the job runs 7–45 s). 0 runs with `conclusion=cancelled` other than the runner-acquisition case above, 0 with `run_attempt>1`. |
| Does the repo plan explain it | No. Repo is public (`visibility: public`); GitHub bills nothing for Actions on public repos with standard hosted runners, so no minute cap applies. The behaviour matches the documented best-effort `schedule` semantics, not a quota. |
| Does the heartbeat cron miss | **Not in the window.** 9 weekday slots (Sep 29–Oct 9) → 9 scheduled runs, each **2.7–3.8 h late** (cron 22:45Z, fired 01:26–02:33Z next UTC day). `scripts/heartbeat.py:53-56` already compensates by assessing the exchange-local date. |
| Worst gap between successful monitor runs, 13:30–20:00Z weekdays | **Fri 2026-10-02 18:16Z → Tue 2026-10-06 18:50Z = 92.4 h wall-clock, 13.5 market hours** (all of Mon Oct 5 plus the tail of Oct 2 and the first 5.3 h of Oct 6). On a *normal* day the first success lands 18:16–19:15Z, so the **first 4.8–5.8 market hours of every session have no monitor run**; worst normal day Wed 2026-10-07 (19:15Z → 5.75 h after the open). Before 2026-09-29 every run failed (secrets not configured), so coverage was zero Sep 21–28. |

Practical conclusion (inference): the cron is a twice-a-day afternoon/evening
check, not a 30-minute guard, and GitHub's own docs say that is within spec.
Anything that must happen within the first half of the session (10 % trailing
stop renewals, −7 % cuts) cannot rely on this workflow. `PROJECT-STATUS.md:69-71`
and `STRATEGY-SPEC.md:204` already say "~2 runs/day"; this note quantifies it
and rules out the plan, the concurrency group and the runner queue as causes.

## 1. Observed: protection-monitor runs (all 30 in window)

`created` = when GitHub created the run (the schedule event firing);
`queue` = `run_started_at − created_at`; `dur` = `updated_at − run_started_at`.

| # | created (UTC) | started | queue s | dur s | event | conclusion | attempt | run id |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-21 18:33:10 | 18:33:10 | 0 | 10 | schedule | failure | 1 | 35639110519 |
| 2 | 2026-09-21 22:30:42 | 22:30:42 | 0 | 13 | schedule | failure | 1 | 35663043432 |
| 3 | 2026-09-22 17:33:54 | 17:33:54 | 0 | 18 | schedule | failure | 1 | 35761525888 |
| 4 | 2026-09-22 21:02:28 | 21:02:28 | 0 | 10 | schedule | failure | 1 | 35784131351 |
| 5 | 2026-09-23 17:46:04 | 17:46:04 | 0 | 10 | schedule | failure | 1 | 35897860161 |
| 6 | 2026-09-23 21:17:21 | 21:17:21 | 0 | 8 | schedule | failure | 1 | 35921491877 |
| 7 | 2026-09-24 17:47:37 | 17:47:37 | 0 | 8 | schedule | failure | 1 | 36036769317 |
| 8 | 2026-09-24 21:18:58 | 21:18:58 | 0 | 7 | schedule | failure | 1 | 36060674782 |
| 9 | 2026-09-25 17:49:55 | 17:49:55 | 0 | 8 | schedule | failure | 1 | 36169574010 |
| 10 | 2026-09-25 21:17:17 | 21:17:17 | 0 | 45 | schedule | failure | 1 | 36190709450 |
| 11 | 2026-09-28 20:02:18 | 20:02:18 | 0 | 8 | schedule | failure | 1 | 36476365631 |
| 12 | 2026-09-29 00:28:58 | 00:28:58 | 0 | 10 | schedule | failure | 1 | 36503307928 |
| 13 | 2026-09-29 11:57:35 | 11:57:35 | 0 | 12 | workflow_dispatch | success | 1 | 36564984980 |
| 14 | 2026-09-29 18:30:15 | 18:30:15 | 0 | 11 | schedule | success | 1 | 36612510922 |
| 15 | 2026-09-29 22:52:14 | 22:52:14 | 0 | 8 | schedule | success | 1 | 36642071462 |
| 16 | 2026-09-30 18:19:02 | 18:19:02 | 0 | 8 | schedule | success | 1 | 36757702107 |
| 17 | 2026-09-30 22:29:54 | 22:29:54 | 0 | 7 | schedule | success | 1 | 36785906329 |
| 18 | 2026-10-01 18:44:08 | 18:44:08 | 0 | 12 | schedule | success | 1 | 36909038040 |
| 19 | 2026-10-01 23:02:06 | 23:02:06 | 0 | 14 | schedule | success | 1 | 36938546290 |
| 20 | 2026-10-02 18:16:17 | 18:16:17 | 0 | 9 | schedule | success | 1 | 37046299106 |
| 21 | 2026-10-02 22:27:50 | 22:27:50 | 0 | 10 | schedule | success | 1 | 37072618644 |
| 22 | 2026-10-05 21:01:01 | 21:01:01 | 0 | 903 | schedule | failure (job `cancelled`, no runner) | 1 | 37373280099 |
| 23 | 2026-10-06 18:50:10 | 18:50:10 | 0 | 11 | schedule | success | 1 | 37514344309 |
| 24 | 2026-10-06 22:56:24 | 22:56:24 | 0 | 10 | schedule | success | 1 | 37543683320 |
| 25 | 2026-10-07 19:15:16 | 19:15:16 | 0 | 12 | schedule | success | 1 | 37673073380 |
| 26 | 2026-10-07 23:41:28 | 23:41:28 | 0 | 9 | schedule | success | 1 | 37703681501 |
| 27 | 2026-10-08 19:11:30 | 19:11:30 | 0 | 11 | schedule | success | 1 | 37830077513 |
| 28 | 2026-10-08 23:51:46 | 23:51:46 | 0 | 10 | schedule | success | 1 | 37861748714 |
| 29 | 2026-10-09 18:42:01 | 18:42:01 | 0 | 8 | schedule | success | 1 | 37975092532 |
| 30 | 2026-10-09 23:05:43 | 23:05:43 | 0 | 11 | schedule | success | 1 | 38002673365 |

Totals: schedule/success 16, schedule/failure 13, workflow_dispatch/success 1.
Runs #1–12 failed at the step "Refuse to run without broker credentials"
(secrets not yet configured; `Protection monitor` step skipped) — verified on
runs 35639110519 and 36503307928. Run #22 failed with job conclusion
`cancelled`, `runner_name` empty, zero steps, annotation
"The job was not acquired by Runner of type hosted even after multiple
attempts"; the 903 s duration equals the workflow's `timeout-minutes: 15`.
No runs on 2026-09-12 to 09-20 (workflow merged 2026-09-20 in 419bd0d) and none
on 2026-10-12 as of 14:00Z (first slot 13:00Z, second 13:30Z, both missed).

### Per day

| date | dow | runs | events | conclusions | start times UTC | offset of each run from preceding :00/:30 slot (min) |
|---|---|---|---|---|---|---|
| 2026-09-21 | Mon | 2 | schedule 2 | failure 2 | 18:33, 22:30 | 3.2, 0.7 |
| 2026-09-22 | Tue | 2 | schedule 2 | failure 2 | 17:33, 21:02 | 3.9, 2.5 |
| 2026-09-23 | Wed | 2 | schedule 2 | failure 2 | 17:46, 21:17 | 16.1, 17.4 |
| 2026-09-24 | Thu | 2 | schedule 2 | failure 2 | 17:47, 21:18 | 17.6, 19.0 |
| 2026-09-25 | Fri | 2 | schedule 2 | failure 2 | 17:49, 21:17 | 19.9, 17.3 |
| 2026-09-28 | Mon | 1 | schedule 1 | failure 1 | 20:02 | 2.3 |
| 2026-09-29 | Tue | 4 | schedule 3, dispatch 1 | failure 1, success 3 | 00:28, 11:57, 18:30, 22:52 | 29.0, –, 0.2, 22.2 |
| 2026-09-30 | Wed | 2 | schedule 2 | success 2 | 18:19, 22:29 | 19.0, 29.9 |
| 2026-10-01 | Thu | 2 | schedule 2 | success 2 | 18:44, 23:02 | 14.1, 2.1 |
| 2026-10-02 | Fri | 2 | schedule 2 | success 2 | 18:16, 22:27 | 16.3, 27.8 |
| 2026-10-05 | Mon | 1 | schedule 1 | failure 1 | 21:01 | 1.0 |
| 2026-10-06 | Tue | 2 | schedule 2 | success 2 | 18:50, 22:56 | 20.2, 26.4 |
| 2026-10-07 | Wed | 2 | schedule 2 | success 2 | 19:15, 23:41 | 15.3, 11.5 |
| 2026-10-08 | Thu | 2 | schedule 2 | success 2 | 19:11, 23:51 | 11.5, 21.8 |
| 2026-10-09 | Fri | 2 | schedule 2 | success 2 | 18:42, 23:05 | 12.0, 5.7 |

Observation: the firing minute is not aligned to :00/:30 (offsets 0.2–29.9
min, roughly uniform), and 10 of 29 scheduled runs fired *outside* the cron's
13–20 hour range (21:xx–00:28Z). So these are not "slot N delayed a few
minutes"; they are a sparse stream of schedule events with no visible
correspondence to individual slots.

### Market-hours coverage (13:30–20:00Z, weekdays)

| weekday | successful runs inside 13:30–20:00Z | all runs that day |
|---|---|---|
| 09-14 … 09-18 | – | workflow did not exist |
| 09-21 … 09-25 | none | 2/day, all failed (no secrets) |
| 09-28 Mon | none | 20:02 failure |
| 09-29 Tue | 18:30 | 00:28 F, 11:57 dispatch S, 18:30 S, 22:52 S |
| 09-30 Wed | 18:19 | 18:19 S, 22:29 S |
| 10-01 Thu | 18:44 | 18:44 S, 23:02 S |
| 10-02 Fri | 18:16 | 18:16 S, 22:27 S |
| 10-05 Mon | **none** | 21:01 cancelled (no runner) |
| 10-06 Tue | 18:50 | 18:50 S, 22:56 S |
| 10-07 Wed | 19:15 | 19:15 S, 23:41 S |
| 10-08 Thu | 19:11 | 19:11 S, 23:51 S |
| 10-09 Fri | 18:42 | 18:42 S, 23:05 S |
| 10-12 Mon | none as of 14:00Z | – |

Gaps between successive *successful* runs (any hour): 92.4 h (10-02 22:27 →
10-06 18:50), then 18.8–20.3 h for every ordinary overnight. Since 09-29 every
session except 10-05 has had exactly one successful run inside market hours,
always after 18:16Z.

## 2. Observed: heartbeat runs (100 in window)

Cron `45 22 * * 1-5`; also `workflow_run` on protection-monitor,
dashboard-data, tests (job-level `if` skips unless the watched run failed).

| # | created (UTC) | queue s | dur s | event | conclusion | run id |
|---|---|---|---|---|---|---|
| 1 | 2026-09-29 12:15:04 | 0 | 1 | workflow_run | skipped | 36566869291 |
| 2 | 2026-09-29 12:15:05 | 0 | 9 | workflow_dispatch | failure | 36566871333 |
| 3 | 2026-09-29 12:15:17 | 0 | 1 | workflow_run | skipped | 36566895555 |
| 4 | 2026-09-29 13:41:58 | 0 | 1 | workflow_run | skipped | 36577023939 |
| 5 | 2026-09-29 13:44:01 | 0 | 1 | workflow_run | skipped | 36577279433 |
| 6 | 2026-09-29 17:13:18 | 0 | 1 | workflow_run | skipped | 36603397146 |
| 7 | 2026-09-29 17:13:33 | 0 | 1 | workflow_run | skipped | 36603426874 |
| 8 | 2026-09-29 18:30:28 | 0 | 1 | workflow_run | skipped | 36612538517 |
| 9 | 2026-09-29 20:16:43 | 0 | 1 | workflow_run | skipped | 36625214339 |
| 10 | 2026-09-29 20:16:53 | 0 | 1 | workflow_run | skipped | 36625235155 |
| 11 | 2026-09-29 22:52:24 | 0 | 11 | workflow_run | skipped | 36642087806 |
| 12 | 2026-09-30 01:34:42 | 0 | 7 | schedule | failure | 36655781159 |
| 13 | 2026-09-30 07:11:52 | 0 | 1 | workflow_run | skipped | 36682325949 |
| 14 | 2026-09-30 07:13:31 | 0 | 7 | workflow_run | skipped | 36682482654 |
| 15 | 2026-09-30 11:39:18 | 0 | 8 | workflow_run | skipped | 36709864569 |
| 16 | 2026-09-30 11:39:20 | 0 | 1 | workflow_run | skipped | 36709869319 |
| 17 | 2026-09-30 13:38:32 | 0 | 1 | workflow_run | skipped | 36723115401 |
| 18 | 2026-09-30 13:38:50 | 0 | 2 | workflow_run | skipped | 36723153525 |
| 19 | 2026-09-30 17:12:21 | 0 | 1 | workflow_run | skipped | 36749723737 |
| 20 | 2026-09-30 17:12:34 | 0 | 1 | workflow_run | skipped | 36749748269 |
| 21 | 2026-09-30 18:19:12 | 0 | 1 | workflow_run | skipped | 36757721189 |
| 22 | 2026-09-30 20:15:15 | 0 | 2 | workflow_run | skipped | 36771310300 |
| 23 | 2026-09-30 20:15:42 | 0 | 1 | workflow_run | skipped | 36771363733 |
| 24 | 2026-09-30 22:30:04 | 0 | 1 | workflow_run | skipped | 36785923122 |
| 25 | 2026-10-01 01:35:05 | 0 | 11 | schedule | success | 36801791211 |
| 26 | 2026-10-01 11:41:36 | 0 | 1 | workflow_run | skipped | 36856959463 |
| 27 | 2026-10-01 11:41:46 | 0 | 1 | workflow_run | skipped | 36856975925 |
| 28 | 2026-10-01 13:44:06 | 0 | 1 | workflow_run | skipped | 36870881454 |
| 29 | 2026-10-01 13:44:27 | 0 | 1 | workflow_run | skipped | 36870924833 |
| 30 | 2026-10-01 17:13:56 | 0 | 1 | workflow_run | skipped | 36897850054 |
| 31 | 2026-10-01 17:14:11 | 0 | 1 | workflow_run | skipped | 36897882309 |
| 32 | 2026-10-01 18:44:22 | 0 | 2 | workflow_run | skipped | 36909065005 |
| 33 | 2026-10-01 20:16:15 | 0 | 8 | workflow_run | skipped | 36920337029 |
| 34 | 2026-10-01 20:16:27 | 0 | 1 | workflow_run | skipped | 36920361915 |
| 35 | 2026-10-01 23:02:21 | 0 | 1 | workflow_run | skipped | 36938569829 |
| 36 | 2026-10-02 01:48:52 | 0 | 9 | schedule | success | 36952717258 |
| 37 | 2026-10-02 11:37:44 | 0 | 1 | workflow_run | skipped | 37002047066 |
| 38 | 2026-10-02 11:38:10 | 0 | 1 | workflow_run | skipped | 37002086061 |
| 39 | 2026-10-02 13:44:37 | 0 | 8 | workflow_run | skipped | 37015022959 |
| 40 | 2026-10-02 13:44:47 | 0 | 10 | workflow_run | skipped | 37015040312 |
| 41 | 2026-10-02 17:16:25 | 0 | 1 | workflow_run | skipped | 37039589295 |
| 42 | 2026-10-02 17:16:36 | 0 | 1 | workflow_run | skipped | 37039610278 |
| 43 | 2026-10-02 18:16:28 | 0 | 10 | workflow_run | skipped | 37046318638 |
| 44 | 2026-10-02 20:18:38 | 0 | 1 | workflow_run | skipped | 37059742939 |
| 45 | 2026-10-02 20:18:51 | 0 | 10 | workflow_run | skipped | 37059761603 |
| 46 | 2026-10-02 21:08:07 | 0 | 1 | workflow_run | skipped | 37064988692 |
| 47 | 2026-10-02 21:08:23 | 0 | 1 | workflow_run | skipped | 37065016063 |
| 48 | 2026-10-02 22:28:02 | 0 | 1 | workflow_run | skipped | 37072637174 |
| 49 | 2026-10-03 01:26:39 | 0 | 11 | schedule | success | 37086112494 |
| 50 | 2026-10-05 11:38:33 | 0 | 1 | workflow_run | skipped | 37304242246 |
| 51 | 2026-10-05 11:38:43 | 0 | 1 | workflow_run | skipped | 37304259758 |
| 52 | 2026-10-05 17:14:58 | 0 | 2 | workflow_run | skipped | 37346994262 |
| 53 | 2026-10-05 17:15:14 | 0 | 2 | workflow_run | skipped | 37347029891 |
| 54 | 2026-10-05 20:16:54 | 0 | 1 | workflow_run | skipped | 37368753924 |
| 55 | 2026-10-05 20:22:16 | 0 | 10 | workflow_run | skipped | 37369302992 |
| 56 | 2026-10-05 21:16:06 | 0 | 351 | workflow_run | success (emailed: monitor run #22 failed) | 37374804179 |
| 57 | 2026-10-06 02:30:43 | 0 | 13 | schedule | failure | 37404485596 |
| 58 | 2026-10-06 11:37:40 | 0 | 1 | workflow_run | skipped | 37457658620 |
| 59 | 2026-10-06 11:37:56 | 0 | 7 | workflow_run | skipped | 37457687436 |
| 60 | 2026-10-06 17:14:20 | 0 | 1 | workflow_run | skipped | 37501985019 |
| 61 | 2026-10-06 17:14:31 | 0 | 8 | workflow_run | skipped | 37502008696 |
| 62 | 2026-10-06 18:50:23 | 0 | 1 | workflow_run | skipped | 37514372854 |
| 63 | 2026-10-06 20:17:23 | 0 | 1 | workflow_run | skipped | 37525309162 |
| 64 | 2026-10-06 20:17:58 | 0 | 11 | workflow_run | skipped | 37525379938 |
| 65 | 2026-10-06 22:56:35 | 0 | 10 | workflow_run | skipped | 37543701670 |
| 66 | 2026-10-07 01:48:47 | 0 | 11 | schedule | success | 37558936407 |
| 67 | 2026-10-07 11:37:45 | 0 | 1 | workflow_run | skipped | 37615365213 |
| 68 | 2026-10-07 11:37:54 | 0 | 1 | workflow_run | skipped | 37615383219 |
| 69 | 2026-10-07 17:17:48 | 0 | 1 | workflow_run | skipped | 37657956687 |
| 70 | 2026-10-07 17:18:11 | 0 | 1 | workflow_run | skipped | 37658005205 |
| 71 | 2026-10-07 19:15:30 | 0 | 1 | workflow_run | skipped | 37673104975 |
| 72 | 2026-10-07 20:17:32 | 0 | 1 | workflow_run | skipped | 37680885879 |
| 73 | 2026-10-07 20:17:44 | 0 | 1 | workflow_run | skipped | 37680911166 |
| 74 | 2026-10-07 23:41:39 | 0 | 7 | workflow_run | skipped | 37703697738 |
| 75 | 2026-10-08 02:16:24 | 0 | 12 | schedule | success | 37717056756 |
| 76 | 2026-10-08 11:39:33 | 0 | 1 | workflow_run | skipped | 37771507954 |
| 77 | 2026-10-08 11:39:49 | 0 | 9 | workflow_run | skipped | 37771537139 |
| 78 | 2026-10-08 17:17:04 | 0 | 1 | workflow_run | skipped | 37815356186 |
| 79 | 2026-10-08 17:17:30 | 0 | 8 | workflow_run | skipped | 37815412464 |
| 80 | 2026-10-08 19:11:44 | 0 | 1 | workflow_run | skipped | 37830105847 |
| 81 | 2026-10-08 20:16:38 | 0 | 1 | workflow_run | skipped | 37838225899 |
| 82 | 2026-10-08 20:16:42 | 0 | 7 | workflow_run | skipped | 37838233933 |
| 83 | 2026-10-08 23:51:58 | 0 | 1 | workflow_run | skipped | 37861768404 |
| 84 | 2026-10-09 02:33:43 | 0 | 9 | schedule | success | 37875158186 |
| 85 | 2026-10-09 11:38:16 | 0 | 1 | workflow_run | skipped | 37924964133 |
| 86 | 2026-10-09 11:38:26 | 0 | 2 | workflow_run | skipped | 37924983215 |
| 87 | 2026-10-09 17:13:55 | 0 | 1 | workflow_run | skipped | 37964787205 |
| 88 | 2026-10-09 17:14:07 | 0 | 1 | workflow_run | skipped | 37964810681 |
| 89 | 2026-10-09 18:42:11 | 0 | 1 | workflow_run | skipped | 37975112838 |
| 90 | 2026-10-09 20:17:54 | 0 | 1 | workflow_run | skipped | 37986030995 |
| 91 | 2026-10-09 20:18:05 | 0 | 7 | workflow_run | skipped | 37986049978 |
| 92 | 2026-10-09 21:07:46 | 0 | 10 | workflow_run | success (emailed: `tests` push run failed 21:07:28Z) | 37991515931 |
| 93 | 2026-10-09 21:07:47 | 0 | 1 | workflow_run | skipped | 37991517130 |
| 94 | 2026-10-09 23:05:56 | 0 | 1 | workflow_run | skipped | 38002690187 |
| 95 | 2026-10-10 01:54:50 | 0 | 10 | schedule | failure | 38014993904 |
| 96 | 2026-10-11 16:11:20 | 0 | 1 | workflow_run | skipped | 38154407460 |
| 97 | 2026-10-12 11:37:07 | 0 | 0 | workflow_run | skipped | 38243803291 |
| 98 | 2026-10-12 11:37:26 | 0 | 1 | workflow_run | skipped | 38243839356 |
| 99 | 2026-10-12 13:39:36 | 0 | 1 | workflow_run | skipped | 38257237560 |
| 100 | 2026-10-12 13:39:59 | 0 | 10 | workflow_run | skipped | 38257281884 |

Totals: workflow_run/skipped 88, workflow_run/success 2, schedule/success 6,
schedule/failure 3, workflow_dispatch/failure 1 (first manual test, 09-29).

Heartbeat cron timing (slot 22:45Z of the weekday → actual run):

| slot (weekday 22:45Z) | fired | late by | conclusion |
|---|---|---|---|
| Mon 09-29 | 09-30 01:34 | 2 h 49 m | failure (heartbeat.py reported a miss) |
| Tue 09-30 | 10-01 01:35 | 2 h 50 m | success |
| Wed 10-01 | 10-02 01:48 | 3 h 03 m | success |
| Thu 10-02 | 10-03 01:26 | 2 h 41 m | success |
| Fri 10-03 | — | — | **no run** (see note) |
| Mon 10-05 | 10-06 02:30 | 3 h 45 m | failure (monitor had no success on 10-05 — correct) |
| Tue 10-06 | 10-07 01:48 | 3 h 03 m | success |
| Wed 10-07 | 10-08 02:16 | 3 h 31 m | success |
| Thu 10-08 | 10-09 02:33 | 3 h 48 m | success |
| Fri 10-09 | 10-10 01:54 | 3 h 09 m | failure (heartbeat.py reported a miss) |

Note on Fri 10-03: the run at 10-03 01:26Z is 2 h 41 m after Thu's slot, and
there is no run in 10-03 22:45Z → 10-04. With the observed ~3 h delay the
Thu slot and the Fri slot are not separable by timestamp alone; counting by
slot, 10 weekday slots produced 9 runs, so **one heartbeat cron firing is
missing or coalesced** (inference; cannot tell which). Counting Sep 29–Oct 9
inclusive from the workflow's merge (09-29 12:15Z, after the Mon slot had not
yet come): 9 of 9 slots whose firing could be attributed → the ticket's
"does the heartbeat's own cron ever miss" is **at least once ambiguous, never
clearly**. The daily heartbeat is reliably ~3 h late, never on time.

The `heartbeat.py` failures on 09-30 and 10-10 are the script's exit-code
contract (`scripts/heartbeat.py:20` "0 everything expected happened"; non-zero
emails a miss), not infrastructure failures; the 10-06 failure correctly
flags that 10-05 had no successful monitor run. Which routine the other two
flagged is out of scope here.

## 3. Documented: what GitHub says about `schedule`

From [Events that trigger workflows → `schedule`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) (fetched 2026-10-12):

> The `schedule` event can be delayed during periods of high loads of GitHub
> Actions workflow runs. High load times include the start of every hour. If
> the load is sufficiently high enough, some queued jobs may be dropped. To
> decrease the chance of delay, schedule your workflow to run at a different
> time of the hour.

> The shortest interval you can run scheduled workflows is once every 5 minutes.

> Scheduled workflows run on the latest commit on the default branch.

> In a public repository, scheduled workflows are automatically disabled when
> no repository activity has occurred in 60 days.

From [Disabling and enabling a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows):

> To prevent unnecessary workflow runs, scheduled workflows may be disabled
> automatically. When a public repository is forked, scheduled workflows are
> disabled by default. In a public repository, scheduled workflows are
> automatically disabled when no repository activity has occurred in 60 days.

From [About billing for GitHub Actions](https://docs.github.com/en/billing/managing-billing-for-your-products/about-billing-for-github-actions):

> GitHub Actions usage is free for self-hosted runners and for public
> repositories that use standard GitHub-hosted runners.

(GitHub Free: 2,000 min/month, 500 MB storage — for *private* repos.)

From [Actions limits](https://docs.github.com/en/actions/reference/limits): Free
plan allows 20 concurrent standard hosted jobs; no documented limit on
scheduled-workflow frequency beyond the 5-minute minimum; no queue-time limit
for hosted runners (24 h applies to self-hosted only).

From [Control workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency):

> At most one job or workflow run can be `pending` in the concurrency group.
> […] When the queue is full, any additional jobs or workflow runs are canceled.

A run cancelled by the concurrency group appears in the API as a run with
`conclusion: cancelled`; the monitor has exactly one such job and its
annotation names runner acquisition, not concurrency.

Community reports, 2026 (secondary; not GitHub statements, no staff replies in
either thread):
[Discussion #209514](https://github.com/orgs/community/discussions/209514)
(opened 2026-10-04): hourly cron `51 * * * *` "intermittent … gaps of several
hours", daily jobs ~5.5 h late, `workflow_dispatch` fine.
[Discussion #208729](https://github.com/orgs/community/discussions/208729)
(opened 2026-09-24): `7,22,37,52 * * * *` never fired at all; manual run fine.
Both match the pattern here (manual run #13 succeeded instantly; cron sparse
and hours late) and were filed in the same fortnight.

## 4. Inferences

1. **The divergence is GitHub's scheduler, not this repo.** Queue delay is
   0 s on every run, the job itself takes ~10 s, the repo is public (no
   minute budget), the workflow is `active` and lives on `main`, `pushed_at`
   is today (60-day rule irrelevant), and there is no concurrency contention.
   What remains is the documented "delayed … some queued jobs may be
   dropped" behaviour: of 16 slots a weekday, ~2 produce a run, each 4–7 h
   after the first slot. The docs' remedy (avoid the top of the hour) is not
   available in a useful form here: our minutes are `0,30`, and both of the
   2026 discussions above tried off-peak minutes without improvement, so I
   would not expect `7,37` to fix it (low confidence; untested on this repo).
2. **"Never started" vs "started late":** 211 of 240 slots left no run object
   (dropped before creation); 29 were created and started with zero queue
   delay; 1 was created and started but never acquired a hosted runner
   (10-05, cancelled at the 15-min timeout). So lateness and loss both happen
   at the event layer, with one runner-capacity incident on top.
3. **Heartbeat cron behaves like a once-a-day schedule should** under the same
   scheduler: always fires (with one ambiguous slot), ~3 h late. It is more
   reliable than the monitor only because it asks for 1 event/day instead of
   16; the per-event drop probability looks similar (each monitor "cluster"
   is one surviving event out of ~8).
4. **Coverage consequence:** since secrets were set on 09-29, the protection
   monitor has given one successful check per session, landing between
   14:16 and 15:15 ET — i.e. **never before 2:15 pm ET**. The 10 % trailing
   stop logic and the −7 % cut are therefore unguarded by this workflow for
   the first ~5 h of every session and for the whole of 10-05. The
   `PROJECT-STATUS.md:71` instruction "treat as a twice-daily coverage check,
   not a 30-min guard" is confirmed and should be tightened to "one
   mid-afternoon check plus one post-close check".
5. **Alternatives considered and rejected:** (a) the repo plan — public repo,
   unlimited minutes, 20 concurrent jobs; (b) concurrency group — no
   overlapping runs, no concurrency cancellations; (c) workflow disabled —
   `state: active`, runs continue; (d) runner queue — 0 s on all 130 runs.
   None explains the ~88 % slot loss; GitHub's best-effort scheduling does.

## 5. Method

```
gh api "repos/philipbergman6-glitch/TRADING-ROUTINE/actions/workflows/protection-monitor.yml/runs?per_page=100&created=>=2026-09-12" --paginate \
  --jq '.workflow_runs[] | [.id,.event,.status,.conclusion,.created_at,.run_started_at,.updated_at,.run_attempt,.head_branch] | @tsv'
gh api "repos/…/actions/workflows/heartbeat.yml/runs?per_page=100&created=>=2026-09-12" --paginate --jq '…same…'
gh api repos/…/actions/runs/37373280099/jobs          # cancelled job: no runner, no steps
gh api repos/…/check-runs/111975472680/annotations    # "not acquired by Runner of type hosted"
gh api repos/… --jq '{private,visibility,pushed_at}'  # public, pushed 2026-10-12
gh api repos/…/actions/workflows                      # all 4 workflows state=active
```

Totals returned by the API matched the paginated row counts (30 and 100).
Nothing was dispatched, re-run or edited on the Actions side.
