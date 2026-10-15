# 0011. Log entry forms the brain must parse

Date: 2026-10-15. Status: findings. Serves the Fund Brain map
([#169](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/169)),
in particular the index builder ticket
[#174](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/174),
which must hard-fail on a header it does not recognise and therefore needs to
know every form the record already contains. Numbers 0007 to 0010 are taken on
unmerged `research/*` branches, hence 0011.

Method: every `##`/`###` header in `memory/RESEARCH-LOG.md` and
`memory/TRADE-LOG.md` on `main` at 248c467 was normalised (dates, weekday
names and numbers replaced by placeholders) and counted; each blotter
lifecycle (`memory/BLOTTER.json`: 18 round trips, 5 open lots) was joined to
the entries that name its symbol. The script lives only in this session's
scratchpad; the counts below are reproducible with a one-line grep where noted.

## 1. Counts, and where they reconcile

| File | `##` headers | `###` headers | Dated headers (either level) |
|---|---|---|---|
| RESEARCH-LOG.md | 174 | 1192 | 199 (174 at `##`, 25 at `###`) |
| TRADE-LOG.md | 67 | 189 | 244 of 256 (12 undated `###` sub-sections) |

`grep -c '^## ' memory/RESEARCH-LOG.md` → 174; `grep -c '^### '` → 1192. The
"1192 entries" figure in `docs/brain/README.md` is the `###` count, which is
mostly sub-sections (`### Decision` 175, `### Risk Factors` 126, `### Positions`
109, `### Market Context` 92, ...), not sessions. A **session entry is a
header, at either level, whose text starts with a date**; sub-sections are
the undated `###` headers under it.

## 2. Header level drifts, twice

- **TRADE-LOG:** EOD snapshots are `##` from 2026-04-30 to 2026-06-09 (13) and
  `###` from 2026-05-14 onward (104). `scripts/build_dashboard_data.py`
  already accepts both (`SNAP_HDR = ^#{2,3}`), parses 117 snapshots, and
  rejects any other kind under that header shape.
- **RESEARCH-LOG:** pre-market entries are `##` through 2026-10-01 and `###`
  from **2026-10-02** (line 7930) onward: `### 2026-10-02 — Pre-Market
  Research (Day 114, ...)`, then `### 2026-10-08 — Pre-Market (Day 118, ...)`.
  A parser that treats only `##` as an entry reports the last research session
  as 2026-10-07 and silently loses seven sessions, including the one that
  explains the PSX entry on 2026-10-02. The dated `###` set also holds the
  2026-07 midday addenda (`### Jul 15 — Midday Addendum`) and one odd header,
  `### May 21 Execution Note` (line 2301, no em dash).

Rule for the builder: a dated header at `##` or `###` is an entry; an undated
`###` is a sub-section of the preceding entry; a dated header with no ` — `
separator (`May 21 Execution Note`) must be listed explicitly or the build
fails.

## 3. Forms

### RESEARCH-LOG session headers (199)

Three date spellings: `2026-04-30 — ...` (most), `2026-08-04 (Tue) — ...`
(2026-08-03 to 2026-09-01), `2026-09-02 (Wed, Day 91) — ...` (September). The
kind after the dash is one of these families (count of dated headers):

| Family | Count | Examples (line) |
|---|---|---|
| Pre-market research | 136 | `Pre-market Research` (39, L13), `Pre-Market Research (Day N, Weekday)` (10, L4011), `(Tue) — Pre-Market Research (Day 70)` (15, L5596), `(Wed, Day 107) — PRE-MARKET` (7, L7473), `### ... — Pre-Market (Day 118, ...)` (6, L8167) |
| Midday scan / addendum | 51 | `Midday Scan` (26, L68), `Midday Addendum` (L592), `Afternoon Addendum (Midday Scan)` (L2503), `Midday Scan (FOMC Day 1, no-op)` (L3906) |
| Market-open research | 3 | `Market-Open Research` (L1722), `Market-Open Research (inline)` (L3761), `Pre-market Research + Market-Open` (L3157) |
| Weekend / holiday | 6 | `Weekend Prep / Market-Open Review (Market Closed — Sunday)` (L241), `Memorial Day (Market Closed)` (L2466), `Weekend Research — MARKETS CLOSED; ...` (L7223) |
| Conviction | 1 | `(Tue, Day 106) — CONVICTION (ad-hoc, advice-only) — ...` (L7422) |
| Backfill | 1 | `2026-05-05 through 2026-05-09 — Weekly Context (Backfill)` (L620) |
| No separator | 1 | `### May 21 Execution Note` (L2301) |

57 distinct normalised forms at `##` alone; 38 of them occur once because the
header carries the day's headline (`— FOMC DECISION DAY`, `— CPI DAY`, `—
OIL UNWIND DAY 2 HITS XLE; ...`). Matching on the family keyword anywhere in
the header (Pre-Market, Midday or Afternoon, Market-Open, Market(s) Closed or
Weekend, Conviction, Backfill) covers 198 of 199; `May 21 Execution Note`
is the one exception;
the trailing headline is free text and must not be part of the match.

### TRADE-LOG headers (256)

| Family | Count | Parsed today | Examples (line) |
|---|---|---|---|
| EOD Snapshot | 117 | yes, dashboard | `Apr 30 — EOD Snapshot (Day 3, Thursday)` (L46), `Day 0 — EOD Snapshot (pre-launch baseline)` (L13) |
| Non-trading day snapshot | 4 | no | `May 10 — Non-Trading Day Snapshot (Sunday; reflects May 08 close)` (L413) |
| Market-open trades / review / exits at open | 36 | no | `2026-04-28 — Market-Open Trades` (L20), `2026-05-01 — Market-Open Review (Friday)` (L59), `2026-09-17 — Market-Open (Deployment Backstop)` (L2849) |
| Midday scan / snapshot / reconciliation / exits | 83 | no | `### Aug 3 — Midday Scan (Day 69, Monday)` (L1937), `2026-05-19 — Midday Snapshot` (L561), `2026-05-18 — Midday Reconciliation (position state audit)` (L532), `Jun 09 — Midday Exits` (L1085) |
| Stop exits and stop ops | 4 | no | `2026-05-06 — Stop Exits` (L246), `2026-06-02 — PLTR Stop-Out` (L915), `2026-06-04 — Stop Executions at Open` (L983), `Sep 16 — Stop Renewal (Day 101, Wednesday, manual ops)` |
| Undated sub-sections | 12 | n/a | `### Actions` (L786), `### XOM — Stop-Out (Trailing Stop Triggered)` (L718), `### New Trades` (L724) |

Two date spellings here too: ISO (`2026-04-28 — Market-Open Trades`) and
`Mon D` (`Jun 10 — Market-Open Trades`); both occur for the same kind on the
same day (2026-06-10, L1107 and L1126 are two entries for one open).

## 4. Which trades the record explains

Join: a lifecycle is *explained* when a research entry dated within the three
days up to and including the entry date names its symbol, and *recorded* when
a trade-log entry on the entry date names it. Symbol `F` (two engineering
test round trips, 2026-08-11) is skipped by name.

| Lifecycle (entry date) | Research entries | Trade-log entries that day |
|---|---|---|
| PLTR, AMD, NVDA (2026-04-28) | **none**: the research log starts 2026-04-30 | `2026-04-28 — Market-Open Trades` (L20, table) |
| AMD, XOM, PLTR (2026-05-07) | 9 to 13 each (L633, L778, L810, L876) | 3 each, incl. the backfill `Market-Open Trades (Week of May 5, Backfill)` (L293) |
| WMT (2026-05-21, same-day round trip) | 2 (L2229, L2277) | 2 (L602, L615) |
| MU (05-26), AVGO (05-27), NVDA and MSFT (06-03), XOM (06-10), XLF and GOOGL (06-25), XLI and XLB (06-29) | 1 to 7 each | 2 to 4 each |
| XLP (06-30), XLK (08-10), XLE (09-17), MPC (09-28), PSX (10-02): open lots | 1 to 4 each; PSX only via the `###` header at L7930 | 3 each |

So 20 of 21 non-test lifecycles are explained and all 21 are recorded. The
unexplained three are the launch-day buys, whose reasoning exists only in
`2026-04-28 — Market-Open Trades` itself. One EOD date, 2026-06-19, has no
research entry at all (a trading day with an EOD snapshot and no pre-market or
midday session logged).

## 5. How a symbol is mentioned

Across the 174 `##` research entries, symbols appear in a table cell 480
times, in plain prose 366 times and in bold 38 times (one count per symbol
per entry, first form wins). Plain prose dominates the later entries
(September and October pre-market sessions mention PSX, MPC and XLE only in
sentences). Consequences:

- Table and bold mentions can be extracted mechanically and are reliable.
- Plain mentions need the symbol list from `memory/SECTORS.json` plus the
  blotter, and a word boundary that excludes `**`, backticks and letters.
  False positives to expect: `F` (never match it bare), `MU` inside words if
  the boundary is wrong, and ETF names in macro prose (`XLE` discussed as a
  sector, not a position).
- Nothing in the record states "this entry is the thesis for this trade". The
  thesis is the `### Decision` sub-section (175 of them) of the pre-market
  entry on the entry date, when one exists; the index can point at it but
  cannot verify it without the trade id (ADR 0014,
  [#172](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/172)).

## 6. Implications for the index builder (#174)

1. Treat any `##`/`###` header beginning with an ISO date or `Mon D` as an
   entry; reuse `parse_header_date` from the dashboard builder (it already
   handles both spellings and `Day 0`).
2. Classify by family keyword after the first ` — `; keep an explicit
   allow-list for the headers without one (`May 21 Execution Note`, `Day 0 —
   EOD Snapshot (pre-launch baseline)`); fail on anything else.
3. Expect two entries of one kind on one date (2026-06-10 market-open, 36
   research dates with more than one session) and never key an entry by date
   and kind alone.
4. Expect no research entry for 2026-04-28 and 2026-06-19 and do not fail on
   that; fail only when a *lifecycle's entry date* has no trade-log entry.
5. Extract symbols from tables and bold first, then prose with the strict
   boundary; record the mention form in the index so a consumer can weigh it.
