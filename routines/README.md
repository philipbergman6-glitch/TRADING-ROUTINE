# Cloud Routine Prompts

Paste each of these verbatim into its Claude Code cloud routine. Do not
paraphrase. The env-var check block and the commit-and-push step are
load-bearing.

## Cron schedules (America/Chicago)

| Routine        | Cron           | File                    |
|----------------|----------------|-------------------------|
| Pre-market     | `0 6 * * 1-5`  | `pre-market.md`         |
| Market-open    | `30 8 * * 1-5` | `market-open.md`        |
| Midday         | `0 12 * * 1-5` | `midday.md`             |
| Daily summary  | `0 15 * * 1-5` | `daily-summary.md`      |
| Weekly review  | `0 16 * * 5`   | `weekly-review.md`      |

## One-time prerequisites per routine

1. Install Claude GitHub App on this repo. Routines land work via auto-merged PRs and need only the App's default `contents: write` + `pull-requests: write` permissions — no unrestricted-push override required.
2. Set env vars on the routine (NOT in a committed .env file):
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_ENDPOINT`,
   `ALPACA_DATA_ENDPOINT`, `PERPLEXITY_API_KEY`, `PERPLEXITY_MODEL`,
   `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM`.
