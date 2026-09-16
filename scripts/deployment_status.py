#!/usr/bin/env python3
"""Rule 12 deployment backstop: is a leadership add mandated today?

The risk engine refuses orders; it never compels one (UNMECHANISED
"min_deployment_backstop"). This script is the routine-side half: it counts
consecutive EOD snapshots in memory/TRADE-LOG.md below the 75% band floor and
combines that with live deployment from the broker, so "3 sessions under band"
is computed, not remembered.

    python3 scripts/deployment_status.py            # live account via alpaca.sh
    python3 scripts/deployment_status.py --equity 102827.45 --long-market-value 62196.92

Prints one JSON object:
    deployed_pct, sessions_under_band, mandate, exemption_allowed,
    target_notional (dollars to add toward the 80% midpoint, capped at the
    20% position limit and available cash), last_eod.

Exit codes:
    0  no mandate
    5  mandate due -- the market-open routine MUST add a leadership position
    2  usage error
    4  state unavailable (broker call failed, or trade log stale/unparseable)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BAND_LOW = Decimal("75")
BAND_MID = Decimal("80")
MAX_POSITION_PCT = Decimal("20")
MANDATE_SESSIONS = 3
# Fri close -> Tue pre-market over a holiday weekend is 4 days; anything older
# means an EOD run was missed and the session count cannot be trusted.
MAX_LOG_AGE_DAYS = 5


def _load_log_parser():
    spec = importlib.util.spec_from_file_location(
        "build_dashboard_data", REPO / "scripts" / "build_dashboard_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sessions_under_band(snaps) -> int:
    """Consecutive EOD snapshots, newest first, with deployment below the floor."""
    n = 0
    for s in reversed(snaps):
        if Decimal("100") - Decimal(str(s["cash"])) < BAND_LOW:
            n += 1
        else:
            break
    return n


def evaluate(snaps, equity: Decimal, long_market_value: Decimal, cash: Decimal,
             today: date) -> dict:
    if equity <= 0:
        raise ValueError(f"equity must be positive, got {equity}")
    last = snaps[-1]["d"]
    age = (today - date.fromisoformat(last)).days
    if age < 0 or age > MAX_LOG_AGE_DAYS:
        raise ValueError(
            f"latest EOD snapshot {last} is {age} days from {today}; "
            f"session count untrustworthy (max {MAX_LOG_AGE_DAYS})")
    deployed = (long_market_value / equity * 100).quantize(Decimal("0.01"))
    under = sessions_under_band(snaps)
    # Live back in band (e.g. a buy already filled) clears the mandate.
    mandate = under >= MANDATE_SESSIONS and deployed < BAND_LOW
    gap = equity * BAND_MID / 100 - long_market_value
    cap = equity * MAX_POSITION_PCT / 100
    target = max(Decimal("0"), min(gap, cap, cash)).quantize(Decimal("1"), ROUND_DOWN)
    return {
        "deployed_pct": float(deployed),
        "band": [float(BAND_LOW), 85.0],
        "sessions_under_band": under,
        "mandate": mandate,
        # One deferral only, on the first due session, and only for a named
        # market-wide risk event scheduled that day. After that, no exemption.
        "exemption_allowed": mandate and under == MANDATE_SESSIONS,
        "target_notional": int(target) if mandate or deployed < BAND_LOW else 0,
        "last_eod": last,
    }


def live_account() -> tuple[Decimal, Decimal, Decimal]:
    r = subprocess.run(["bash", str(REPO / "scripts" / "alpaca.sh"), "account"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"alpaca.sh account failed: {r.stderr.strip()}")
    a = json.loads(r.stdout)
    return Decimal(a["equity"]), Decimal(a["long_market_value"]), Decimal(a["cash"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--equity", type=Decimal)
    p.add_argument("--long-market-value", type=Decimal)
    p.add_argument("--cash", type=Decimal)
    p.add_argument("--trade-log", type=Path, default=REPO / "memory" / "TRADE-LOG.md")
    p.add_argument("--today", type=date.fromisoformat,
                   default=datetime.now(timezone.utc).date())
    args = p.parse_args(argv)

    manual = (args.equity, args.long_market_value)
    if any(v is not None for v in manual) and not all(v is not None for v in manual):
        print("--equity and --long-market-value must be given together", file=sys.stderr)
        return 2
    try:
        bdd = _load_log_parser()
        snaps = bdd.parse_trade_log(args.trade_log.read_text(encoding="utf-8"))
        if args.equity is None:
            equity, lmv, cash = live_account()
        else:
            equity, lmv = args.equity, args.long_market_value
            cash = args.cash if args.cash is not None else equity - lmv
        result = evaluate(snaps, equity, lmv, cash, args.today)
    except Exception as e:  # noqa: BLE001 -- any failure means state unknown
        print(f"DEPLOYMENT STATE UNAVAILABLE: {type(e).__name__}: {e}", file=sys.stderr)
        return 4
    print(json.dumps(result))
    return 5 if result["mandate"] else 0


if __name__ == "__main__":
    sys.exit(main())
