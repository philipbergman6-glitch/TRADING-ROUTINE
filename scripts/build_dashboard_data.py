#!/usr/bin/env python3
"""Regenerate docs/dashboard/data.js from memory/ logs. Deterministic, no LLM.

Parses:
  - memory/TRADE-LOG.md   -> EQ  (every "EOD Snapshot" / "Midday Cut" header +
                                  its **Portfolio:** line)
                          -> BOOK (positions table of the latest EOD snapshot)
  - memory/WEEKLY-REVIEW.md -> WEEKS (Stats table of each "## Week ending" section)

TRADES / FEED / RULES / INSIGHTS and per-date chart notes are curated, not
derivable from the logs — they are frozen below (analysis as of 2026-07-28).

HARD-FAILS on any parse mismatch. Never publishes partial or stale data.
"""

import re
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

SNAP_HDR = re.compile(r"^#{2,3}\s+(.+?)\s+—\s+(EOD Snapshot|Midday Cut)\b")
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
        # the **Portfolio:** line must follow within a few lines
        pm = None
        for j in range(i + 1, min(i + 4, len(lines))):
            pm = PORTFOLIO.match(lines[j])
            if pm:
                break
        if not pm:
            fail(f"snapshot '{lines[i].strip()}' has no **Portfolio:** line")
        dp = parse_pct(pm.group(4) + "%") if pm.group(4) else 0.0
        snap = {"d": d, "kind": kind, "v": parse_money(pm.group(1)),
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
        fail("no EOD Snapshot / Midday Cut headers found in TRADE-LOG.md")
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
        })
    return book


# --------------------------------------------------------------------------
# WEEKLY-REVIEW.md -> WEEKS
# --------------------------------------------------------------------------

WEEK_HDR = re.compile(r"^## Week ending (\d{4})-(\d{2})-(\d{2})\s*$", re.MULTILINE)


def stats_row(block, metric):
    m = re.search(r"^\|\s*" + re.escape(metric) + r"\s*\|\s*(.+?)\s*\|\s*$",
                  block, re.MULTILINE)
    if not m:
        fail(f"weekly review block missing stats row {metric!r}")
    return m.group(1)


def parse_weekly_review(text):
    weeks = []
    matches = list(WEEK_HDR.finditer(text))
    if not matches:
        fail("no '## Week ending YYYY-MM-DD' sections in WEEKLY-REVIEW.md")
    for n, m in enumerate(matches):
        block = text[m.end(): matches[n + 1].start() if n + 1 < len(matches) else len(text)]
        ret = stats_row(block, "Week return")
        rm = re.search(r"\(([+\-−][\d.]+)%\)", ret)
        if not rm:
            fail(f"no (%) in 'Week return' row: {ret!r}")
        spx_raw = stats_row(block, "S&P 500 week")
        sm = re.match(r"([+\-−]?[\d.]+)%", spx_raw)
        if not sm:
            fail(f"'S&P 500 week' row does not start with a percent: {spx_raw!r}")
        weeks.append({"w": f"{m.group(2)}/{m.group(3)}",
                      "bot": parse_pct(rm.group(1) + "%"),
                      "spx": parse_pct(sm.group(1) + "%")})
    return weeks


# --------------------------------------------------------------------------
# Curated content — frozen, analysis as of 2026-07-28
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
    "2026-06-15": "XOM thesis-break cut at −5.6% — before the −7% trigger",
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
{d:"Jun 29", s:"XLI",  sec:"etf",  q:116, in:"182.16", out:"OPEN", open:1, pl:{v:"+121 unrl", up:1}, th:"Industrials leader"},
{d:"Jun 29", s:"XLB",  sec:"etf",  q:412, in:"51.07",  out:"OPEN", open:1, pl:{v:"+132 unrl", up:1}, th:"Materials #2"},
{d:"Jun 30", s:"XLP",  sec:"etf",  q:250, in:"83.76",  out:"OPEN", open:1, pl:{v:"+400 unrl", up:1}, th:"Defensive diversifier"}
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
{d:"07/28", b:"hold", x:"Pre-market ran 11:34 today. FOMC Jul 28–31: no new risk into the decision."}
];

const RULES = [
{ok:"✓", c:"up",   t:"10% trailing GTC on every position", v:"'spotless 4 straight weeks' · none lowered"},
{ok:"✓", c:"up",   t:"Max 3 trades/wk · 20% cap · ≤6 positions", v:"never breached in 64 days"},
{ok:"✓", c:"up",   t:"Cut on thesis break, don't wait for −7%", v:"XOM Jun 15 at −5.6%"},
{ok:"✓", c:"up",   t:"Exit sector after 2 failed trades", v:"tech flagged Jun 09, re-entry gated"},
{ok:"△", c:"warn", t:"75–85% deployed", v:"reached Jun 30 · lost Jul 23 · now 60.2%"},
{ok:"✗", c:"dn",   t:"Trim a stalled +10–15% single-name", v:"GOOGL flagged, not trimmed → round-trip"}
];

// ---- STATIC SECTION — analysis as of 2026-07-28; not regenerated by build_dashboard_data.py ----
const INSIGHTS = [
{c:"var(--red)", n:"01", h:"All the profit is 10 weeks old.", p:"Phase P&L is +5.88%, but equity on Jun 12 (first weekly review) was $106,860 — <b>higher than today's $105,879</b>. Since reviews began: 7 weeks, 1 up week, net ≈ −0.9% while the S&P summed ≈ +1.0%. The April–May tech book made all the money; the June–July ETF regime has been paying for discipline lessons. Question for Aug 02: which regime is the real strategy?"},
{c:"var(--amber)", n:"02", h:"Logged exits: 1 winner, 5 losers, −$5,531 — yet the account is up.", p:"Every written-down exit sums to −$5,531 (XOM +95, MSFT −1,690, NVDA −1,857, XOM −1,193, GOOGL −833, XLF −53). The +$5.9k of phase profit lives in the <b>never-logged Apr–May exits</b> (AMD, PLTR, MU, AVGO) plus today's open positions. Weekly-review 'profit factor 0.00' is a data artifact, not reality — but it means your own retrospectives are computing stats on the losing half of your history."},
{c:"var(--cyan)", n:"03", h:"The GOOGL round-trip was flagged a week before it happened.", p:"Jul 17 review: 'wide trail on a spiking single-name; watch for a discretionary partial trim.' Not taken. Jul 23: the +10.55% run gapped through the stop to <b>−3.99% realized</b>. The Jul 24 review names it plainly: 'flagged, not taken.' The agent's self-diagnosis loop works — <b>the gap is that flags don't become orders</b>."},
{c:"var(--green)", n:"04", h:"Risk control is genuinely solved.", p:"64 trading days, zero rule breaches, no stop ever lowered, worst single loss −9.4%, and it's improving: June's exits waited for stops at −8/−9%; by Jun 15 it cut XOM on thesis break at −5.6%, and GOOGL's damage was capped at −4% by the ratcheted trail. <b>Loss size shrank every month.</b> This is the strongest evidence for going live."},
{c:"var(--violet)", n:"05", h:"The book is 3 correlated sector ETFs and $42k idle cash.", p:"Since the GOOGL stop-out: XLI + XLB + XLP (one macro bet, as the Jul 24 review admits), deployment 60% vs the 75–85% mandate, and redeployment deferred at every scan since Jul 23 — 'market-open, patiently' three sessions running. FOMC ends Jul 31; <b>Aug 02 arrives with the redeploy decision still open</b>."},
{c:"var(--cyan)", n:"06", h:"Your local clone lied to you (and to me).", p:"This Mac's copy of TRADING-ROUTINE was <b>97 commits behind</b> — it showed the system dead since Jun 22 when it had run every scheduled day since. The cloud crons push straight to origin/main. Any dashboard, analysis, or meeting demo must read the remote, and a <code>git pull</code> belongs in your routine before touching this repo locally."}
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

    eq_rows = []
    for s in snaps:
        dp = "0" if s["dp"] == 0 else fmt(s["dp"], 2)
        note = EQ_NOTES.get(s["d"], "")
        eq_rows.append(
            f'{{d:{js_str(s["d"])},v:{fmt(s["v"], 2)},cash:{fmt(s["cash"], 1)},'
            f'dp:{dp},note:{js_str(note)}}}')

    week_rows = [
        f'{{w:{js_str(w["w"])}, bot:{fmt(w["bot"], 2)}, spx:{fmt(w["spx"], 2)}}}'
        for w in weeks]

    book_label = date.fromisoformat(snaps[-1]["d"]).strftime("%b %d").replace(" 0", " ")
    book_rows = [
        f'{{s:{js_str(b["s"])}, q:{b["q"]}, in:{fmt(b["in"], 2)}, pl:{fmt(b["pl"], 2)}, '
        f'plp:{fmt(b["plp"], 2)}, stop:{b["stop"]}, w:{fmt(b["w"], 1)}}}'
        for b in book]

    return (
        "// ================= DATA — origin/main, read 2026-07-28 =================\n"
        "\n"
        "// {d, v: portfolio $, cash: cash %, dp: day P&L %}\n"
        "const EQ = [\n" + ",\n".join(eq_rows) + "\n];\n"
        "\n"
        "// weekly reviews, verbatim\n"
        "const WEEKS = [\n" + ",\n".join(week_rows) + "\n];\n"
        "\n"
        f"const BOOK = [ // {book_label} EOD\n" + ",\n".join(book_rows) + "\n];\n"
        "\n" + STATIC_TAIL
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
