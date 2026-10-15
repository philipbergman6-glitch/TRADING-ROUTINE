#!/usr/bin/env python3
"""Regenerate docs/dashboard/data.js from memory/ logs. Deterministic, no LLM.

Parses:
  - memory/TRADE-LOG.md   -> EQ  (every "EOD Snapshot" header + its
                                  **Portfolio:** line — daily closes ONLY;
                                  midday entries are prose-only audit trail)
                          -> BOOK (positions table of the latest EOD snapshot)
  - memory/WEEKLY-REVIEW.md -> WEEKS (Stats table of each "## Week ending" section)
  - state/events.jsonl     -> RUNS (run records, ADR 0012: machine-written by
                              every routine and monitor run; runs started
                              before LOG_ASOF only, so a later record cannot
                              make the committed data.js stale)
  - memory/BLOTTER.json    -> TRADES (scripts/blotter.py --json, written by the
                              daily summary from broker fills: FIFO round
                              trips and open lots; open lots must equal the
                              latest EOD book or the build fails)

FEED / RISK and per-date chart notes are curated, not derivable
from the logs — they are written below and dated by ANALYSIS_ASOF, which the
dashboard displays alongside the (separate) latest-log date.

HARD-FAILS on any parse mismatch. Never publishes partial or stale data.
"""

import re
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts.run_record import MalformedRunRecord, fold  # noqa: E402
from scripts.state_store import STATE_FILE, CorruptState, replay  # noqa: E402

STATE = REPO / STATE_FILE
TRADE_LOG = REPO / "memory" / "TRADE-LOG.md"
WEEKLY_REVIEW = REPO / "memory" / "WEEKLY-REVIEW.md"
BLOTTER = REPO / "memory" / "BLOTTER.json"
SECTORS = REPO / "memory" / "SECTORS.json"
OUT = REPO / "docs" / "dashboard" / "data.js"

# Engineering test fills (research 0006 excludes them from every figure).
# Excluded here by symbol, and the exclusion is printed in the blotter label.
TEST_SYMBOLS = frozenset({"F"})

YEAR = 2026
DAY0_DATE = "2026-04-27"  # "Day 0" baseline header carries no calendar date

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


class ParseError(RuntimeError):
    pass


def fail(msg):
    raise ParseError(msg)


def parse_header_date(label):
    """'Apr 30' / 'Jul 1' / '2026-06-25' / 'Day 0' -> ISO date string."""
    label = label.strip()
    if label == "Day 0":
        return DAY0_DATE
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", label)
    if m:
        return label
    m = re.fullmatch(r"([A-Z][a-z]{2})\s+(\d{1,2})", label)
    if m:
        mon = MONTHS.get(m.group(1)) or fail(f"unknown month in header: {label!r}")
        return date(YEAR, mon, int(m.group(2))).isoformat()
    fail(f"unparseable snapshot header date: {label!r}")


def parse_money(s):
    m = re.fullmatch(r"[+\-−]?\$([\d,]+(?:\.\d+)?)", s.strip())
    if not m:
        fail(f"unparseable dollar amount: {s!r}")
    v = float(m.group(1).replace(",", ""))
    return -v if s.strip()[0] in "-−" else v


def parse_pct(s):
    m = re.fullmatch(r"[+\-−]?([\d.]+)%", s.strip())
    if not m:
        fail(f"unparseable percent: {s!r}")
    v = float(m.group(1))
    return -v if s.strip()[0] in "-−" else v


def fmt(v, nd):
    return f"{v:.{nd}f}"


def js_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --------------------------------------------------------------------------
# TRADE-LOG.md -> EQ + BOOK
# --------------------------------------------------------------------------

# EQ is a daily-close series: ONLY "EOD Snapshot" headers feed it. Midday
# headers ("Midday Scan", and the one-off "Midday Cut" of Jun 15) are measured
# at a different time of day, so plotting them alongside closes would corrupt
# the curve, the day-P&L bars and max drawdown. Do not widen this alternation
# without giving midday its own series — see the assert in parse_trade_log.
SNAP_HDR = re.compile(r"^#{2,3}\s+(.+?)\s+—\s+(EOD Snapshot)\b(.*)$")
DAY_NO = re.compile(r"\(Day\s+(\d+)\b")
PORTFOLIO = re.compile(
    r"^\*\*Portfolio:\*\*\s+(\$[\d,]+(?:\.\d+)?)\s+\|\s+"
    r"\*\*Cash:\*\*\s+\$[\d,]+(?:\.\d+)?\s+\(([\d.]+)%\)\s+\|\s+"
    r"\*\*Day P&L:\*\*\s+([+\-−]?\$[\d,]+(?:\.\d+)?)(?:\s+\(([+\-−]?[\d.]+)%\))?")
POS_HDR = re.compile(
    r"^\|\s*Ticker\s*\|\s*Shares\s*\|\s*Entry\s*\|\s*Close\s*\|\s*Day Chg\s*\|"
    r"\s*Unrealized P&L\s*\|\s*Stop\s*\|")


def parse_trade_log(text):
    lines = text.split("\n")
    snaps = []  # {date, kind, v, cash, dp, positions: [...] | None}
    i = 0
    while i < len(lines):
        m = SNAP_HDR.match(lines[i])
        if not m:
            i += 1
            continue
        d = parse_header_date(m.group(1).split("(")[0])
        kind = m.group(2)
        if kind != "EOD Snapshot":
            fail(f"EQ is a daily-close series but '{lines[i].strip()}' is a "
                 f"{kind}; intraday observations need their own series")
        # phase day number — "Day 0" baseline carries none, every other header must
        if m.group(1).strip() == "Day 0":
            n = 0
        else:
            nm = DAY_NO.search(m.group(3))
            if not nm:
                fail(f"snapshot '{lines[i].strip()}' has no '(Day N' phase counter")
            n = int(nm.group(1))
        # the **Portfolio:** line must follow within a few lines
        pm = None
        for j in range(i + 1, min(i + 4, len(lines))):
            pm = PORTFOLIO.match(lines[j])
            if pm:
                break
        if not pm:
            fail(f"snapshot '{lines[i].strip()}' has no **Portfolio:** line")
        dp = parse_pct(pm.group(4) + "%") if pm.group(4) else 0.0
        snap = {"d": d, "n": n, "kind": kind, "v": parse_money(pm.group(1)),
                "cash": float(pm.group(2)), "dp": dp, "positions": None}
        # positions table (EOD snapshots)
        for j in range(i + 1, min(i + 8, len(lines))):
            if POS_HDR.match(lines[j]):
                rows = []
                k = j + 2  # skip separator row
                while k < len(lines) and lines[k].startswith("|"):
                    cells = [c.strip() for c in lines[k].strip().strip("|").split("|")]
                    if len(cells) != 7:
                        fail(f"positions row has {len(cells)} cells, expected 7: {lines[k]!r}")
                    if cells[0] != "—":
                        rows.append(cells)
                    k += 1
                snap["positions"] = rows
                break
        snaps.append(snap)
        i += 1
    if not snaps:
        fail("no EOD Snapshot headers found in TRADE-LOG.md")
    dates = [s["d"] for s in snaps]
    if dates != sorted(dates):
        fail(f"snapshot dates out of order: {dates}")
    if len(dates) != len(set(dates)):
        fail(f"duplicate snapshot dates: {dates}")
    return snaps


def build_book(snap):
    """Latest EOD snapshot positions table -> BOOK entries."""
    if snap["kind"] != "EOD Snapshot":
        fail(f"latest snapshot ({snap['d']}) is a {snap['kind']}, not an EOD Snapshot")
    if snap["positions"] is None:
        fail(f"latest EOD snapshot ({snap['d']}) has no positions table")
    book = []
    for sym, shares, entry, close, _daychg, unreal, stop in snap["positions"]:
        um = re.fullmatch(r"([+\-−]\$[\d,]+(?:\.\d+)?)\s+\(([+\-−][\d.]+%)\)", unreal.strip())
        if not um:
            fail(f"unparseable Unrealized P&L for {sym}: {unreal!r}")
        sm = re.match(r"\**\$?([\d.]+)", stop.strip())  # the log may bold the level
        if not sm:
            fail(f"unparseable stop for {sym}: {stop!r}")
        stop_s = sm.group(1)
        frac = stop_s.split(".")[1] if "." in stop_s else ""
        if len(frac) > 3:  # display at most 3 decimals; round longer to cents
            stop_s = fmt(float(stop_s), 2)
        q = int(shares)
        close_v = parse_money(close)
        w = round(q * close_v / snap["v"] * 100, 1)
        book.append({
            "s": sym, "q": q, "in": parse_money(entry),
            "pl": parse_money(um.group(1)), "plp": parse_pct(um.group(2)),
            "stop": stop_s, "w": w,
            "protection": "trailing" if "trail" in stop.lower() else "fixed" if "fixed" in stop.lower() else "unspecified",
        })
    return book


# --------------------------------------------------------------------------
# WEEKLY-REVIEW.md -> WEEKS
# --------------------------------------------------------------------------

WEEK_HDR = re.compile(r"^## Week ending (\d{4})-(\d{2})-(\d{2})\s*$", re.MULTILINE)

# Index levels inside the 'S&P 500 week' row, e.g. "7,483.24 Jul 03 → 7,543.64".
# 5+ leading digit/comma chars keeps this from matching the percent itself.
SPX_LEVEL = re.compile(r"\b([\d,]{5,}\.\d+)\b")

# Known discontinuities in the logged S&P series: each week re-fetched a
# starting level instead of chaining from the prior week's logged close, so the
# series is not continuous. These five are grandfathered and documented in the
# 'Benchmark Data Errata' section of WEEKLY-REVIEW.md. Any NEW break, or a
# grandfathered one that has since been repaired, hard-fails the build.
#   week ending -> (prior week's logged close, this week's logged start)
KNOWN_SPX_CHAIN_BREAKS = {
    "2026-07-24": (7475.69, 7441.68),
    "2026-07-31": (7417.10, 7411.98),
    "2026-08-07": (7437.63, 7489.72),
    "2026-08-21": (7798.99, 7785.76),
    "2026-08-28": (7637.80, 7674.37),
}


def stats_row(block, metric):
    m = re.search(r"^\|\s*" + re.escape(metric) + r"\s*\|\s*(.+?)\s*\|\s*$",
                  block, re.MULTILINE)
    if not m:
        fail(f"weekly review block missing stats row {metric!r}")
    return m.group(1)


def parse_weekly_review(text):
    """Parse weekly stats and build a CONTINUOUS benchmark series.

    Each week records the S&P return it observed at the time ('spx', kept
    verbatim as the contemporaneous record). Because those weeks were fetched
    independently, the quoted start level sometimes disagrees with the prior
    week's quoted close. 'spxc' re-derives each week from the chained closes so
    the plotted benchmark is a valid continuous series; weeks whose levels are
    unavailable fall back to the logged figure and are flagged est=True.
    """
    weeks = []
    matches = list(WEEK_HDR.finditer(text))
    if not matches:
        fail("no '## Week ending YYYY-MM-DD' sections in WEEKLY-REVIEW.md")
    prev_close = None
    seen_breaks = {}
    for n, m in enumerate(matches):
        wk_end = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        block = text[m.end(): matches[n + 1].start() if n + 1 < len(matches) else len(text)]
        ret = stats_row(block, "Week return")
        rm = re.search(r"\(([+\-−][\d.]+)%\)", ret)
        if not rm:
            fail(f"no (%) in 'Week return' row: {ret!r}")
        spx_raw = stats_row(block, "S&P 500 week")
        sm = re.match(r"([+\-−]?[\d.]+)%", spx_raw)
        if not sm:
            fail(f"'S&P 500 week' row does not start with a percent: {spx_raw!r}")
        spx_logged = parse_pct(sm.group(1) + "%")

        levels = [float(v.replace(",", "")) for v in SPX_LEVEL.findall(spx_raw)]
        if levels and len(levels) < 2:
            fail(f"'S&P 500 week' row for {wk_end} quotes one index level, "
                 f"expected a start AND a close: {spx_raw!r}")
        start, close = (levels[0], levels[1]) if levels else (None, None)

        # the quoted percent must agree with the quoted levels
        if start is not None:
            implied = (close / start - 1) * 100
            if abs(implied - spx_logged) > 0.06:
                fail(f"{wk_end}: levels imply {implied:+.2f}% but row says "
                     f"{spx_logged:+.2f}%: {spx_raw!r}")
            # continuity against the prior week's close
            if prev_close is not None and abs(prev_close - start) > 0.01:
                seen_breaks[wk_end] = (round(prev_close, 2), round(start, 2))

        if prev_close is not None and close is not None:
            spx_chained = (close / prev_close - 1) * 100
            est = False
        else:
            spx_chained = spx_logged  # no levels to chain from — first weeks
            est = True

        weeks.append({"w": f"{m.group(2)}/{m.group(3)}",
                      "bot": parse_pct(rm.group(1) + "%"),
                      "spx": spx_logged,
                      "spxc": spx_chained,
                      "est": est})
        if close is not None:
            prev_close = close

    unknown = {k: v for k, v in seen_breaks.items() if KNOWN_SPX_CHAIN_BREAKS.get(k) != v}
    if unknown:
        fail("NEW S&P chain break(s) — each week must start at the prior week's "
             "logged close. Fix the log, or document and grandfather in "
             f"KNOWN_SPX_CHAIN_BREAKS: {unknown}")
    repaired = set(KNOWN_SPX_CHAIN_BREAKS) - set(seen_breaks)
    if repaired:
        fail(f"grandfathered S&P chain break(s) no longer present: {sorted(repaired)} "
             "— remove them from KNOWN_SPX_CHAIN_BREAKS and from the errata section")
    return weeks


# --------------------------------------------------------------------------
# memory/BLOTTER.json -> TRADES
# --------------------------------------------------------------------------
# The daily summary writes `scripts/blotter.py --json` (broker fills, FIFO)
# to memory/BLOTTER.json next to the EOD snapshot. Fills are the record; the
# dashboard orders them for a reader: open lots first (newest entry first),
# then closed round trips, newest exit first.

CHIP_BY_SECTOR = {"Information Technology": "tech", "Communication Services": "tech",
                  "Energy": "enrg"}
SHORT_SECTOR = {"Information Technology": "TECH", "Communication Services": "COMMS",
                "Energy": "ENERGY", "Consumer Staples": "STAPLES",
                "Consumer Discretionary": "DISCRETIONARY", "Materials": "MATERIALS",
                "Industrials": "INDUSTRIALS", "Financials": "FINANCIALS"}


def read_blotter():
    if not BLOTTER.exists():
        fail(f"{BLOTTER.relative_to(REPO)} missing: run scripts/blotter.py --json > memory/BLOTTER.json")
    try:
        data = json.loads(BLOTTER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"BLOTTER.json is not valid JSON: {exc}")
    for key in ("round_trips", "open_lots"):
        if not isinstance(data.get(key), list):
            fail(f"BLOTTER.json lacks a '{key}' list")
    return data


def sector_chip(symbol, sectors):
    sector = sectors.get(symbol)
    if not sector:
        fail(f"{symbol} traded but missing from memory/SECTORS.json")
    short = SHORT_SECTOR.get(sector, sector.upper())
    if symbol.startswith("XL"):
        return "etf", f"{short} ETF"
    return CHIP_BY_SECTOR.get(sector, "oth"), short


def signed_money(v):
    v = float(v)
    return f"{'+' if v >= 0 else '−'}{abs(v):,.2f}"


def build_trades(blotter, book, log_asof):
    """BLOTTER.json -> TRADES rows, open lots first, then newest exit first."""
    sectors = json.loads(SECTORS.read_text(encoding="utf-8"))
    asof = date.fromisoformat(log_asof)
    opens = [o for o in blotter["open_lots"] if o["symbol"] not in TEST_SYMBOLS]
    closed = [r for r in blotter["round_trips"] if r["symbol"] not in TEST_SYMBOLS]

    lots = sorted(o["symbol"] for o in opens)
    held = sorted(b["s"] for b in book)
    if lots != held:
        fail(f"BLOTTER.json open lots {lots} do not match the latest EOD book {held}: "
             "refresh the blotter with the EOD snapshot")

    rows = []
    for o in sorted(opens, key=lambda o: o["entered"], reverse=True):
        entered = date.fromisoformat(o["entered"][:10])
        chip, label = sector_chip(o["symbol"], sectors)
        rows.append({"d": entered.isoformat(), "s": o["symbol"], "sec": chip, "lbl": label,
                     "q": int(o["qty"]), "in": f"{float(o['avg_in']):.2f}", "out": None,
                     "days": (asof - entered).days, "pl": None, "plp": None, "open": 1})
    for r in sorted(closed, key=lambda r: (r["exited"], r["entered"]), reverse=True):
        entered = date.fromisoformat(r["entered"][:10])
        exited = date.fromisoformat(r["exited"][:10])
        chip, label = sector_chip(r["symbol"], sectors)
        pnl = float(r["pnl"])
        rows.append({"d": entered.isoformat(), "s": r["symbol"], "sec": chip, "lbl": label,
                     "q": int(r["qty"]), "in": f"{float(r['avg_in']):.2f}",
                     "out": f"{exited.isoformat()} · {float(r['avg_out']):.2f}",
                     "days": (exited - entered).days,
                     "pl": {"v": signed_money(pnl), "up": 1 if pnl >= 0 else 0},
                     "plp": signed_money(r["pnl_pct"]), "open": 0})
    return rows


# --------------------------------------------------------------------------
# state/events.jsonl -> RUNS
# --------------------------------------------------------------------------

RECENT_RUNS = 12


def parse_state(text):
    try:
        return replay(text)
    except CorruptState as exc:
        fail(str(exc))


def read_state():
    """Events on the checked-out main. The file is created by the first run
    record; until then there are none."""
    return parse_state(STATE.read_text(encoding="utf-8") if STATE.exists() else "")


def summarize_runs(events, log_asof):
    """Run records started before `log_asof` (UTC dates), newest first.

    The cutoff is what keeps the golden check honest: data.js is regenerated
    only when memory/** changes, while the monitor appends run records every
    30 minutes with a token that triggers no workflow. Every line dated before
    the latest EOD log was already on main when that log's rebuild ran.
    Every record is validated, not only the shown ones: one malformed line
    anywhere hard-fails the build."""
    try:
        fold(events)
        shown = fold([e for e in events if e.get("kind") == "run" and e["at"][:10] < log_asof])
    except MalformedRunRecord as exc:
        fail(str(exc))
    recent = []
    for run in sorted(shown, key=lambda r: r.started_at, reverse=True)[:RECENT_RUNS]:
        s = run.start
        recent.append({
            "run": run.run, "r": run.routine, "t": run.trigger,
            "s": run.started_at, "e": run.ended_at, "o": run.outcome or "unfinished",
            "sha": s["code_sha"][:7], "dirty": s["code_dirty"],
            "rb": s["rulebook_version"] + ("" if s["rulebook_pinned"] else " UNPINNED"),
            "m": s["model_id"] or s["model_source"],
            "n": {"a": len(run.actions), "r": len(run.refusals), "i": len(run.incidents),
                  "in": len(run.intents)},
        })
    outcomes = {}
    for run in shown:
        key = run.outcome or "unfinished"
        outcomes[key] = outcomes.get(key, 0) + 1
    return {
        "since": min((r.started_at[:10] for r in shown), default=None),
        "through": (date.fromisoformat(log_asof) - timedelta(days=1)).isoformat(),
        "total": len(shown),
        "unfinished": sum(r.ended_at is None for r in shown),
        "outcomes": dict(sorted(outcomes.items())),
        "recent": recent,
    }


# --------------------------------------------------------------------------
# Curated content — dated by ANALYSIS_ASOF below, NOT by the latest log.
#
# These two dates drift apart on purpose: the logs regenerate nightly, the
# editorial does not. The dashboard surfaces both so a stale narrative can
# never sit behind a "LIVE" badge. When you revise the prose below, bump
# ANALYSIS_ASOF in the same commit.
ANALYSIS_ASOF = "2026-10-15"

#
# FEED / RISK and the per-date chart notes are editorial: they
# cannot be derived from the logs, so they are written by hand and dated.
# Figures that DO move with the logs (deployment %, phase day, the blotter)
# are generated above — never bake a live number in here.
# --------------------------------------------------------------------------

# Chart-point annotations by date; dates without an entry get note:"".
EQ_NOTES = {
    "2026-04-27": "Day 0 baseline",
    "2026-04-30": "AMD +11.96% unrealized",
    "2026-05-27": "MU +8.58% · XOM closed +$95",
    "2026-06-04": "PEAK +10.27% — only 36% deployed",
    "2026-06-09": "MSFT & NVDA stops fired — full reset",
    "2026-06-10": "Redeployed into XOM",
    "2026-06-12": "First weekly review written",
    "2026-06-17": "100% cash — FOMC hold",
    "2026-06-18": "100% cash",
    "2026-06-19": "100% cash",
    "2026-06-22": "/conviction run: DELL ✓ GNRC ✓ MU refused",
    "2026-06-23": "100% cash",
    "2026-06-24": "100% cash — 6th straight idle session",
    "2026-06-25": "Idle streak broken: GOOGL + XLF bought",
    "2026-06-29": "XLF→XLI/XLB sector rotation",
    "2026-06-30": "XLP added — INSIDE 75–85% band for the first time",
    "2026-07-03": "Best week: +2.24%, beat S&P",
    "2026-07-06": "Post-reset high",
    "2026-07-15": "GOOGL +10.55% intraweek high",
    "2026-07-22": "GOOGL 0.7% above its stop into Q2 print",
    "2026-07-23": "GOOGL gapped through stop: −$832.73 (−3.99%)",
    "2026-07-24": "Weekly review: source a single-name engine",
    "2026-07-27": "All 3 positions green on cost",
    "2026-08-04": "Fresh phase high — all 3 green on cost",
    "2026-08-07": "Rule 12 written: deployment backstop after 3 idle sessions",
    "2026-08-10": "Rule 12 fires: XLK bought — 60.4% → 80.2%, back in band",
    "2026-09-14": "XLI stop fires: −$1,575 after 77 days",
    "2026-09-17": "XLE bought — energy sleeve opened",
    "2026-09-28": "MPC bought — first single name since GOOGL (rule 14)",
    "2026-09-30": "XLB stop fires: −$948 after 93 days",
    "2026-10-02": "PSX bought — second refiner",
    "2026-10-13": "STRATEGY_VERSION unset: market-open halts at the version gate",
}

STATIC_TAIL = '''\
// Commentary as of __ANALYSIS_ASOF__; not a live safety certification.
// Decision tape: curated highlights, newest first.
const FEED = [
{d:"10/13", b:"sys",  x:"<b>STRATEGY_VERSION unset in the cloud routine environment</b>: market-open and midday stop at the version gate (exit 5) before any broker call — owner configuration, not code. The protection monitor (Actions variable set) keeps covering the book."},
{d:"10/13", b:"sys",  x:"v1 frozen at tag <b>v1-baseline</b>: coordinator lease + intent recovery (ADR 0010) and per-run records (ADR 0012) now wrap every mutation."},
{d:"10/02", b:"trade",x:"PSX 57 @ $264.20 — second refiner. <b>validate_order exit 0</b>, bracket entry, protective leg converted to a 10% trail."},
{d:"09/30", b:"cut",  x:"XLB fixed stop fires at $48.77: <b>−$947.79 (−4.50%)</b> after 93 days. Book is now energy-led."},
{d:"09/28", b:"trade",x:"MPC 13 @ $396.33 — <b>first single name since GOOGL</b>, under rule 14's composition mandate."},
{d:"09/19", b:"sys",  x:"Research 0006: full fill history pulled read-only and <b>reconciled to equity to the cent</b>. Bot +3.28% vs SPY +7.04% to Sep 18; the ETF segment is the drag."},
{d:"09/17", b:"trade",x:"XLE 311 @ $63.92 — energy sleeve opened."},
{d:"09/14", b:"cut",  x:"XLI trailing stop fires at $168.58: <b>−$1,575.36 (−7.46%)</b>."},
{d:"08/11", b:"sys",  x:"Benchmark audit: the logged S&amp;P series <b>broke chain 3×</b> (weeks 07/24, 07/31, 08/07). Chart now plots the re-chained series — <b>which is worse for the bot</b>. Build hard-fails on any new break."},
{d:"08/10", b:"trade",x:"<b>Rule 12 fires on its own deadline</b> — XLK 112 @ $187.85. Deployment 60.4% → 80.2%, back in band after 12 sessions out; first tech exposure since the GOOGL stop."},
{d:"08/07", b:"sys",  x:"Weekly review writes <b>Rule 12 into the strategy itself</b>: below-band for 3 sessions ⇒ next market-open MUST add. Verbatim: <i>'patience was masking non-compliance.'</i>"},
{d:"07/28", b:"hold", x:"FOMC Jul 28–31: <b>no new risk into the decision</b>. Redeploy deferred again."},
{d:"07/24", b:"sys",  x:"Weekly review: <b>all-ETF book has no independent engine</b> — sourcing a single-name is 'the book's missing half'."},
{d:"07/23", b:"cut",  x:"GOOGL gaps through stop post-Q2 (capex fear): <b>−3.99%</b>. Pre-market call: no re-entry into the fear. Held."},
{d:"06/30", b:"trade",x:"XLP added — <b>deployment inside the 75–85% band for the first time</b> (79.4%)."},
{d:"06/29", b:"trade",x:"Rotation: XLF out (worst sector YTD), XLI + XLB in."},
{d:"06/25", b:"trade",x:"Idle streak broken after 6 cash sessions: GOOGL + XLF."},
{d:"06/22", b:"sys",  x:"/conviction from 100% cash: 24 sources. DELL ✓ GNRC ✓ — <b>MU refused</b> (+200% YTD, binary print, target 26% below spot)."},
{d:"06/15", b:"cut",  x:"<b>XOM thesis-break cut at −5.6%</b> — US-Iran deal killed the oil premium. Didn't wait for −7%."},
{d:"06/09", b:"cut",  x:"MSFT & NVDA trailing stops fire. Full reset to cash."},
{d:"04/30", b:"hold", x:"XOM idea 6/10 — <b>below the 8/10 bar. DO NOT BUY.</b>"}
];

const RULES = __RULES_JSON__;

const RISK = [
{t:"Evidence", v:"Fills reconciled to equity to the cent at 2026-09-18 (research 0006); blotter rebuilt from broker fills each EOD", c:"up"},
{t:"Execution", v:"Every mutation under the coordinator lease with intent recovery (ADR 0010) since 2026-10-13", c:"up"},
{t:"Benchmark", v:"Some weeks estimated; see comparison labels", c:"warn"}
];
'''


# --------------------------------------------------------------------------
# Emit data.js
# --------------------------------------------------------------------------

def js_num(v, nd):
    if nd == 2 and v == int(v) and abs(v) < 1 and v == 0:
        return "0"
    return fmt(v, nd)


def emit(snaps, weeks, events, blotter=None):
    book = build_book(snaps[-1])
    runs = summarize_runs(events, snaps[-1]["d"])
    trades = build_trades(blotter if blotter is not None else read_blotter(), book, snaps[-1]["d"])

    # a note keyed to a date that carries no EOD snapshot is a silent typo —
    # it would never render, so refuse to publish rather than drop it quietly
    orphans = sorted(set(EQ_NOTES) - {s["d"] for s in snaps})
    if orphans:
        fail(f"EQ_NOTES entries match no EOD snapshot date: {orphans}")

    eq_rows = []
    for s in snaps:
        dp = "0" if s["dp"] == 0 else fmt(s["dp"], 2)
        note = EQ_NOTES.get(s["d"], "")
        eq_rows.append(
            f'{{d:{js_str(s["d"])},n:{s["n"]},v:{fmt(s["v"], 2)},'
            f'cash:{fmt(s["cash"], 1)},dp:{dp},note:{js_str(note)}}}')

    week_rows = [
        f'{{w:{js_str(w["w"])}, bot:{fmt(w["bot"], 2)}, spx:{fmt(w["spx"], 2)}, '
        f'spxc:{fmt(w["spxc"], 2)}, est:{1 if w["est"] else 0}}}'
        for w in weeks]

    book_label = date.fromisoformat(snaps[-1]["d"]).strftime("%b %d").replace(" 0", " ")
    book_rows = [
        f'{{s:{js_str(b["s"])}, q:{b["q"]}, in:{fmt(b["in"], 2)}, pl:{fmt(b["pl"], 2)}, '
        f'plp:{fmt(b["plp"], 2)}, stop:{b["stop"]}, protection:{js_str(b["protection"])}, w:{fmt(b["w"], 1)}}}'
        for b in book]

    # Current rule observations are generated from the latest log, never
    # extrapolated from an old editorial audit. No claim of broker verification.
    trailing = sum(b["protection"] == "trailing" for b in book)
    fixed = sum(b["protection"] == "fixed" for b in book)
    deployed = 100 - snaps[-1]["cash"]
    rules = [
        {"ok": "?", "c": "warn", "t": "Logged protection", "v": f"{trailing} trailing / {fixed} fixed; broker status unverified"},
        {"ok": "?", "c": "warn", "t": "Historical rule compliance", "v": "not independently verified"},
        {"ok": "✓" if 75 <= deployed <= 85 else "!", "c": "up" if 75 <= deployed <= 85 else "warn",
         "t": "Logged deployment", "v": f"{deployed:.1f}% as of {snaps[-1]['d']}"},
    ]
    static_tail = STATIC_TAIL.replace("__RULES_JSON__", json.dumps(rules, ensure_ascii=False))
    static_tail = static_tail.replace("__ANALYSIS_ASOF__", ANALYSIS_ASOF)

    return (
        f"// ============ DATA — origin/main, latest log {snaps[-1]['d']} ============\n"
        "\n"
        "// Two independent dates. LOG_ASOF moves nightly with the trade log;\n"
        "// ANALYSIS_ASOF only moves when a human rewrites the editorial prose.\n"
        "// The dashboard shows both, so curated text can never pass as live.\n"
        f"const LOG_ASOF = {js_str(snaps[-1]['d'])};\n"
        f"const ANALYSIS_ASOF = {js_str(ANALYSIS_ASOF)};\n"
        "\n"
        "// {d, n: phase day, v: portfolio $, cash: cash %, dp: day P&L %}\n"
        "const EQ = [\n" + ",\n".join(eq_rows) + "\n];\n"
        "\n"
        "// weekly reviews. spx = as logged that week (contemporaneous record);\n"
        "// spxc = re-chained from the logged closes so the series is continuous;\n"
        "// est:1 = no index levels in the log, spxc falls back to spx.\n"
        "const WEEKS = [\n" + ",\n".join(week_rows) + "\n];\n"
        "\n"
        f"const BOOK = [ // {book_label} EOD\n" + ",\n".join(book_rows) + "\n];\n"
        "\n"
        "// Run records (ADR 0012), from state/events.jsonl: machine-written by every\n"
        "// routine and protection-monitor run, reconciled, never curated. Runs started\n"
        "// before LOG_ASOF only. Runs before `since` (or all runs, while it is null)\n"
        "// are unprovenanced: no record of code, rulebook, prompt or model exists and\n"
        "// none is backfilled.\n"
        f"const RUNS = {json.dumps(runs, ensure_ascii=False, sort_keys=True)};\n"
        "\n"
        "// Trade blotter from memory/BLOTTER.json (scripts/blotter.py --json: broker\n"
        "// fills, FIFO). Open lots first, newest entry first; then closed round trips,\n"
        f"// newest exit first. Test symbols excluded: {sorted(TEST_SYMBOLS)}.\n"
        "const TRADES = [\n" + ",\n".join(json.dumps(t, ensure_ascii=False) for t in trades) + "\n];\n"
        "\n"
        "// ============ Curated: hand-written, dated by ANALYSIS_ASOF ============\n"
        "\n" + static_tail
    )


def main():
    snaps = parse_trade_log(TRADE_LOG.read_text(encoding="utf-8"))
    weeks = parse_weekly_review(WEEKLY_REVIEW.read_text(encoding="utf-8"))
    out = emit(snaps, weeks, read_state(), read_blotter())
    check = "--check" in sys.argv
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if check:
        if current != out:
            print("MISMATCH: regenerated data.js differs from committed docs/dashboard/data.js",
                  file=sys.stderr)
            sys.exit(1)
        print("OK: data.js reproduces committed values")
        return
    OUT.write_text(out, encoding="utf-8")
    trade_rows = out.count('\n{"d"')
    print(f"wrote {OUT} — EQ {len(snaps)} · WEEKS {len(weeks)} · "
          f"BOOK {len(build_book(snaps[-1]))} (latest EOD {snaps[-1]['d']}) · "
          f"TRADES {trade_rows} from BLOTTER.json")


if __name__ == "__main__":
    main()
