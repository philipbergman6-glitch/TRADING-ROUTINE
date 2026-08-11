#!/usr/bin/env bash
# Shared env loader for the wrapper scripts. Sourced, never executed.
#
# Precedence: PROCESS ENV WINS over .env.
# The cloud routines export the real credentials as process env vars and are
# told there is no .env file. Locally there is one. Sourcing .env with `set -a`
# (the old behaviour) let a stale local file silently overwrite a deliberately
# exported override — including ALPACA_ENDPOINT, which decides paper vs live.
# So .env only fills in variables that are not already set.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue   # skip comments/blanks/junk
    [[ -n "${!key:-}" ]] && continue                        # process env wins
    export "$key=$value"
  done < "$ENV_FILE"
fi
