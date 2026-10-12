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
# The drill profile reads .env.drill instead, so the two key pairs never sit in
# one process: .env holds ALPACA_*, .env.drill holds DRILL_ALPACA_*.
if [[ "${ALPACA_PROFILE:-production}" == "drill" ]]; then
  ENV_FILE="$ROOT/.env.drill"
else
  ENV_FILE="$ROOT/.env"
fi

if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue   # skip comments/blanks/junk
    [[ -n "${!key:-}" ]] && continue                        # process env wins
    export "$key=$value"
  done < "$ENV_FILE"
fi
