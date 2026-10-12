# 0009 — Can alert delivery be confirmed? Resend status, webhooks, limits, and our senders' failure modes

Date: 2026-10-12. Resolves wayfinder research ticket #102 (parent map #93).
Sources: Resend primary docs (resend.com/docs, resend.com/pricing), GitHub
Actions docs (docs.github.com), the curl man page, and this repo's
`scripts/email.sh`, `scripts/protection_monitor.py`, `scripts/heartbeat.py`,
`.github/workflows/heartbeat.yml`, `.github/workflows/protection-monitor.yml`.
No email was sent and no Resend call was made while researching. Each claim
is marked **[doc]** (stated by the cited source), **[code]** (read directly in
this repo at the commit on `main` 5a9dfc0), or **[inference]**.

## Summary

- **Yes, delivery can be confirmed, but we do not do it today.** `POST /emails`
  returns `{"id": ...}`; `GET /emails/{id}` returns `last_event` whose values
  include `sent`, `delivered`, `delivery_delayed`, `bounced`, `complained`,
  `failed`, `suppressed`. Our `email.sh` discards the `id` [code].
- **Timing:** Resend documents no SLA for `sent -> delivered`. The one documented
  bound is on the unhappy path: a `delivery_delayed` email is retried "for up
  to 14 hours" and then becomes `bounced` [doc]. So a status is not reliably
  final for ~14 h; polling a few seconds after send tells you only whether
  the first delivery attempt has already succeeded [inference].
- **Webhooks exist** (`email.delivered`, `email.bounced`, `email.complained`,
  `email.delivery_delayed`, `email.failed`, ...), signed via Svix headers, with
  8-attempt exponential backoff. They require a POST endpoint we do not have;
  a GitHub Actions runner cannot be that endpoint [doc + inference].
- **Limits:** 10 requests/second/team by default; Free plan 100 emails/day,
  3,000/month, 1 webhook endpoint. `Idempotency-Key` header, <=256 chars,
  kept 24 h; reuse with a different body is a 409 `invalid_idempotent_request`
  [doc].
- **Today on send failure:** `curl -fsS` makes `email.sh` exit non-zero (curl
  exit 22 on HTTP >= 400) and print only a one-line curl error to stderr. Both
  Python callers run it with `check=False`, so the failure changes nothing:
  no exit-code change, no retry, no second channel. Only the direct
  `heartbeat.yml:42` step turns an email failure into a failed workflow run
  [code]. With credentials missing, `email.sh` appends to `DAILY-SUMMARY.md`
  on the runner and exits 0; neither workflow commits, so that text is lost
  when the job ends [code + inference].
- **Cheap second channel:** `gh issue create` from the workflow (gh is
  preinstalled; needs `GH_TOKEN` and `issues: write`) plus GitHub's own
  per-user "only notify for failed workflows" email. Both are free and need
  no new infrastructure [doc].

## Q1. Send response ID and `GET /emails/{id}` delivery status

**Send response.** The Send Email reference's example response is
`{"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}`; no other response field is
documented [doc]. <https://resend.com/docs/api-reference/emails/send-email>

**Retrieve.** `GET https://api.resend.com/emails/{id}` returns `object`, `id`,
`message_id`, `to`, `from`, `created_at`, `subject`, `html`, `text`, `bcc`,
`cc`, `reply_to`, `last_event`, `scheduled_at`, `tags`. Example shows
`"last_event": "delivered"` and the page defers the value list to the Email
Events overview [doc]. <https://resend.com/docs/api-reference/emails/retrieve-email>

**States** ("Understand email events", verbatim definitions) [doc]:
<https://resend.com/docs/dashboard/emails/manage-emails>

| `last_event` | Definition |
|---|---|
| `sent` | "The email was sent successfully." |
| `delivered` | "Resend successfully delivered the email to the recipient's mail server." |
| `delivery_delayed` | "The email couldn't be delivered to the recipient's mail server because a temporary issue occurred." |
| `bounced` | "The recipient's mail server rejected the email." |
| `complained` | "The email was successfully delivered to the recipient's mail server, but the recipient marked it as spam." |
| `failed` | "The email failed to be sent." |
| `suppressed` | "The email was not sent because the recipient is on the suppression list." |
| `queued` | "The email created from Broadcasts or Batches is queued for delivery." |
| `scheduled` | "The email is scheduled for delivery." |
| `canceled` | "The scheduled email was canceled (by user)." |
| `opened` / `clicked` | Engagement events (open tracking noted as not always accurate). |

The webhook event-types page adds the gloss that `email.sent` "Occurs whenever
the API request was successful" [doc]. <https://resend.com/docs/webhooks/event-types>
So a 200 from `POST /emails` is equivalent to `sent`, i.e. accepted by Resend,
not accepted by the recipient's server [inference from the two definitions].

**How quickly do they settle?** The only timing statement found: a
`delivery_delayed` email is retried automatically and "Resend keeps retrying
automatically for up to 14 hours"; if still not accepted it becomes `bounced`
[doc, manage-emails page]. No page states a typical `sent -> delivered`
latency or declares which states are terminal. `delivered` is the first
positive confirmation; `bounced`, `failed`, `suppressed` are negative. The
API reference does not say how soon after send the ID is queryable [doc,
<https://resend.com/docs/api-reference/introduction>]. I am not confident
about typical happy-path latency; SMTP handoff is usually seconds, but that is
general knowledge, not a Resend commitment [inference].

**Bounce reasons** are not in the retrieve response (only the `last_event`
string); the bounce detail object (`type` e.g. `Permanent`/`Temporary`,
`subType` e.g. `Suppressed`/`MessageRejected`, `message`, `diagnosticCode[]`)
is documented only on the `email.bounced` webhook payload [doc].
<https://resend.com/docs/webhooks/emails/bounced>

## Q2. Webhooks for delivery and bounce events; do we need a receiver?

**Available events** (email family) [doc, <https://resend.com/docs/webhooks/event-types>]:
`email.sent`, `email.delivered`, `email.delivery_delayed`, `email.bounced`,
`email.complained`, `email.failed`, `email.suppressed`, `email.opened`,
`email.clicked`, `email.received`, `email.scheduled`. Payload `data` carries
`email_id`, `message_id`, `from`, `to`, `subject`, `tags`, `created_at`
(plus `bounce` on bounced) [doc, <https://resend.com/docs/webhooks/emails/sent>].

**Receiver requirement.** Webhooks are "real-time HTTPS requests that tell
your application an event occurred"; setup is "Create a route that can accept
POST requests" then "Define a webhook with the URL of your endpoint" [doc].
<https://resend.com/docs/webhooks/introduction> Verification reads
`svix-id`, `svix-timestamp`, `svix-signature` headers against a signing
secret from the webhook details page [doc].
<https://resend.com/docs/webhooks/verify-webhooks-requests>

**Retries.** Exponential backoff over eight attempts: immediate, then 5 s,
5 min, 30 min, 2 h, 5 h, 10 h, 10 h. An endpoint that "keeps failing to
receive events" is disabled automatically with an email notification;
messages can be replayed from the dashboard [doc].
<https://resend.com/docs/webhooks/retries-and-replays>

**Do we have a receiver?** No. This repo runs only GitHub Actions jobs and
Claude cloud routines [code: `.github/workflows/`, `routines/`]. A runner has
no stable public URL and lives for minutes, so it cannot host a webhook
endpoint [inference]. A webhook would need a new always-on HTTPS receiver
(e.g. a serverless function) that we do not operate. **Polling
`GET /emails/{id}` from the same job needs no new infrastructure** and is
the only confirmation path available to us without one [inference].
Free plan allows "1 endpoint" for webhooks [doc, <https://resend.com/pricing>].

## Q3. Rate limits and idempotency on send

**Rate limit.** "The default maximum rate limit is 10 requests per second per
team." Headers: `ratelimit-limit`, `ratelimit-remaining`, `ratelimit-reset`
(seconds), `retry-after` (seconds). Over the limit returns HTTP 429
(`rate_limit_exceeded`). Increases via support [doc].
<https://resend.com/docs/api-reference/rate-limit>

**Quotas.** Free plan: "limited to 100 emails per day", 3,000/month, 3
domains, 30-day data retention [doc, <https://resend.com/pricing>]. Exceeding
the daily quota is 429 `daily_quota_exceeded`, resetting at midnight UTC
[doc, <https://resend.com/docs/api-reference/errors>]. Our volume is a handful
of emails per trading day [code: the five routines, protection monitor on
issue/action only, heartbeat on miss only], so the per-second limit is not a
practical concern; the 100/day cap only matters if a retry loop misbehaves
[inference].

**Idempotency.** `Idempotency-Key` request header (SMTP uses
`Resend-Idempotency-Key`). "Idempotency keys can be up to 256 characters and
must be unique per API request"; "kept in the system for 24 hours". Same key
+ same body: original response returned "without actually sending the email
again". Same key + different body: 409 `invalid_idempotent_request`. Same key
while first still in flight: 409 `concurrent_idempotent_requests` (safe to
retry). Also supported on `POST /emails/batch` [doc].
<https://resend.com/docs/dashboard/emails/idempotency-keys>
<https://resend.com/docs/api-reference/emails/send-email>

Implication: a retry loop around `curl` is safe from duplicates only if every
attempt sends the same `Idempotency-Key` and an identical body. Our body
includes a per-run `stamp` in the subject (`email.sh:23,40`), so one key per
`email.sh` invocation (e.g. `${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-<sha of
msg>`) would satisfy both constraints [inference].

**Error codes relevant to us** [doc, <https://resend.com/docs/api-reference/errors>
and <https://resend.com/docs/api-reference/introduction>]: 400
`validation_error` (bad `from`/`to`), 401 `missing_api_key`, 403 invalid API
key, 429 rate/quota, 500 `application_error` ("Retry later"). Only 429 and
5xx are retry-worthy; 4xx other than 429 are configuration faults [inference].

## Q4. A cheap second channel from GitHub Actions

**(a) Create a GitHub issue from the failing job.** "GitHub CLI is
preinstalled on all GitHub-hosted runners." Each step using it "must set an
environment variable called `GH_TOKEN`". The docs' own example runs
`gh issue create --title "Issue report" --body "..." --repo $GITHUB_REPOSITORY`
from a scheduled workflow [doc].
<https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/using-github-cli-in-workflows>
The automatic-token guide's issue-creating example sets `issues: write` on the
job [doc]. <https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication>
Our workflows today grant `heartbeat.yml` only `contents: read, actions: read`
[code `.github/workflows/heartbeat.yml:16-18`] and `protection-monitor.yml`
sets no `permissions` block [code]; `issues: write` would have to be added
[inference]. Issue creation by `GITHUB_TOKEN` does not itself trigger new
workflow runs ("events triggered by the `GITHUB_TOKEN` will not create a new
workflow run", exceptions `workflow_dispatch`/`repository_dispatch`) [doc].
<https://docs.github.com/en/actions/concepts/security/github_token>
An issue generates GitHub's normal web/email notification to repo watchers,
so it reaches the owner through a channel independent of Resend [inference
from GitHub notifications being the owner's normal issue feed; the exact
notification routing is a user setting].

**(b) Let the workflow run itself fail, and use GitHub's Actions
notifications.** "If you enable email or web notifications for GitHub
Actions, you'll receive a notification when any workflow runs that you've
triggered have completed"; "You can also choose to receive a notification
only when a workflow run has failed." For scheduled workflows,
"Notifications ... are sent to the user who initially created the workflow",
shifting to whoever last edited the cron or re-enabled the workflow [doc].
<https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs>
Setting path: Notification settings > System > Actions > "Email" and "Only
notify for failed workflows" [doc].
<https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications>
This is per-user and only works if the job exits non-zero, which, for the
Python callers, requires removing `check=False` or otherwise propagating the
email failure [inference, see Q5]. Caveat: the workflow creator is a single
GitHub account, so this is a one-person channel [doc + inference].

**(c) `workflow_run` chaining**, already used by `heartbeat.yml:11-13`,
triggers "regardless of the conclusion of the previous workflow" (filter via
`github.event.workflow_run.conclusion`), only for workflow files on the
default branch, and "can't ... chain together more than three levels" [doc].
<https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>
Its weakness as a fallback: the heartbeat's own reaction to a failed workflow
is to call `email.sh` again (`heartbeat.yml:42`), i.e. the same channel that
may have just failed [code + inference]. `schedule` "can be delayed during
periods of high loads" and public-repo cron is disabled after 60 days of
inactivity [doc, same page].

**Recommendation (inference):** (a) is the cheapest independent channel: one
`gh issue create` step guarded by `if: failure()`, plus `issues: write`.
Pair it with (b) by making email failure fail the job. Webhooks are not
worth a receiver for this volume; polling `GET /emails/{id}` once ~10-30 s
after send and recording `last_event` in the job log gives a cheap
"accepted vs delivered" signal, with the caveat that `delivery_delayed` can
take up to 14 h to resolve.

## Q5. What happens today on send failure (file:line)

### `scripts/email.sh`

- `:5` `set -euo pipefail` — any failing command aborts the script with that
  command's exit status [code].
- `:25-30` if any of `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM` is empty: append
  `## <stamp> (fallback — email not configured)` + message to
  `$ROOT/DAILY-SUMMARY.md` (`:10`), echo `[email fallback] appended to
  DAILY-SUMMARY.md`, echo the message, **`exit 0`** [code]. In Actions this
  file lives on the ephemeral runner; neither `heartbeat.yml` nor
  `protection-monitor.yml` has a commit/push step and `heartbeat.yml` grants
  only `contents: read`, so the appended text is discarded at job end
  [code + inference]. A missing secret therefore looks like success to every
  caller.
- `:42-45` `curl -fsS -X POST https://api.resend.com/emails ...` with no
  `Idempotency-Key`, no retry flags, no `--max-time`, and the response body
  is written to stdout but **never parsed; the returned `id` is not
  captured** [code]. The curl man page: `-f/--fail` means "Fail with error
  code 22 and with no response body output at all for HTTP transfers
  returning HTTP response codes at 400" and "is not fail-safe" [doc,
  <https://curl.se/docs/manpage.html>]. `-S` prints a one-line error to
  stderr despite `-s` [doc, same]. Net effect of any HTTP 4xx/5xx from
  Resend (bad key 401/403, validation 400, quota 429, 5xx): `email.sh`
  exits 22, the Resend JSON error body is suppressed, and a single
  `curl: (22) The requested URL returned error: 4xx` line is the only
  trace [code + doc]. Network failures surface as other non-zero curl
  codes [inference]. On HTTP 200 the script prints `{"id":...}` and
  exits 0; this proves only `sent` (API accepted), not delivery (Q1)
  [inference].

### `scripts/protection_monitor.py`

- `:76-82` `notify()` builds the lines and runs
  `subprocess.run(["bash", str(EMAIL), ...], check=False, timeout=60)`; the
  return value is discarded [code].
- `:107-108` `notify(report)` is called only when `args.email and (code != 0
  or results)`; `main()` then `return code` — **the exit code is computed
  before `notify` and is unaffected by it** [code]. `:113` `raise
  SystemExit(main())`.
- So on send failure: curl's stderr line appears in the job log, the step's
  exit status stays whatever the protection result was, no retry, no other
  channel, and the JSON report (already printed at `:106`) exists only in
  the run log [code + inference]. If the protection exit is non-zero the
  workflow fails for that reason and `heartbeat.yml` fires — and tries the
  same email channel (`heartbeat.yml:39-42`) [code].
- `timeout=60` with no `curl --max-time`: a hung Resend connection raises
  `subprocess.TimeoutExpired` after 60 s, which is **not caught** in
  `notify()` or `main()` [code `:82`, `:84-109`], so the process would
  terminate with a traceback and exit 1 — an alert failure that does fail
  the job, but by accident [inference].

### `scripts/heartbeat.py`

- `:137-140` when `report["issues"]` and not `--no-email`: body is built and
  `subprocess.run(["bash", str(EMAIL), body], check=False, timeout=60)`;
  result discarded [code].
- `:141` `return report["exit"]` — exit code (5 on missed expectations, per
  the docstring `:22`) is independent of the email outcome [code].
- Same `TimeoutExpired` exposure as above (`:140`, not caught; the
  `except` at `:132` covers only the data-gathering block) [code].
- `:132-134` if Alpaca/git/`gh api` fail, `EXIT_NO_STATE` is returned and
  **no email is attempted at all** [code].

### `.github/workflows/heartbeat.yml`

- `:39-42` on `workflow_run` failure of `protection-monitor`,
  `dashboard-data` or `tests`, the step runs `bash scripts/email.sh
  "WORKFLOW FAILED: ..."` directly. Here `set -e` + `curl -f` **does**
  propagate: an email failure fails this step and the heartbeat run [code].
  But `heartbeat` is not in its own `workflows:` list (`:12`), so nothing
  reacts to a failed heartbeat except GitHub's per-user Actions
  notification, if the owner has enabled it [code + inference].
- `:43-45` the scheduled path runs `python3 scripts/heartbeat.py`, where the
  `check=False` behaviour above applies [code].

### Net: the single point of silent failure

An alert from `protection_monitor.py` or `heartbeat.py` can be lost with
(a) missing secrets (exit 0, text on a discarded runner disk), (b) any
Resend 4xx/5xx or network error (one stderr line, job status unchanged),
or (c) Resend accepting the message and the recipient server later bouncing
it (no code path ever reads `last_event`). None of these three produces a
second signal today [code + inference].

## Open points

- Whether the owner's GitHub Actions notification setting is enabled is a
  user-account setting I cannot read from the repo; treat (b) in Q4 as
  unverified until checked.
- Typical `sent -> delivered` latency is undocumented by Resend; the 14-hour
  figure bounds only the delayed path.
- Not checked: whether `EMAIL_FROM` is on a verified domain (a 400/403 would
  be silent today for the Python callers for the reasons above).
