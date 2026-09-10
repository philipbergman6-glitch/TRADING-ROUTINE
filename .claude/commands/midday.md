---
description: Midday scan — cut losers at -7%, tighten stops on winners, thesis check
---

## T4 — ledger on the live path (mandatory)

`validate_order.py` writes every verdict (approved **and** refused) to Postgres.
`--json` includes `ledger_order_id`. Exit **6** = ledger unavailable → STOP.
`DATABASE_URL` is required. This records; it does **not** bind validate→submit
([#19](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/19) still
open). Markdown remains the operational store
([#28](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/28)).

Capture after every validate (single-quoted `-c` — double quotes NameError on the key):

```
VALIDATE_JSON=$(python3 scripts/validate_order.py ... --json)
# exit 0 or 3 both leave a ledger row; exit 6 → STOP
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
```

After every successful mutating order submit, persist the broker response
(existing Ledger API — `submit` / `stop` only; no invented cancel writer).
Derive real HTTP status via `ALPACA_HTTP_STATUS_FILE` (alpaca.sh writes curl
`%{http_code}`; never hardcode 200). Re-assign `LEDGER_ORDER_ID` from **each**
validate `--json` before the matching `record_broker_response`:

```
HTTP_STATUS_FILE=$(mktemp)
RESP=$(ALPACA_HTTP_STATUS_FILE="$HTTP_STATUS_FILE" ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$ORDER_JSON")
HTTP_STATUS=$(cat "$HTTP_STATUS_FILE"); rm -f "$HTTP_STATUS_FILE"
python3 scripts/record_broker_response.py \
    --order-id "$LEDGER_ORDER_ID" --kind submit --http-status "$HTTP_STATUS" \
    --response "$RESP"
```

Trail/protective places that are separate broker orders: `--kind stop`
(Ledger `record_stop` / protection). Parent entry OTO: `--kind submit`.

You are running the midday scan workflow. Resolve today's date via:
DATE=$(date +%Y-%m-%d).

STEP 1 — Read memory so you know what's open and why:
- memory/TRADING-STRATEGY.md (exit rules)
- tail of memory/TRADE-LOG.md (entries, original thesis per position, stops)
- today's memory/RESEARCH-LOG.md entry

STEP 2 — Pull current state:
bash scripts/alpaca.sh positions
bash scripts/alpaca.sh orders

STEP 2b — On-entry ADR 0002 convergence (leftover fixed legs).
Scan open orders from STEP 2 for leftover fixed protective sells —
`side=sell`, `type=stop` (NOT `trailing_stop`), trail fields null/absent —
covering a held position. Convert each via CONVERT_FIXED_TO_TRAIL_STEPS
(cancel then order). Do NOT leave convergence as wishful "next routine" prose.

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent 10 --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0:
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID
TRAIL_JSON=$(python3 scripts/build_oto_order.py trail --symbol SYM --qty N --trail-percent 10)
HTTP_STATUS_FILE=$(mktemp)
RESP=$(ALPACA_HTTP_STATUS_FILE="$HTTP_STATUS_FILE" ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$TRAIL_JSON")
HTTP_STATUS=$(cat "$HTTP_STATUS_FILE"); rm -f "$HTTP_STATUS_FILE"
python3 scripts/record_broker_response.py \
    --order-id "$LEDGER_ORDER_ID" --kind stop --http-status "$HTTP_STATUS" \
    --response "$RESP"
On exit 3 → log, keep scanning. On exit 4 → STOP. On exit 6 → STOP (ledger). If convert fails after
cancel, email loudly and retry the trail place.

STEP 3 — Cut losers immediately. For every position where
unrealized_plpc <= -0.07, validate the sell through the risk engine first
(paper + position coherence). Do NOT skip validate_order:

VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
Exit 0 = approved → proceed.
Exit 3 = refused → log violations verbatim; do not close.
Exit 4 = broker state unavailable → STOP, email alert, exit.

On approve (mutating alpaca requires ALPACA_RISK_OK=1).
Order is mandatory cancel-then-close (#38 / CUT_LOSER_STEPS): close alone
403s while reserved, and close-then-cancel leaves the loser held AND naked.
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID   # release reserved shares
ALPACA_RISK_OK=1 bash scripts/alpaca.sh close SYM
Log the exit to TRADE-LOG: exit price, realized P&L, "cut at -7% per rule".

STEP 4 — Tighten trailing stops on winners. Ladder is owned by the engine
(`required_trail_percent` via `scripts/validate_stop_change.py`) — do NOT
hand-compute 15%/20% thresholds in prose.

For each position with a resting trailing stop:
  G = unrealized_plpc * 100          # e.g. 0.16 → 16
  C = current trail_percent on the open sell order
  P = current mark price

Ask the engine for the widest trail still permitted, then validate the change:
T=$(python3 scripts/validate_stop_change.py --gain-pct G --print-required)
# Skip if already at or tighter than required (nothing to tighten).
python3 scripts/validate_stop_change.py --gain-pct G --proposed-trail T \
    --current-trail C --current-price P --json
Exit 0 = approved trail/stop change (wires required_trail_percent +
validate_stop_change on implied stops).
Exit 3 = refused → skip tighten, log violations verbatim.
Exit 2 = usage → STOP, fix inputs.

Then validate the replacement protective sell (T1) before mutating:
VALIDATE_JSON=$(python3 scripts/validate_order.py --symbol SYM --qty N --side sell \
    --price P --trail-percent T --json)
LEDGER_ORDER_ID=$(printf "%s" "$VALIDATE_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ledger_order_id"])')
On exit 0 (TRAIL_TIGHTEN_STEPS = cancel then order — never reverse):
ALPACA_RISK_OK=1 bash scripts/alpaca.sh cancel ORDER_ID
TRAIL_JSON=$(python3 scripts/build_oto_order.py trail --symbol SYM --qty N --trail-percent T)
HTTP_STATUS_FILE=$(mktemp)
RESP=$(ALPACA_HTTP_STATUS_FILE="$HTTP_STATUS_FILE" ALPACA_RISK_OK=1 bash scripts/alpaca.sh order "$TRAIL_JSON")
HTTP_STATUS=$(cat "$HTTP_STATUS_FILE"); rm -f "$HTTP_STATUS_FILE"
python3 scripts/record_broker_response.py \
    --order-id "$LEDGER_ORDER_ID" --kind stop --http-status "$HTTP_STATUS" \
    --response "$RESP"
On validate_order exit 3 → skip tighten, log. On exit 4 → STOP. On exit 6 → STOP (ledger).
#40 PATCH resize is OPEN — do not invent a patch path; cancel→replace still
has a brief naked window. T2 validates the stop/trail change; it does not
close that window.

STEP 5 — Thesis check. If a thesis broke intraday, cut the position even
if not at -7% yet — same validate_order + ALPACA_RISK_OK cancel-then-close gate
as STEP 3. Document reasoning in TRADE-LOG.

STEP 6 — Optional intraday research via Perplexity if something is moving
sharply with no obvious cause. Append afternoon addendum to RESEARCH-LOG.

STEP 7 — Notification: only if action was taken.
bash scripts/email.sh "<action summary>"
