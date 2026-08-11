#!/usr/bin/env bash
# Research wrapper. All market research goes through Perplexity.
# Usage: bash scripts/perplexity.sh "<query>"
# Exits with code 3 if PERPLEXITY_API_KEY is unset so callers can fall back.
set -euo pipefail

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

query="${1:-}"
if [[ -z "$query" ]]; then
  echo "usage: bash scripts/perplexity.sh \"<query>\"" >&2
  exit 1
fi

if [[ -z "${PERPLEXITY_API_KEY:-}" ]]; then
  echo "WARNING: PERPLEXITY_API_KEY not set. Fall back to WebSearch." >&2
  exit 3
fi

MODEL="${PERPLEXITY_MODEL:-sonar}"

payload="$(python3 -c "
import json, sys
print(json.dumps({
  'model': sys.argv[1],
  'messages': [
    {'role': 'system', 'content': 'You are a precise financial research assistant. Cite every claim. Be concise.'},
    {'role': 'user', 'content': sys.argv[2]},
  ],
}))
" "$MODEL" "$query")"

curl -fsS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$payload"
echo
