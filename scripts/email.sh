#!/usr/bin/env bash
# Notification wrapper. Sends an email via the Resend API.
# Usage: bash scripts/email.sh "<message>"
# If credentials are unset, appends to a local fallback file.
set -euo pipefail

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

FALLBACK="$ROOT/DAILY-SUMMARY.md"

if [[ $# -gt 0 ]]; then
  msg="$*"
else
  msg="$(cat)"
fi

if [[ -z "${msg// /}" ]]; then
  echo "usage: bash scripts/email.sh \"<message>\"" >&2
  exit 1
fi

stamp="$(date '+%Y-%m-%d %H:%M %Z')"

if [[ -z "${RESEND_API_KEY:-}" || -z "${EMAIL_TO:-}" || -z "${EMAIL_FROM:-}" ]]; then
  printf "\n---\n## %s (fallback — email not configured)\n%s\n" "$stamp" "$msg" >> "$FALLBACK"
  echo "[email fallback] appended to DAILY-SUMMARY.md"
  echo "$msg"
  exit 0
fi

payload="$(python3 -c "
import json, sys
print(json.dumps({
    'from': sys.argv[1],
    'to': [sys.argv[2]],
    'subject': sys.argv[3],
    'text': sys.argv[4],
}))
" "$EMAIL_FROM" "$EMAIL_TO" "Trading Brief — $stamp" "$msg")"

curl -fsS -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer $RESEND_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$payload"
echo
