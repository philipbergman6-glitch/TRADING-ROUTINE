#!/usr/bin/env python3
"""Regenerate docs/dashboard/data.js from memory/ logs. Deterministic, no LLM.

Parses:
  - memory/TRADE-LOG.md   -> EQ  (every "EOD Snapshot" header + its
                                  **Portfolio:** line — daily closes ONLY;
                                  midday entries are prose-only audit trail)
                          -> BOOK (positions table of the latest EOD snapshot)
  - memory/WEEKLY-REVIEW.md -> WEEKS (Stats table of each "## Week ending" section)

TRADES / FEED / RULES / INSIGHTS and per-date chart notes are curated, not
derivable from the logs — they are curated below and dated by ANALYSIS_ASOF,
which the dashboard displays alongside the (separate) latest-log date.

HARD-FAILS on any parse mismatch. Never publishes partial or stale data.
"""

import re
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRADE_LOG = REPO / "memory" / "TRADE-LOG.md"
WEEKLY_REVIEW = REPO / "memory" / "WEEKLY-REVIEW.md"
OUT = REPO / "docs" / "dashboard" / "data.js"

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
        sm = re.match(r"\$?([\d.]+)", stop.strip())
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
# Curated content — dated by ANALYSIS_ASOF below, NOT by the latest log.
#
# These two dates drift apart on purpose: the logs regenerate nightly, the
# editorial does not. The dashboard surfaces both so a stale narrative can
# never sit behind a "LIVE" badge. When you revise the prose below, bump
# ANALYSIS_ASOF in the same commit.
ANALYSIS_ASOF = "2026-09-17"

#
# TRADES / FEED / RULES / RISK / INSIGHTS and the per-date chart notes are
# editorial: they cannot be derived from the logs, so they are written by hand
# and dated. Figures that DO move with the logs (deployment %, phase day) are
# placeholders substituted at build time — never bake a live number in here.
# Open positions carry pl:null on purpose; their P&L lives in BOOK, which is
# regenerated nightly, so the blotter cannot drift.
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
}

STATIC_TAIL = '''\
const TRADES = [
{d:"Apr 28", s:"AMD",  sec:"tech", q:62,  in:"314.97", out:null, gap:"never logged · last seen +11.96%", pl:null, th:"AI/CPU momentum"},
{d:"Apr 28", s:"NVDA", sec:"tech", q:90,  in:"208.64", out:null, gap:"never logged", pl:null, th:"AI GPU"},
{d:"Apr 28", s:"PLTR", sec:"tech", q:142, in:"142.30", out:null, gap:"never logged · last seen −3.02%", pl:null, th:"AI/defense sw"},
{d:"May 07", s:"XOM",  sec:"enrg", q:140, in:"—",      out:"146.62", pl:{v:"+95", up:1}, th:"Energy leadership"},
{d:"May 26", s:"MU",   sec:"tech", q:25,  in:"853.58", out:null, gap:"never logged · last seen +8.58%", pl:null, th:"HBM cycle"},
{d:"May 27", s:"AVGO", sec:"tech", q:40,  in:"427.95", out:null, gap:"never logged", pl:null, th:"AI networking"},
{d:"Jun 03", s:"MSFT", sec:"tech", q:48,  in:"436.20", out:"~401 · stop", pl:{v:"−1,690", up:0}, th:"Mega-cap AI capex"},
{d:"Jun 03", s:"NVDA", sec:"tech", q:90,  in:"219.64", out:"~199 · stop", pl:{v:"−1,857", up:0}, th:"Re-entry"},
{d:"Jun 10", s:"XOM",  sec:"enrg", q:142, in:"150.14", out:"141.74 · thesis cut", pl:{v:"−1,193", up:0}, th:"Cut at −5.6%, before −7% rule"},
{d:"Jun 25", s:"GOOGL",sec:"tech", q:62,  in:"336.36", out:"322.93 · stop Jul 23", pl:{v:"−833", up:0}, th:"+10.55% high given back"},
{d:"Jun 25", s:"XLF",  sec:"etf",  q:390, in:"53.97",  out:"53.83 · rotation", pl:{v:"−53", up:0}, th:"Financials thesis broke"},
{d:"Jun 29", s:"XLI",  sec:"etf",  q:116, in:"182.16", out:"168.58 · Sep 14 stop", pl:{v:"−1,575.36", up:0}, th:"Industrials leader; exit recorded Sep 14"},
{d:"Jun 29", s:"XLB",  sec:"etf",  q:412, in:"51.07",  out:"OPEN", open:1, pl:null, th:"Materials #2"},
{d:"Jun 30", s:"XLP",  sec:"etf",  q:250, in:"83.76",  out:"OPEN", open:1, pl:null, th:"Defensive diversifier"},
{d:"Aug 10", s:"XLK",  sec:"etf",  q:112, in:"187.85", out:"OPEN", open:1, pl:null, th:"Rule 12 deployment backstop — first tech since GOOGL"}
];

const FEED = [
{d:"04/30", b:"hold", x:"XOM idea 6/10 — <b>below the 8/10 bar. DO NOT BUY.</b>"},
{d:"06/09", b:"cut",  x:"MSFT & NVDA trailing stops fire. Full reset to cash."},
{d:"06/15", b:"cut",  x:"<b>XOM thesis-break cut at −5.6%</b> — US-Iran deal killed the oil premium. Didn't wait for −7%."},
{d:"06/22", b:"sys",  x:"/conviction from 100% cash: 24 sources. DELL ✓ GNRC ✓ — <b>MU refused</b> (+200% YTD, binary print, target 26% below spot)."},
{d:"06/25", b:"trade",x:"Idle streak broken after 6 cash sessions: GOOGL + XLF."},
{d:"06/29", b:"trade",x:"Rotation: XLF out (worst sector YTD), XLI + XLB in."},
{d:"06/30", b:"trade",x:"XLP added — <b>deployment inside the 75–85% band for the first time</b> (79.4%)."},
{d:"07/23", b:"cut",  x:"GOOGL gaps through stop post-Q2 (capex fear): <b>−3.99%</b>. Pre-market call: no re-entry into the fear. Held."},
{d:"07/24", b:"sys",  x:"Weekly review: <b>all-ETF book has no independent engine</b> — sourcing a single-name is 'the book's missing half'."},
{d:"07/28", b:"hold", x:"FOMC Jul 28–31: <b>no new risk into the decision</b>. Redeploy deferred again."},
{d:"08/07", b:"sys",  x:"Weekly review writes <b>Rule 12 into the strategy itself</b>: below-band for 3 sessions ⇒ next market-open MUST add. Verbatim: <i>'patience was masking non-compliance.'</i>"},
{d:"08/10", b:"trade",x:"<b>Rule 12 fires on its own deadline</b> — XLK 112 @ $187.85. Deployment 60.4% → 80.2%, back in band after 12 sessions out; first tech exposure since the GOOGL stop."},
{d:"08/11", b:"sys",  x:"Benchmark audit: the logged S&amp;P series <b>broke chain 3×</b> (weeks 07/24, 07/31, 08/07). Chart now plots the re-chained series — <b>which is worse for the bot</b>. Build hard-fails on any new break."}
];

const RULES = __RULES_JSON__;

const RISK = [
{t:"Evidence", v:"Markdown snapshots; broker reconciliation outstanding", c:"warn"},
{t:"Execution", v:"Recovery across interrupted routines remains unproven", c:"warn"},
{t:"Benchmark", v:"Some weeks estimated; see comparison labels", c:"warn"}
];

// Commentary as of __ANALYSIS_ASOF__; not a live safety certification.
const INSIGHTS = [
{c:"var(--amber)", n:"01", h:"Prove the system before real money.", p:"The current objective is a recoverable paper execution path and independently reconciled performance. A green unit-test suite alone does not establish continuous protection or a profitable strategy."},
{c:"var(--cyan)", n:"02", h:"Keep the evidence visible.", p:"The equity curve and current book are generated from dated logs. The historical blotter below is incomplete; use it as an archive, not a complete realized-return or win-rate calculation. Benchmark weeks marked estimated remain provisional."},
{c:"var(--violet)", n:"03", h:"Test whether the decisions add value.", p:"Freeze an experiment specification and compare prospective agent decisions with passive and simple mechanical baselines, on matching dates and after modeled costs. Record predictions before trades and version every strategy change."}
];
'''


# --------------------------------------------------------------------------
# Emit data.js
# --------------------------------------------------------------------------

def js_num(v, nd):
    if nd == 2 and v == int(v) and abs(v) < 1 and v == 0:
        return "0"
    return fmt(v, nd)


def emit(snaps, weeks):
    book = build_book(snaps[-1])

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
        "\n" + static_tail
    )


def main():
    snaps = parse_trade_log(TRADE_LOG.read_text(encoding="utf-8"))
    weeks = parse_weekly_review(WEEKLY_REVIEW.read_text(encoding="utf-8"))
    out = emit(snaps, weeks)
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
    print(f"wrote {OUT} — EQ {len(snaps)} · WEEKS {len(weeks)} · "
          f"BOOK {len(build_book(snaps[-1]))} (latest EOD {snaps[-1]['d']})")


if __name__ == "__main__":
    main()
