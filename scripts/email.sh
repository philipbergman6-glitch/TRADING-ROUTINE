#!/usr/bin/env bash
# Delivery-verified notification wrapper around the Resend API (ADR 0004).
# Usage: bash scripts/email.sh "<message>"        (or the message on stdin)
#
# Sends, captures the Resend email id, then reads the email back and checks
# its last_event. Exit 0 means Resend accepted the message and has not
# reported a bounce/failure; anything else is a loud failure the caller must
# treat as "the owner was NOT told":
#   1  usage (empty message)
#   2  send rejected: HTTP != 200, or no id in the response (body on stderr)
#   3  credentials unset (message also appended to EMAIL_FALLBACK_FILE)
#   4  Resend reports the email bounced / failed / suppressed / canceled
#   5  status unverifiable: GET /emails/{id} kept failing
# Env (optional): RESEND_API_BASE, EMAIL_STATUS_WAIT (s before the status read,
# default 5), EMAIL_STATUS_RETRY_WAIT (default 5), EMAIL_FALLBACK_FILE.
set -euo pipefail

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

FALLBACK="${EMAIL_FALLBACK_FILE:-$ROOT/DAILY-SUMMARY.md}"
API="${RESEND_API_BASE:-https://api.resend.com}"
STATUS_WAIT="${EMAIL_STATUS_WAIT:-5}"
STATUS_RETRY_WAIT="${EMAIL_STATUS_RETRY_WAIT:-5}"

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

missing=()
for v in RESEND_API_KEY EMAIL_TO EMAIL_FROM; do
  [[ -n "${!v:-}" ]] || missing+=("$v")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  printf "\n---\n## %s (NOT SENT — email not configured)\n%s\n" "$stamp" "$msg" >> "$FALLBACK"
  echo "email NOT SENT: ${missing[*]} unset; message appended to $FALLBACK" >&2
  exit 3
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

# One key per distinct payload: a retried identical send is deduplicated by
# Resend (same key + same body returns the original response); a different
# message in the same minute gets a different key.
idem="$(printf '%s' "$payload" | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
http="$(curl -sS -o "$body_file" -w '%{http_code}' --max-time 30 --retry 2 --retry-delay 3 \
  -X POST "$API/emails" \
  -H "Authorization: Bearer $RESEND_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $idem" \
  -d "$payload")" || { echo "email NOT SENT: curl failed (exit $?) talking to $API" >&2; exit 2; }
if [[ "$http" != "200" ]]; then
  echo "email NOT SENT: Resend returned HTTP $http: $(cat "$body_file")" >&2
  exit 2
fi
id="$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(d.get("id") or "")' "$body_file")"
if [[ -z "$id" ]]; then
  echo "email NOT SENT: Resend accepted without an id: $(cat "$body_file")" >&2
  exit 2
fi
echo "sent id=$id"

# Delivery status. Resend documents no sent->delivered latency; "sent" and
# "delivery_delayed" are accepted (delayed is retried by Resend for up to
# 14 h), the negative states are a failure the caller must surface elsewhere.
sleep "$STATUS_WAIT"
last_event=""
for attempt in 1 2 3; do
  http="$(curl -sS -o "$body_file" -w '%{http_code}' --max-time 30 \
    "$API/emails/$id" -H "Authorization: Bearer $RESEND_API_KEY")" || http="000"
  if [[ "$http" == "200" ]]; then
    last_event="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("last_event") or "")' "$body_file")"
    [[ -n "$last_event" ]] && break
  fi
  [[ "$attempt" -lt 3 ]] && sleep "$STATUS_RETRY_WAIT"
done
if [[ -z "$last_event" ]]; then
  echo "email id=$id status unverifiable: GET $API/emails/$id last HTTP $http: $(cat "$body_file")" >&2
  exit 5
fi
echo "last_event=$last_event"
case "$last_event" in
  bounced|failed|suppressed|canceled)
    echo "email id=$id NOT DELIVERED: last_event=$last_event" >&2
    exit 4 ;;
esac
