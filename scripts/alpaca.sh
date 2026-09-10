#!/usr/bin/env bash
# Alpaca API wrapper. All trading API calls go through here.
# Usage: bash scripts/alpaca.sh <subcommand> [args...]
set -euo pipefail

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

API="${ALPACA_ENDPOINT:-https://paper-api.alpaca.markets/v2}"
DATA="${ALPACA_DATA_ENDPOINT:-https://data.alpaca.markets/v2}"

# PAPER-ONLY GUARD — checked before anything else, including credentials, so it
# holds even in a keyless environment. This bot places orders autonomously with
# no human in the loop, so an unset or mistyped ALPACA_ENDPOINT must never
# silently resolve to production. Hard-fail: a silent live order is the worst
# failure mode this repo has.
if [[ "$API" != *"paper-api.alpaca.markets"* && "${ALPACA_ALLOW_LIVE:-0}" != "1" ]]; then
  echo "REFUSING: ALPACA_ENDPOINT is not a paper endpoint ($API)." >&2
  echo "This bot is paper-only. Export ALPACA_ALLOW_LIVE=1 to override." >&2
  exit 4
fi

: "${ALPACA_API_KEY:?ALPACA_API_KEY not set in environment}"
: "${ALPACA_SECRET_KEY:?ALPACA_SECRET_KEY not set in environment}"

H_KEY="APCA-API-KEY-ID: $ALPACA_API_KEY"
H_SEC="APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"

# Optional HTTP-status capture for T4 ledger writes. When the caller exports
# ALPACA_HTTP_STATUS_FILE to a path, write curl's %{http_code} there and keep
# stdout as the response body only. Unset → legacy _curl (no status file).
_curl() {
  local status_file="${ALPACA_HTTP_STATUS_FILE:-}"
  if [[ -z "$status_file" ]]; then
    _curl "$@"
    return
  fi
  local tmp code
  tmp=$(mktemp)
  code=$(curl -sS -o "$tmp" -w "%{http_code}" "$@" || true)
  printf "%s" "$code" > "$status_file"
  cat "$tmp"
  rm -f "$tmp"
  # Match curl -f: treat HTTP 4xx/5xx as failure.
  if [[ "$code" =~ ^[45][0-9][0-9]$ ]]; then
    echo "alpaca.sh: HTTP $code" >&2
    return 22
  fi
}


cmd="${1:-}"
shift || true

# RISK-ENGINE GATE — mutating subcommands refuse unless ALPACA_RISK_OK=1.
# Callers must run scripts/validate_order.py first (exit 0), then re-invoke
# with ALPACA_RISK_OK=1. Read-only subcommands never need the flag.
# validate_order.py itself only uses read paths, so there is no recursion.
case "$cmd" in
  order|close|close-all|cancel|cancel-all)
    if [[ "${ALPACA_RISK_OK:-0}" != "1" ]]; then
      echo "REFUSING: mutating command '$cmd' requires risk-engine approval." >&2
      echo "Run: python3 scripts/validate_order.py ... (exit 0), then" >&2
      echo "     ALPACA_RISK_OK=1 bash scripts/alpaca.sh $cmd ..." >&2
      exit 5
    fi
    ;;
esac

case "$cmd" in
  account)
    _curl -H "$H_KEY" -H "$H_SEC" "$API/account"
    ;;
  positions)
    _curl -H "$H_KEY" -H "$H_SEC" "$API/positions"
    ;;
  position)
    sym="${1:?usage: position SYM}"
    _curl -H "$H_KEY" -H "$H_SEC" "$API/positions/$sym"
    ;;
  quote)
    sym="${1:?usage: quote SYM}"
    _curl -H "$H_KEY" -H "$H_SEC" "$DATA/stocks/$sym/quotes/latest"
    ;;
  orders)
    status="${1:-open}"
    _curl -H "$H_KEY" -H "$H_SEC" "$API/orders?status=$status"
    ;;
  order)
    body="${1:?usage: order '<json>'}"
    _curl -H "$H_KEY" -H "$H_SEC" -H "Content-Type: application/json" \
      -X POST -d "$body" "$API/orders"
    ;;
  cancel)
    oid="${1:?usage: cancel ORDER_ID}"
    _curl -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/orders/$oid"
    ;;
  cancel-all)
    _curl -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/orders"
    ;;
  close)
    sym="${1:?usage: close SYM}"
    _curl -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/positions/$sym"
    ;;
  close-all)
    _curl -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/positions"
    ;;
  *)
    echo "Usage: bash scripts/alpaca.sh <account|positions|position|quote|orders|order|cancel|cancel-all|close|close-all> [args]" >&2
    exit 1
    ;;
esac
echo
