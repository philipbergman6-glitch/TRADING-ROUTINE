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
if [[ "$API" != "https://paper-api.alpaca.markets/v2" ]]; then
  echo "REFUSING: ALPACA_ENDPOINT is not a paper endpoint ($API)." >&2
  echo "This deployment is paper-only; no live override is supported." >&2
  exit 4
fi
if [[ "$DATA" != "https://data.alpaca.markets/v2" ]]; then
  echo "REFUSING: unrecognized ALPACA_DATA_ENDPOINT." >&2
  exit 4
fi

: "${ALPACA_API_KEY:?ALPACA_API_KEY not set in environment}"
: "${ALPACA_SECRET_KEY:?ALPACA_SECRET_KEY not set in environment}"

H_KEY="APCA-API-KEY-ID: $ALPACA_API_KEY"
H_SEC="APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"

# Optional HTTP-status capture for T4 ledger writes. When the caller exports
# ALPACA_HTTP_STATUS_FILE to a path, write curl's %{http_code} there and keep
# stdout as the response body only. Unset → real curl -fsS (no recursion).
_curl() {
  local status_file="${ALPACA_HTTP_STATUS_FILE:-}"
  if [[ -z "$status_file" ]]; then
    curl --connect-timeout 10 --max-time 30 -fsS "$@"
    return
  fi
  local tmp code transport=0
  tmp=$(mktemp)
  code=$(curl --connect-timeout 10 --max-time 30 -sS -o "$tmp" -w "%{http_code}" "$@") || transport=$?
  printf "%s" "$code" > "$status_file"
  cat "$tmp"
  rm -f "$tmp"
  # Match curl -f: treat HTTP 4xx/5xx as failure.
  if [[ "$transport" != 0 ]]; then
    echo "alpaca.sh: transport failure ($transport); outcome unknown, reconcile before retry." >&2
    return "$transport"
  fi
  if [[ ! "$code" =~ ^2[0-9][0-9]$ ]]; then
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
    # A refusal before HTTP is not a broker success. Clear a reused capture
    # file so callers cannot accidentally ledger an earlier request's 200.
    if [[ -n "${ALPACA_HTTP_STATUS_FILE:-}" ]]; then
      printf "000" > "$ALPACA_HTTP_STATUS_FILE"
    fi
    if [[ "${ALPACA_RISK_OK:-0}" != "1" ]]; then
      echo "REFUSING: mutating command '$cmd' requires risk-engine approval." >&2
      echo "Run: python3 scripts/validate_order.py ... (exit 0), then" >&2
      echo "     ALPACA_RISK_OK=1 bash scripts/alpaca.sh $cmd ..." >&2
      exit 5
    fi
    # Validate this exact command/body against broker state. The env flag is
    # only caller intent; it is never proof of a previous validation.
    python3 "$(dirname "$0")/validate_mutation.py" "$cmd" "${1:-}" >&2
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
    after="${2:-}"
    [[ "$status" =~ ^(open|closed|all)$ ]] || { echo "usage: orders [open|closed|all] [AFTER_ISO_UTC]" >&2; exit 2; }
    url="$API/orders?status=$status&limit=500"
    if [[ -n "$after" ]]; then
      # Bounded window: an unfiltered closed-order history grows forever and
      # would eventually hit the 500-row page cap and block every validation.
      [[ "$after" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || { echo "orders: AFTER must be YYYY-MM-DDTHH:MM:SSZ" >&2; exit 2; }
      url="$url&after=$after"
    fi
    _curl -H "$H_KEY" -H "$H_SEC" "$url"
    ;;
  activities)
    # Read-only fill history for the blotter. Alpaca pages by id: pass the last
    # id of the previous page as PAGE_TOKEN. AFTER bounds the window.
    after="${1:-}"
    token="${2:-}"
    url="$API/account/activities/FILL?direction=asc&page_size=100"
    if [[ -n "$after" ]]; then
      [[ "$after" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || { echo "activities: AFTER must be YYYY-MM-DDTHH:MM:SSZ" >&2; exit 2; }
      url="$url&after=$after"
    fi
    if [[ -n "$token" ]]; then
      [[ "$token" =~ ^[A-Za-z0-9:_-]{1,80}$ ]] || { echo "activities: invalid PAGE_TOKEN" >&2; exit 2; }
      url="$url&page_token=$token"
    fi
    _curl -H "$H_KEY" -H "$H_SEC" "$url"
    ;;
  asset)
    sym="${1:?usage: asset SYM}"
    _curl -H "$H_KEY" -H "$H_SEC" "$API/assets/$sym"
    ;;
  order-info)
    oid="${1:?usage: order-info ORDER_ID}"
    _curl -H "$H_KEY" -H "$H_SEC" "$API/orders/$oid"
    ;;
  order-by-client)
    # Idempotency probe for resumable stop replacement: 404 means "never
    # submitted" and prints null; transport failure means unknown and exits 7.
    cid="${1:?usage: order-by-client CLIENT_ORDER_ID}"
    [[ "$cid" =~ ^[A-Za-z0-9-]{1,48}$ ]] || { echo "order-by-client: invalid client_order_id" >&2; exit 2; }
    tmp=$(mktemp)
    code=$(curl --connect-timeout 10 --max-time 30 -sS -o "$tmp" -w "%{http_code}" \
      -H "$H_KEY" -H "$H_SEC" "$API/orders:by_client_order_id?client_order_id=$cid") \
      || { rm -f "$tmp"; echo "alpaca.sh: transport failure; outcome unknown" >&2; exit 7; }
    if [[ "$code" == "404" ]]; then
      echo "null"
    elif [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
      cat "$tmp"
    else
      rm -f "$tmp"; echo "alpaca.sh: HTTP $code" >&2; exit 22
    fi
    rm -f "$tmp"
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
    echo "Usage: bash scripts/alpaca.sh <account|positions|position|quote|orders|order-info|order-by-client|activities|asset|order|cancel|cancel-all|close|close-all> [args]" >&2
    exit 1
    ;;
esac
echo
