#!/usr/bin/env python3
"""Build the Fund Brain index: docs/brain/index.json and docs/brain/INDEX.md.

    python3 scripts/build_brain_index.py                 # regenerate both files
    python3 scripts/build_brain_index.py --check         # regenerate in memory, compare
    python3 scripts/build_brain_index.py --parse         # parse every input, write nothing (routine log gate)
    python3 scripts/build_brain_index.py --symbol PLTR   # everything about one symbol
    python3 scripts/build_brain_index.py --refusals 2026-10   # every refusal in a month

First slice of the brain (map #169, ticket #174): the committed record joined
per symbol and per UTC date. No trade id yet (that is ADR 0014, ticket #172);
the join key is (symbol, date).

Sources and what is taken from each:
  memory/RESEARCH-LOG.md   dated entry headers; symbols named in the entry,
                           under "### Trade Ideas" and under "### Decision"
  memory/TRADE-LOG.md      dated entry headers (both "## <date> — Kind" and
                           "### <Mon D> — Kind (Day N, …)" styles); symbols
  memory/BLOTTER.json      round trips and open lots (symbol F excluded by name)
  memory/WEEKLY-REVIEW.md  the "## Week ending" section covering each date
  state/events.jsonl       run records (refusals, actions, incidents, intents)
                           and intent lines, started before the latest EOD
                           snapshot date — the same cutoff the dashboard uses,
                           so the committed index is reproducible between
                           EOD pushes even though the monitor appends run
                           records every 30 minutes without a rebuild.

Deterministic, no LLM, no network. HARD-FAILS on any header kind the parser
does not know, a traded symbol without a sector, a week without a grade, a
malformed run record or a corrupt state file. Never writes a partial index.

Parsers shared with the dashboard are imported from build_dashboard_data.py,
never copied.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts.build_dashboard_data import (  # noqa: E402
    BLOTTER, DAY0_DATE, SECTORS, TEST_SYMBOLS, TRADE_LOG, WEEKLY_REVIEW,
    WEEK_HDR, ParseError, fail, parse_header_date, parse_trade_log,
    read_blotter, read_state,
)
from scripts.run_record import MalformedRunRecord, fold  # noqa: E402

RESEARCH_LOG = REPO / "memory" / "RESEARCH-LOG.md"
OUT_JSON = REPO / "docs" / "brain" / "index.json"
OUT_MD = REPO / "docs" / "brain" / "INDEX.md"

DECISION_TEXT_CAP = 400

# --------------------------------------------------------------------------
# Dated entry headers
# --------------------------------------------------------------------------

# "## 2026-10-15 — Pre-market Research", "### Sep 9 — EOD Snapshot (Day 96, …)",
# "## Day 0 — EOD Snapshot". The text after the dash is the title; its first
# " — "-separated part is the kind, the rest is a free note.
ENTRY_HDR = re.compile(
    r"^(#{2,3})\s+(Day 0|[A-Z][a-z]{2}\s+\d{1,2}|\d{4}-\d{2}-\d{2})"
    r"(?:\s+through\s+(\d{4}-\d{2}-\d{2}))?"
    r"(?:\s*\([^)]*\))?\s+—\s+(.+?)\s*$")
TOP_LEVEL = re.compile(r"^##\s")

# Every header kind the record has used, mapped to a stable slug. A new kind
# is a parser change, reviewed here, never a silent miss.
TRADE_KINDS = [
    (r"eod snapshot", "eod-snapshot"),
    (r"non-trading day snapshot", "non-trading-day-snapshot"),
    (r"midday scan( snapshot)?", "midday-scan"),
    (r"midday snapshot", "midday-snapshot"),
    (r"midday cut", "midday-cut"),
    (r"midday exits", "midday-exits"),
    (r"midday reconciliation", "midday-reconciliation"),
    (r"market-open review", "market-open-review"),
    (r"market-open( trades?)?( & [A-Z]+ exit)?", "market-open-trades"),
    (r"market-open stop adjustments", "market-open-stop-adjustments"),
    (r"[A-Z]+ stop-out", "stop-out"),
    (r"stop exits|stop executions at open", "stop-exits"),
    (r"stop renewal", "stop-renewal"),
]
RESEARCH_KINDS = [
    (r"pre-?market( research)?( \+ market-open)?", "pre-market-research"),
    (r"market-open research", "market-open-research"),
    (r"midday scan", "midday-scan"),
    (r"(midday|afternoon) addendum", "addendum"),
    (r"weekend (prep / market-open review|research)", "weekend-research"),
    (r"weekly context", "weekly-context"),
    (r"memorial day", "holiday-note"),
    (r"conviction", "conviction"),
]
KINDS = {"trade": ("trade-log", TRADE_KINDS), "research": ("research-log", RESEARCH_KINDS)}
FILES = {"trade": TRADE_LOG, "research": RESEARCH_LOG}


def parse_entry_header(line, log):
    """-> (iso date, kind slug, title, note) for a dated entry header, None for
    any other header line. Unknown kinds hard-fail."""
    m = ENTRY_HDR.match(line.rstrip())
    if not m:
        return None
    d = parse_header_date(m.group(2))
    title = m.group(4)
    # Parentheticals anywhere in the title are notes, never part of the kind:
    # "Pre-market Research (Wednesday, Day 66) — FOMC DECISION DAY".
    parens = [p.strip() for p in re.findall(r"\(([^)]*)\)", title)]
    base = re.sub(r"\s*\([^)]*\)", "", title)
    kind_text, _, rest = base.partition(" — ")
    kind_text = kind_text.strip()
    note = "; ".join(x for x in [rest.strip(), *parens] if x)
    if m.group(3):
        note = f"through {m.group(3)}" + ("; " + note if note else "")
    label, table = KINDS[log]
    for pattern, slug in table:
        if re.fullmatch(pattern, kind_text, re.IGNORECASE):
            return d, slug, title, note.strip()
    fail(f"unknown {label} entry kind {kind_text!r} in header {line.strip()!r}")


def mentions(text, symbols):
    """Known symbols named in `text`, sorted, engineering test fills excluded."""
    found = set(re.findall(r"(?<![A-Za-z$])\$?([A-Z]{1,5})(?![A-Za-z])", text))
    return sorted((found & symbols) - TEST_SYMBOLS)


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_log(text, log, symbols):
    """Dated entries of one log, in file order, each with its line number,
    symbols named, and (research) the Trade Ideas / Decision symbols."""
    lines = text.split("\n")
    entries = []
    current = None
    section = None
    seq = {}
    for n, line in enumerate(lines, start=1):
        if line.startswith("#"):
            hdr = parse_entry_header(line, log)
            if hdr:
                d, kind, title, note = hdr
                seq[(d, kind)] = seq.get((d, kind), 0) + 1
                current = {
                    "id": f"{log}/{d}/{kind}/{seq[(d, kind)]}", "log": log,
                    "file": FILES[log].relative_to(REPO).as_posix(), "line": n,
                    "date": d, "kind": kind, "title": title, "note": note,
                    "_body": [], "_sections": {},
                }
                entries.append(current)
                section = None
                continue
            if TOP_LEVEL.match(line) or line.startswith("# "):
                if line.startswith("# ") and current is None:
                    continue  # the file title
                fail(f"{FILES[log].name} line {n}: top-level header is not a dated entry: {line.strip()!r}")
            if current is None:
                fail(f"{FILES[log].name} line {n}: subsection {line.strip()!r} before the first dated entry")
            section = line.lstrip("#").strip()
            current["_sections"].setdefault(section, [])
            continue
        if current is not None:
            current["_body"].append(line)
            if section is not None:
                current["_sections"][section].append(line)
    for e in entries:
        body = "\n".join(e.pop("_body"))
        sections = e.pop("_sections")
        e["symbols"] = mentions(body, symbols)
        if log == "research":
            ideas = "\n".join("\n".join(v) for k, v in sections.items() if k.startswith("Trade Ideas"))
            decision = "\n".join("\n".join(v) for k, v in sections.items() if k.startswith("Decision"))
            e["ideas"] = mentions(ideas, symbols)
            e["decision"] = mentions(decision, symbols)
            e["decision_text"] = squash(decision)[:DECISION_TEXT_CAP]
    return entries


# --------------------------------------------------------------------------
# Weekly review
# --------------------------------------------------------------------------

GRADE = re.compile(r"^###\s+Overall Grade:\s*(\S+)\s*$", re.MULTILINE)
WEEK_SECTION = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
ALLOWED_TOP = ("## Week ending YYYY-MM-DD", "## Benchmark Data Errata")


def parse_weeks(text, symbols):
    for line in text.split("\n"):
        if TOP_LEVEL.match(line) and not WEEK_HDR.match(line) and not line.startswith(ALLOWED_TOP):
            fail(f"WEEKLY-REVIEW.md top-level header is not a week: {line.strip()!r}")
    heads = list(WEEK_HDR.finditer(text))
    weeks = {}
    for i, h in enumerate(heads):
        end = date(int(h.group(1)), int(h.group(2)), int(h.group(3))).isoformat()
        block = text[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        block = block.split("\n## ", 1)[0]  # stop at a non-week top-level header
        g = GRADE.search(block)
        if not g:
            fail(f"week ending {end} has no 'Overall Grade' line")
        if end in weeks:
            fail(f"duplicate week ending {end}")
        parts = WEEK_SECTION.split(block)
        sections = {parts[k]: parts[k + 1] for k in range(1, len(parts) - 1, 2)}
        weeks[end] = {
            "ending": end, "line": text[:h.start()].count("\n") + 1,
            "grade": g.group(1),
            "symbols": mentions(block, symbols),
            "closed_trades": mentions(sections.get("Closed Trades", ""), symbols),
            "open_positions": mentions(sections.get("Open Positions at Week End", ""), symbols),
        }
    if not weeks:
        fail("no '## Week ending' sections in WEEKLY-REVIEW.md")
    return dict(sorted(weeks.items()))


def week_for(d, weeks):
    """The week-ending date whose seven days contain `d`, or None."""
    day = date.fromisoformat(d)
    for end in weeks:
        e = date.fromisoformat(end)
        if e - timedelta(days=6) <= day <= e:
            return end
    return None


# --------------------------------------------------------------------------
# Blotter and state
# --------------------------------------------------------------------------

def read_sectors():
    data = json.loads(SECTORS.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def index_blotter(blotter, sectors):
    """-> {symbol: {sector, round_trips, open_lots}} for traded symbols."""
    out = {}
    for key in ("round_trips", "open_lots"):
        for lot in blotter[key]:
            s = lot["symbol"]
            if s in TEST_SYMBOLS:
                continue
            if s not in sectors:
                fail(f"{s} traded but missing from memory/SECTORS.json")
            rec = out.setdefault(s, {"sector": sectors[s], "round_trips": [], "open_lots": []})
            rec[key].append(lot)
    for rec in out.values():
        rec["round_trips"].sort(key=lambda r: (r["entered"], r["exited"]))
        rec["open_lots"].sort(key=lambda r: r["entered"])
    return out


def lead_symbol(text, symbols):
    """'XLP: HOLD …' -> XLP; else the first known symbol named; else None."""
    m = re.match(r"^([A-Z]{1,5}):", text)
    if m and m.group(1) in symbols and m.group(1) not in TEST_SYMBOLS:
        return m.group(1)
    named = mentions(text, symbols)
    return named[0] if named else None


def index_state(events, asof, symbols):
    """Run records and intent lines dated before `asof`, keyed by id."""
    try:
        fold(events)  # every record validated, not only the shown ones
        shown = fold([e for e in events if e.get("kind") == "run" and e["at"][:10] < asof])
    except MalformedRunRecord as exc:
        fail(str(exc))
    runs, refusals = {}, []
    for run in sorted(shown, key=lambda r: (r.started_at, r.run)):
        s = run.start
        touched = set()
        for field in ("actions", "refusals", "incidents"):
            for text in getattr(run, field):
                sym = lead_symbol(text, symbols)
                touched.update(mentions(text, symbols))
                if field == "refusals":
                    refusals.append({"at": run.ended_at or run.started_at, "run": run.run,
                                     "routine": run.routine, "symbol": sym,
                                     "source": "run", "text": text})
        runs[run.run] = {
            "run": run.run, "routine": run.routine, "trigger": run.trigger,
            "started_at": run.started_at, "ended_at": run.ended_at,
            "outcome": run.outcome or "unfinished",
            "code_sha": s["code_sha"], "code_dirty": s["code_dirty"],
            "rulebook_version": s["rulebook_version"], "rulebook_pinned": s["rulebook_pinned"],
            "model_id": s["model_id"], "model_source": s["model_source"],
            "actions": list(run.actions), "refusals": list(run.refusals),
            "incidents": list(run.incidents), "intents": list(run.intents),
            "symbols": sorted(touched),
        }
    intents = {}
    for e in events:
        if e.get("kind") != "intent" or e["at"][:10] >= asof:
            continue
        rec = intents.setdefault(e["intent"], {"intent": e["intent"], "symbol": None,
                                               "action": None, "first_at": e["at"],
                                               "last_state": None, "history": []})
        if e.get("symbol") and e["symbol"] not in TEST_SYMBOLS:
            rec["symbol"] = e["symbol"]
        if e.get("action"):
            rec["action"] = e["action"]
        rec["last_state"] = e["state"]
        rec["history"].append({k: v for k, v in e.items() if k not in ("kind", "schema", "intent")})
        if e["state"] == "refused":
            run = runs.get(e["writer"])
            refusals.append({"at": e["at"], "run": e["writer"],
                             "routine": run["routine"] if run else e["writer"].rsplit("-", 2)[0],
                             "symbol": rec["symbol"], "source": "intent",
                             "text": "; ".join(e.get("reasons") or [])})
    refusals.sort(key=lambda r: (r["at"], r["run"], r["text"]))
    return runs, dict(sorted(intents.items())), refusals


# --------------------------------------------------------------------------
# Join
# --------------------------------------------------------------------------

def build():
    sectors = read_sectors()
    blotter = read_blotter()
    symbols = (set(sectors) | {l["symbol"] for k in ("round_trips", "open_lots") for l in blotter[k]}) - TEST_SYMBOLS
    snaps = parse_trade_log(TRADE_LOG.read_text(encoding="utf-8"))
    asof = snaps[-1]["d"]
    research = parse_log(RESEARCH_LOG.read_text(encoding="utf-8"), "research", symbols)
    trade = parse_log(TRADE_LOG.read_text(encoding="utf-8"), "trade", symbols)
    weeks = parse_weeks(WEEKLY_REVIEW.read_text(encoding="utf-8"), symbols)
    lifecycles = index_blotter(blotter, sectors)
    runs, intents, refusals = index_state(read_state(), asof, symbols)

    entries = {}
    for e in research + trade:
        e["week"] = week_for(e["date"], weeks)
        entries[e["id"]] = e

    syms = {s: {"sector": sectors[s], "research": [], "trade_log": [], "ideas": [],
                "decisions": [], "last_decision": None,
                "round_trips": [], "open_lots": [], "runs": [], "intents": [], "weeks": []}
            for s in sorted(symbols)}
    for s, rec in lifecycles.items():
        syms[s]["round_trips"] = rec["round_trips"]
        syms[s]["open_lots"] = rec["open_lots"]
    for e in research + trade:
        key = "research" if e["log"] == "research" else "trade_log"
        for s in e["symbols"]:
            syms[s][key].append(e["id"])
        for s in e.get("ideas", []):
            syms[s]["ideas"].append(e["id"])
        for s in e.get("decision", []):
            syms[s]["decisions"].append(e["id"])
            syms[s]["last_decision"] = {"date": e["date"], "entry": e["id"], "text": e["decision_text"]}
    for rid, run in runs.items():
        for s in run["symbols"]:
            syms[s]["runs"].append(rid)
    for iid, it in intents.items():
        if it["symbol"]:
            syms[it["symbol"]]["intents"].append(iid)
    for end, w in weeks.items():
        for s in w["symbols"]:
            syms[s]["weeks"].append(end)

    dates = {}

    def day(d):
        return dates.setdefault(d, {"fills": [], "intents": [], "research": [],
                                    "runs": [], "trade_log": [], "week": week_for(d, weeks)})

    for e in research + trade:
        day(e["date"])["research" if e["log"] == "research" else "trade_log"].append(e["id"])
    for s, rec in lifecycles.items():
        for rt in rec["round_trips"]:
            day(rt["entered"][:10])["fills"].append({"symbol": s, "side": "entry", "qty": rt["qty"], "avg": rt["avg_in"]})
            day(rt["exited"][:10])["fills"].append({"symbol": s, "side": "exit", "qty": rt["qty"], "avg": rt["avg_out"], "pnl": rt["pnl"]})
        for lot in rec["open_lots"]:
            day(lot["entered"][:10])["fills"].append({"symbol": s, "side": "entry", "qty": lot["qty"], "avg": lot["avg_in"]})
    for rid, run in runs.items():
        day(run["started_at"][:10])["runs"].append(rid)
    for iid, it in intents.items():
        day(it["first_at"][:10])["intents"].append(iid)
    for d in dates.values():
        d["fills"].sort(key=lambda f: (f["symbol"], f["side"]))

    return {
        "generated_from": {
            "trade_log_asof": asof,
            "run_cutoff": "started before " + asof + " (UTC)",
            "sources": {
                "memory/RESEARCH-LOG.md": {"entries": len(research)},
                "memory/TRADE-LOG.md": {"entries": len(trade), "eod_snapshots": len(snaps)},
                "memory/WEEKLY-REVIEW.md": {"weeks": len(weeks)},
                "memory/BLOTTER.json": {"round_trips": sum(len(r["round_trips"]) for r in lifecycles.values()),
                                        "open_lots": sum(len(r["open_lots"]) for r in lifecycles.values()),
                                        "excluded_symbols": sorted(TEST_SYMBOLS)},
                "state/events.jsonl": {"runs": len(runs), "intents": len(intents)},
            },
        },
        "symbols": syms,
        "dates": dict(sorted(dates.items())),
        "entries": dict(sorted(entries.items())),
        "weeks": weeks,
        "runs": runs,
        "intents": intents,
        "refusals": refusals,
    }


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

def query_symbol(index, symbol):
    if symbol not in index["symbols"]:
        fail(f"{symbol} is not in the index (known: {', '.join(index['symbols'])})")
    rec = dict(index["symbols"][symbol])
    rec["research"] = [index["entries"][i] for i in rec["research"]]
    rec["trade_log"] = [index["entries"][i] for i in rec["trade_log"]]
    rec["runs"] = [index["runs"][r] for r in rec["runs"]]
    rec["intents"] = [index["intents"][i] for i in rec["intents"]]
    rec["weeks"] = [index["weeks"][w] for w in rec["weeks"]]
    return rec


def query_refusals(index, month):
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        fail(f"month must be YYYY-MM, got {month!r}")
    return [r for r in index["refusals"] if r["at"].startswith(month)]


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

def render_json(index):
    return json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def render_md(index):
    g = index["generated_from"]
    out = [
        "# Fund Brain index",
        "",
        f"Generated by `scripts/build_brain_index.py` from the committed record; "
        f"latest EOD snapshot {g['trade_log_asof']}. Machine form: `index.json`. "
        "Do not edit; regenerate.",
        "",
        "## Symbols",
        "",
        "| Symbol | Sector | Closed | Open | Research | Trade log | Runs | Intents | Last decision |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s, r in index["symbols"].items():
        ld = r["last_decision"]
        out.append(f"| {s} | {r['sector']} | {len(r['round_trips'])} | {len(r['open_lots'])} | "
                   f"{len(r['research'])} | {len(r['trade_log'])} | {len(r['runs'])} | {len(r['intents'])} | "
                   f"{ld['date'] if ld else '—'} |")
    out += ["", "## Open lots", "", "| Symbol | Entered | Qty | Avg in |", "|---|---|---|---|"]
    for s, r in index["symbols"].items():
        for lot in r["open_lots"]:
            out.append(f"| {s} | {lot['entered'][:10]} | {lot['qty']} | {lot['avg_in']} |")
    out += ["", "## Round trips", "", "| Symbol | Entered | Exited | Qty | Avg in | Avg out | P&L | P&L % |",
            "|---|---|---|---|---|---|---|---|"]
    trips = sorted((rt for r in index["symbols"].values() for rt in r["round_trips"]),
                   key=lambda rt: (rt["exited"], rt["entered"]), reverse=True)
    for rt in trips:
        out.append(f"| {rt['symbol']} | {rt['entered'][:10]} | {rt['exited'][:10]} | {rt['qty']} | "
                   f"{rt['avg_in']} | {rt['avg_out']} | {rt['pnl']} | {rt['pnl_pct']} |")
    out += ["", "## Refusals", "", "| At (UTC) | Routine | Symbol | Source | Reason |", "|---|---|---|---|---|"]
    for r in reversed(index["refusals"]):
        text = r["text"].replace("|", "\\|")
        out.append(f"| {r['at'][:16]} | {r['routine']} | {r['symbol'] or '—'} | {r['source']} | {text} |")
    out += ["", "## Sources", "", "| Source | Counts |", "|---|---|"]
    for src, counts in g["sources"].items():
        out.append(f"| `{src}` | " + ", ".join(f"{k} {v}" for k, v in counts.items()) + " |")
    out += ["", f"Run and intent records: {g['run_cutoff']}.", ""]
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    index = build()
    if "--parse" in argv:
        # Log-format gate for the routines that append to the logs (2026-10-16:
        # a "Midday" header, not "Midday Scan", failed dashboard-data and tests
        # three times in one day). build() has already parsed every input;
        # an unknown header kind raised ParseError before this line.
        g = index["generated_from"]["sources"]
        print(f"OK: parsed research {g['memory/RESEARCH-LOG.md']['entries']} · "
              f"trade-log {g['memory/TRADE-LOG.md']['entries']} · weeks {len(index['weeks'])} · "
              f"latest EOD {index['generated_from']['trade_log_asof']}; nothing written")
        return 0
    if "--symbol" in argv:
        print(json.dumps(query_symbol(index, argv[argv.index("--symbol") + 1]), indent=1, sort_keys=True))
        return 0
    if "--refusals" in argv:
        for r in query_refusals(index, argv[argv.index("--refusals") + 1]):
            print(f"{r['at']}  {r['routine']}  {r['symbol'] or '-'}  {r['text']}")
        return 0
    js, md = render_json(index), render_md(index)
    if "--check" in argv:
        cur_js = OUT_JSON.read_text(encoding="utf-8") if OUT_JSON.exists() else None
        cur_md = OUT_MD.read_text(encoding="utf-8") if OUT_MD.exists() else None
        if cur_js != js or cur_md != md:
            print("MISMATCH: regenerated brain index differs from committed docs/brain/index.json / INDEX.md",
                  file=sys.stderr)
            return 1
        print("OK: docs/brain/index.json and INDEX.md reproduce committed values")
        return 0
    OUT_JSON.write_text(js, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    g = index["generated_from"]["sources"]
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)} — "
          f"symbols {len(index['symbols'])} · dates {len(index['dates'])} · "
          f"research {g['memory/RESEARCH-LOG.md']['entries']} · trade-log {g['memory/TRADE-LOG.md']['entries']} · "
          f"runs {g['state/events.jsonl']['runs']} · refusals {len(index['refusals'])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
