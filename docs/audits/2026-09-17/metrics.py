"""Recompute log-derived audit measurements; no broker or network access."""
from datetime import date
import json
from math import prod
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import build_dashboard_data as b

snaps = b.parse_trade_log(b.TRADE_LOG.read_text())
weeks = b.parse_weekly_review(b.WEEKLY_REVIEW.read_text())
peak = snaps[0]["v"]
worst = 0
discrepancies = []
for i, snap in enumerate(snaps):
    peak = max(peak, snap["v"])
    worst = min(worst, 100 * (snap["v"] / peak - 1))
    if i:
        prev = snaps[i - 1]
        implied = 100 * (snap["v"] / prev["v"] - 1)
        if abs(implied - snap["dp"]) > .025:
            discrepancies.append({
                "date": snap["d"], "prior_date": prev["d"],
                "calendar_day_gap": (date.fromisoformat(snap["d"]) - date.fromisoformat(prev["d"])).days,
                "equity_change_pct": round(implied, 6), "logged_day_pct": snap["dp"],
            })
print(json.dumps({
    "basis": "Committed markdown; unreconciled with broker; no external-cash-flow adjustment",
    "first_date": snaps[0]["d"], "last_date": snaps[-1]["d"],
    "snapshot_count": len(snaps), "last_phase_day": snaps[-1]["n"],
    "initial_equity": snaps[0]["v"], "last_equity": snaps[-1]["v"],
    "equity_return_pct": 100 * (snaps[-1]["v"] / snaps[0]["v"] - 1),
    "peak_equity": peak, "max_observed_eod_drawdown_pct": worst,
    "weekly_observations": len(weeks), "last_week": weeks[-1]["w"],
    "weekly_bot_compounded_pct": 100 * (prod(1 + w["bot"] / 100 for w in weeks) - 1),
    "weekly_benchmark_compounded_pct": 100 * (prod(1 + w["spxc"] / 100 for w in weeks) - 1),
    "estimated_benchmark_weeks": sum(w["est"] for w in weeks),
    "daily_return_discrepancies": discrepancies,
}, indent=2))
