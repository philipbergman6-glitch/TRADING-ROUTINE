#!/usr/bin/env bash
# Once-a-day alert for a send-only Resend key (ticket #147, ADR 0007).
# Usage: bash scripts/alert_unverified.sh <marker-file>
#
# The marker is EMAIL_UNVERIFIED_FILE: scripts/email.sh appends a line each
# time Resend accepted an email whose delivery could not be read because
# RESEND_API_KEY is send-only (401 restricted_api_key on GET /emails/{id}).
# The alerts still went out, so this never fails the job; it emits one
# workflow warning and opens today's GitHub issue unless one with the same
# title already exists (open or closed): the owner hears once a day, through
# the channel that does not depend on Resend. A missing or empty marker means
# nothing to do. Needs gh with GH_TOKEN (issues: write) and GITHUB_REPOSITORY.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: bash scripts/alert_unverified.sh <marker-file>" >&2
  exit 1
fi
marker="$1"
[[ -s "$marker" ]] || exit 0
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY unset}"

count="$(grep -c . "$marker")"
echo "::warning title=Alert delivery unverifiable::delivery unverifiable: restricted key. $count email(s) sent but not verified: RESEND_API_KEY is send-only. Replace it with a full-access key (ticket #147)."

title="ALERT DELIVERY UNVERIFIED $(date -u +%F): Resend key is send-only"
existing="$(gh issue list -R "$GITHUB_REPOSITORY" --state all --search "\"$title\" in:title" \
  --json number,title --jq ".[] | select(.title == \"$title\") | .number")"
if [[ -n "$existing" ]]; then
  echo "already alerted today: issue #${existing%%$'\n'*}"
  exit 0
fi

run_url="${GITHUB_SERVER_URL:-https://github.com}/$GITHUB_REPOSITORY/actions/runs/${GITHUB_RUN_ID:-unknown}"
body="Alert emails went out, but their delivery could not be checked: Resend answered \`GET /emails/{id}\` with 401 \`restricted_api_key\`, so \`RESEND_API_KEY\` is a sending-only key and a bounce would go unnoticed.

**Owner:** replace the \`RESEND_API_KEY\` repository secret with a full-access Resend key. See ticket #147.

Run: $run_url

Emails sent, unverified:
\`\`\`
$(cat "$marker")
\`\`\`"
gh issue create -R "$GITHUB_REPOSITORY" --title "$title" --body "$body"
