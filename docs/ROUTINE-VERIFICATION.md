# Routine verification — 2026-09-19

Evidence: owner-provided Claude routines screenshot and authenticated read of
GitHub main at `07603ef6614417faa1f68fedfbec77b284012980`. The local checkout
was fast-forwarded to this commit, preserving uncommitted documentation edits.

## Schedules and prompts

All five project routines are marked **Active** in the screenshot. The visible
prompt beginnings match the thin-prompt template in `routines/README.md`.
The screenshot truncates the remaining prompt text, so it cannot establish
the full saved prompt or the selected repository/environment.

| Routine | Displayed schedule | Repository instruction |
|---|---|---|
| pre-market | Weekdays 14:30 | `routines/pre-market.md` |
| market-open | Weekdays 16:30 | `routines/market-open.md` |
| midday | Weekdays 20:00 | `routines/midday.md` |
| daily-summary | Weekdays 23:00 | `routines/daily-summary.md` |
| weekly-review | Saturday 00:00 | `routines/weekly-review.md` |

These times match the documented America/Chicago cron schedules converted to
Asia/Jerusalem on September 18. The screenshot does not identify its timezone
or prove daylight-saving behavior across transition dates. Confirm scheduler
timezone and use exchange calendar checks for holidays and early closes.

The three E2BOT routines are also marked Active, but no E2BOT reference exists
in this repository's current tracked contents. Their attached repository,
account and relationship to Trading Routine remain unknown. Do not assume they
share a broker account or execution engine based on this screenshot.

## Evidence of recent operation

GitHub main was nine commits ahead of the original local inspection. All changes
were in logs and generated dashboard data; routine and execution code did not
change. Commits include September 17/18 midday reports and EOD snapshots,
September 18 pre-market research, and the September 18 weekly review. Several
commit messages link their originating Claude sessions. This confirms recent
committed outputs, not independent verification of broker operations.

- [Recent commits](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/commits/07603ef6614417faa1f68fedfbec77b284012980/)
- [Tests succeeded](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/35395224423)
- [Dashboard generation succeeded](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/35395224454)
- [Pages deployment succeeded](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/actions/runs/35395246740)

Latest logged EOD is September 18: equity $103,282.35, four positions,
approximately 79.9% deployed. These remain log-derived observations. After
synchronization, offline doctor and generated-data consistency passed, as did
all 24 dashboard tests. Current broker state and full private cloud settings
were not inspected; no routine was triggered or modified.
