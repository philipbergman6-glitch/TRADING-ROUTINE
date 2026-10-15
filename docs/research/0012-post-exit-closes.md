# 0012 — Post-exit daily closes for the brain outcome review

Research note for Wayfinder ticket
[#182](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/182)
(parent map [#169](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/169),
blocking [#180](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/180)).
Researched 2026-10-15. Sources: this repository as checked out at `248c467`
(scripts, tests, ADRs, `memory/`, `state/`), Alpaca reference docs and FAQ
(docs.alpaca.markets), alpaca.markets/learn and /support pages, the
`alpacahq/alpaca-py` source, and Alpaca-staff forum posts. **No broker call
was made**: the research worktree carries no API key, so every statement
about the live API is from documentation or from what the repo already
verified in ADR 0008, and is marked as such.

Question: research 0006 §"What exited names did afterwards" needs the daily
close of each exited symbol for +5 and +20 sessions after the exit and to
date. The brain index builder (`scripts/build_brain_index.py`, planned) must
be offline and deterministic so that `--check` in CI compares a golden file.
Where do those closes come from?

## VERDICT (up front)

1. **Nothing committed today can reproduce the 0006 table.** The repo holds
   closes only for *held* positions on *logged* sessions (the EOD snapshot
   table in `memory/TRADE-LOG.md`, 445 rows). After an exit the symbol drops
   out of that table, so the post-exit path is exactly the data the repo does
   not have. `scripts/reconcile_equity.py` fetches SIP closes on every run and
   caches nothing; `memory/RECONCILIATION-EXCEPTIONS.json` holds three equity
   diffs, no prices; `state/events.jsonl` holds run and intent records, no
   prices; `docs/research/0006` holds percentages, not closes.
2. **The endpoint is the one `scripts/alpaca.sh bars` already calls**:
   `GET https://data.alpaca.markets/v2/stocks/bars?symbols=…&timeframe=1Day&feed=sip&adjustment=raw&limit=10000`,
   paged by `next_page_token`. A free (Basic) paper key reads SIP daily bars
   for any `end` at least 15 minutes old (HTTP 403 `42210000` otherwise),
   200 requests/min, history back to 2016-01-04, and the data subscription
   is bound to the user id, not to the account's positions, so an exited
   symbol's bars stay readable indefinitely. Delisted symbols stay in the
   database but can be renamed; none of ours is delisted.
3. **Recommended cache: `memory/CLOSES.json`, written by the daily-summary
   routine (which already has the key and already commits `memory/`), read
   by the builder, never fetched in CI.** One JSON object keyed by symbol,
   then by ISO session date, value the SIP `raw` close as a Decimal string;
   a `_meta` block naming the feed, adjustment and the last session covered.
   The writer refreshes forward only (yesterday's session for every symbol
   with an open lot or an exit in the last 20 sessions plus a to-date tail
   for every exited symbol), hard-fails on any missing day, and never writes
   a partial file. The builder treats a missing close as a build error, not
   as a blank cell.

## 1. What close data is already committed

| Location | What it holds | Closes? | Coverage |
|---|---|---|---|
| `memory/TRADE-LOG.md` EOD snapshot tables | `Ticker, Shares, Entry, Close, Day Chg, Unrealized P&L, Stop` per held position per logged session | Yes, for **held** positions only | 117 EOD snapshots, 445 position rows, 16 symbols (AMD, AVGO, GOOGL, MPC, MSFT, MU, NVDA, PLTR, PSX, XLB, XLE, XLF, XLI, XLK, XLP, XOM); F and WMT never survived to an EOD. Five broker sessions have no EOD entry (0006: Apr 28, Apr 29, May 11, Jun 15, Jun 16). The "Close" is whatever the routine read from `/v2/positions` near 20:10 UTC, not a documented SIP close (`routines/daily-summary.md` step 4 does not say which price). |
| `memory/BLOTTER.json` | 18 round trips, 5 open lots; `avg_in`, `avg_out`, `pnl` as strings | Exit price only (`avg_out`) | Exits 2026-05-06 to 2026-09-30, 13 symbols. Provides the exit session and price the outcome review starts from. |
| `memory/RECONCILIATION-EXCEPTIONS.json` | Three sessions (2026-05-04, 2026-06-02, 2026-07-29) with an equity `diff` and a reason | No | — |
| `scripts/reconcile_equity.py` `fetch_closes` | Calls `alpaca.sh bars` for every symbol ever filled, from the first fill to the last past broker session, on **every run** | No cache; result lives in memory and is discarded | Lines 66-83: returns `dict[(symbol, date), Decimal]`; `risk_engine/accounting.py:154` raises `no close for SYM on DATE` when a held lot has no close. This is the only SIP-close consumer and it already fetches the entire post-exit range for exited symbols as a side effect (symbols = every fill, dates = whole history), then throws it away. |
| `state/events.jsonl` | 32 run/intent records | No | — |
| `docs/research/0006-paper-results-reconciliation.md` lines 109-132 | 14 exits × (+5, +20, to Sep 18) as percentages | Derived numbers only, from **IEX** bars (header line 6), not SIP | Not reproducible from the repo; the source bars were never committed. |
| `docs/dashboard/data.js` | Equity series, book, trades | No prices beyond the EOD table | — |

Direct observation: `git ls-files | grep -i 'close\|bars\|prices'` returns only
`docs/adr/0008-…`, `scripts/close_position.py`, `tests/test_close_position.py`.
There is no committed bar or price file anywhere in the repo.

Consequence for the builder: the +5/+20 columns for the 18 exits need 36
specific (symbol, session) closes plus a to-date close per exited symbol,
and the EOD table can supply at most the exit-day close for a few of them
(when another lot of the same symbol was still held). A cache is required.

## 2. Alpaca endpoint, feed, limits, history

### 2.1 How the repo calls it today

`scripts/alpaca.sh` lines 209-224 (`bars`): hard-codes
`$DATA/stocks/bars?symbols=$syms&timeframe=1Day&start=$start&end=$end&feed=sip&adjustment=raw&limit=10000`
with optional `page_token`, where `DATA` must equal
`https://data.alpaca.markets/v2` (line 44 refuses anything else). The
comment on line 210-211 records the 15-minute SIP rule. The script validates
`SYMBOLS` against `^[A-Z.]{1,10}(,[A-Z.]{1,10})*$`, dates against
`YYYY-MM-DD`, and the page token against `^[A-Za-z0-9|:_=-]{1,120}$`.
`tests/test_reconcile_equity.py:47` pins the exact URL.

`scripts/validate_order.py:134` parses every adapter response with
`json.loads(…, parse_float=str)`, and `fetch_closes` passes `bar["c"]` to
`risk_engine.models.to_money`, which rejects floats outright (`models.py:63`).
So the existing path already turns Alpaca's JSON-number closes into
Decimals losslessly; the cache writer must reuse `adapter()` rather than
`requests`/`json.loads` defaults.

ADR 0008 (2026-10-12) chose SIP over IEX after checking all 122 sessions:
"Broker portfolio-history equity equals cash plus held lots at the
consolidated (SIP) close on 119 of 122 sessions to the cent; IEX closes miss
by $6 median and up to $100". That is the repo's own empirical proof that
**a Basic paper key reads `feed=sip` daily bars** and that SIP, not IEX, is
the close the broker marks to. Research 0006 used IEX; its percentages will
therefore not match a SIP-based rebuild exactly (expect differences of a few
basis points), which the outcome review should state rather than hide.

### 2.2 Feed access for a Basic (free) paper key — from Alpaca docs

- `feed` on `/v2/stocks/bars` is one of `sip`, `iex`, `otc`, `boats`
  ([reference](https://docs.alpaca.markets/reference/stockbars)). The
  alpaca-py `DataFeed` enum also lists `delayed_sip` and `overnight`, but
  `overnight` is documented as an error on historical bars ("include
  feed=boats") and `delayed_sip` is a streaming feed name; neither is
  verified for this endpoint.
- Default when `feed` is omitted: "the 'best' available feed based on the
  user's subscription" ([FAQ](https://docs.alpaca.markets/docs/market-data-faq)),
  i.e. IEX on Basic. The reference page literally says "Default sip"; the
  FAQ and staff posts describe the effective behaviour. **Always pass
  `feed=sip` explicitly**, as `alpaca.sh` does; an omitted feed would
  silently return IEX closes that ADR 0008 showed are wrong by dollars.
- Basic may query SIP history: "For historical queries, the `end` parameter
  must be at least 15 minutes old to query SIP data without a subscription"
  ([FAQ](https://docs.alpaca.markets/docs/market-data-faq)); plan table
  "Historical data limitation: latest 15 minutes" for Basic
  ([About Market Data API](https://docs.alpaca.markets/docs/about-market-data-api)).
  Violation returns HTTP 403 `{"code":42210000,"message":"subscription does
  not permit querying recent SIP data"}` (FAQ; staff-confirmed on the
  [forum](https://forum.alpaca.markets/t/subscription-does-not-permit-querying-recent-sip-data/14751)).
  Omitting `end` defaults to "15 minutes before the current time" for
  users without real-time access ([reference](https://docs.alpaca.markets/reference/stockbars)).
  For a daily cache this never bites: the writer asks for sessions up to
  yesterday.
- Paper vs live keys: "it doesn't matter if you use your paper trading or
  your live trading keys … It's your user ID that's tied to your data
  subscription" (Dan Whitnable, Alpaca staff, 2025-09-12,
  [forum](https://forum.alpaca.markets/t/key-limitations-on-paper-trading-keys/17789)).

### 2.3 Rate limits, paging, depth

- Basic: 200 requests/min; Algo Trader Plus: 10,000/min
  ([About Market Data API](https://docs.alpaca.markets/docs/about-market-data-api),
  [alpaca.markets/data](https://alpaca.markets/data)); over the limit returns
  HTTP 429 ([support](https://alpaca.markets/support/usage-limit-api-calls)).
  One multi-symbol request per day is three orders of magnitude under this.
- `limit` 1 to 10,000 bars, default 1,000, counted across all symbols in
  the request, not per symbol; continue with `page_token` =
  `next_page_token` until null ([reference](https://docs.alpaca.markets/reference/stockbars),
  [learn article](https://alpaca.markets/learn/fetch-historical-data)).
  `fetch_closes` already loops this with a 200-page ceiling. The whole
  history to date is 13 exited symbols × ≤120 sessions ≈ 1,600 bars: one
  page.
- Multi-symbol: `symbols` comma-separated, response
  `{"bars": {"SYM": [...]}, "next_page_token": …}`; no documented maximum
  symbol count (staff suggests keeping the URL under ~4,000 symbols,
  [forum](https://forum.alpaca.markets/t/get-minute-bars-for-multiple-symbols/12773)).
  `sort` is `asc` by default.
- History depth: "Since 2016" on both plans
  ([About Market Data API](https://docs.alpaca.markets/docs/about-market-data-api));
  exact start 2016-01-04, "available for both the free Basic and the paid
  data subscriptions" (staff, [forum](https://forum.alpaca.markets/t/wrong-historical-data-for-past-4-years/14802)).

### 2.4 Are bars for a symbol we no longer hold still available months later?

Yes. The data subscription is a property of the user, not of the trading
account's positions (§2.2, staff post 17789); no Alpaca page conditions
historical bars on holdings, and `fetch_closes` already pulls every
historical fill symbol (PLTR, WMT, F, …) on each daily run months after
their exits (ADR 0008 ran it over the full history on 2026-10-12). Two
caveats from staff posts: delisted symbols "remain in the database" but may
be re-keyed with a numeric suffix ([forum 8493](https://forum.alpaca.markets/t/are-alpaca-historical-tick-data-point-in-time/8493),
[forum 18227](https://forum.alpaca.markets/t/delisted-tickers/18227)), and
symbol renames need `asof=YYYY-MM-DD` ([reference](https://docs.alpaca.markets/reference/stockbars)).
None of the 13 exited symbols is delisted or renamed; the cache writer
should still hard-fail when a requested symbol returns zero bars rather than
emit an empty series.

### 2.5 Are daily closes stable once fetched?

Not guaranteed. Alpaca publishes no immutability statement. The FAQ's
condition table includes trade condition `9` "Corrected Consolidated Close",
which updates the daily bar; staff have edited adjusted history after
corporate-action fixes ([forum 15101](https://forum.alpaca.markets/t/adjusted-historic-bar-data-is-inaccurate/15101))
and escalate bad raw bars to the data team ([forum 14802](https://forum.alpaca.markets/t/wrong-historical-data-for-past-4-years/14802)).
Implications: (a) fetch `adjustment=raw`, as today, because adjusted series
move whenever Alpaca's corporate-action table changes; (b) a committed cache
is *more* deterministic than a live fetch, which is the point; (c) the
writer must never silently overwrite an existing value. If a refetch
disagrees with the committed close, that is an incident to record (same
pattern as `RECONCILIATION-EXCEPTIONS.json`), not an in-place edit.

Timestamp semantics: a 1Day bar's `t` is the New-York calendar day rendered
in UTC (`2026-04-28T04:00:00Z` in EDT, `…T05:00:00Z` in EST)
([FAQ](https://docs.alpaca.markets/docs/market-data-faq)). `fetch_closes`
takes `str(bar["t"])[:10]`, which is the session date in both cases. The
close is the closing-auction print; extended-hours trades do not move daily
OHLC ([FAQ](https://docs.alpaca.markets/docs/market-data-faq)).

## 3. Recommended shape for the committed closes cache

### 3.1 File

`memory/CLOSES.json`, next to `BLOTTER.json` and
`RECONCILIATION-EXCEPTIONS.json`, because (a) the daily-summary routine
already stages and pushes `memory/TRADE-LOG.md memory/BLOTTER.json`
(`routines/daily-summary.md:99`), (b) the dashboard workflow is triggered by
pushes to `memory/**` (`.github/workflows/dashboard.yml:3-7`), so the brain
index can be rebuilt by the same trigger, and (c) `state/` is the
append-only run-record store (ADR 0012) and should not carry derived market
data.

```json
{
  "_meta": {
    "source": "alpaca /v2/stocks/bars timeframe=1Day feed=sip adjustment=raw",
    "written_by": "scripts/closes.py",
    "schema": 1,
    "through": "2026-10-14"
  },
  "PLTR": {
    "2026-05-06": "132.33",
    "2026-05-07": "131.90"
  },
  "AMD": {
    "2026-05-06": "409.10"
  }
}
```

Rules, each mirroring an existing repo rule:

- **Keys**: symbol (validated by the same `^[A-Z.]{1,10}$` as `alpaca.sh`),
  then ISO session date in New York time (what `session_of` returns for a
  fill, so an exit at `2026-05-06T14:06:56Z` keys to `"2026-05-06"`, the
  same day as its bar).
- **Values**: the SIP `raw` close as a **string**, produced by
  `to_money(bar["c"], …)` and serialised with `str(Decimal)`; readers load
  with `json.loads(…, parse_float=str)` and `to_money`, exactly as
  `load_exceptions` does (`reconcile_equity.py:88-99`). Never a JSON number.
  Dates sorted ascending and symbols sorted so the file diff is readable and
  the golden comparison is byte-stable (`json.dumps(sort_keys=True, indent=2)`).
- **Scope**: every symbol that has ever had a fill (the set `fetch_closes`
  already requests), from its first fill session through `_meta.through`.
  This includes held names, which gives the brain a documented SIP close for
  the open-position pages too and removes the ambiguity of the EOD table's
  "Close" column. Size: ~18 symbols × ~125 sessions today, growing ~5-10
  values per session; trivial.
- **Hard-fail, never partial**: the writer refuses to write if any requested
  (symbol, session) between the first fill and `through` is missing from the
  response (a trading day with no bar), if a symbol returns no bars, if a
  value fails `to_money`, or if a refetched session disagrees with the
  committed value. On refusal the old file stays untouched and the routine
  records an incident (ADR 0012 `--incident`), the same way
  `reconcile_equity.py` exit 4 stops the EOD snapshot. Sessions are the
  broker's, from `/v2/account/portfolio/history` timestamps as
  `session_equity` already derives them, so holidays are not guessed.
- **`through`**: the last *past* session (yesterday or earlier), because SIP
  is unavailable for the last 15 minutes and because the EOD routine runs
  near the close. The builder's "to date" column is "to `_meta.through`"
  and says so.

### 3.2 Who refreshes it

**The daily-summary routine, not CI.** Reasons, in order of weight:

1. CI has no market-data key. `tests.yml` and `dashboard.yml` reference no
   `ALPACA_*` secret; only `heartbeat.yml` and `protection-monitor.yml`
   carry the key pair, and those are the mutation-adjacent jobs the repo
   keeps deliberately small. Giving the test job a key would also make the
   golden check network-dependent, which is the thing `--check` exists to
   prevent.
2. The routine already runs `reconcile_equity.py` every session, which
   already fetches these exact bars (§1). Extending that one fetch to also
   persist its result costs one extra file write and no extra API call;
   writing it from a separate job would double the calls and create a second
   source of truth.
3. `memory/**` pushes already trigger the dashboard rebuild, so the brain
   index can be regenerated and `--check`ed in the same workflow run with no
   new trigger.

Concretely: add `scripts/closes.py` with `--check` (verify the committed
file covers every needed session through yesterday and matches a refetch of
the last N sessions) and `--write` (extend forward); call it in step 2 of
`routines/daily-summary.md` right after `reconcile_equity.py`, and add
`memory/CLOSES.json` to the `git add` on line 99. `reconcile_equity.py` can
then take its closes from the file when present and from the API only for
sessions the file lacks, which also removes its daily full-history refetch.

### 3.3 What the builder does with it

`build_brain_index.py` reads `memory/BLOTTER.json` for each round trip's
exit session and `avg_out`, looks up `CLOSES[symbol]` for the exit session
and the 5th and 20th later keys in that symbol's series, and the last key
≤ `_meta.through`, and emits the percentage as a Decimal string with the
session dates it used. If fewer than 5 or 20 sessions exist after the exit
(XLB, exited 2026-09-30, has 10 sessions to 2026-10-14) the column is
`null` with the count available, never a projection from fewer sessions. A
missing exit-day close is a build error (exit non-zero, nothing written),
matching the dashboard builder's `fail()` behaviour.

Reproducing 0006's table exactly is not a goal: 0006 used IEX closes; the
cache is SIP. The first build should print both side by side once (SIP vs
the 0006 numbers) so the difference is on record, then 0006 stays as
written.

## Repo implications (for #180)

1. Outcome record fields that this data supports: `exit_session`,
   `exit_price` (blotter `avg_out`), `close_plus_5`, `close_plus_20`,
   `close_through` with their session dates, and the three percentages;
   all strings. Anything needing intraday prices (max adverse excursion
   after exit) is out of scope for a daily-close cache.
2. Writer: daily-summary routine via `scripts/closes.py`; reader:
   `build_brain_index.py`; checker: `tests.yml` golden via `--check` with
   no network.
3. Keep `feed=sip&adjustment=raw` and the `parse_float=str` adapter path;
   never introduce a second HTTP client for bars.
4. Record refetch disagreements as exceptions, do not overwrite.

## Open questions (not answerable from this worktree)

- No live GET was made: this worktree has no key in its environment, and
  the hook forbids loading one. ADR 0008's 119/122 reconciliation is the
  repo's evidence that `feed=sip` works on the Basic paper key; it was not
  re-run here.
- Whether an omitted `feed` on `/v2/stocks/bars` silently returns IEX on
  Basic or errors (docs disagree; moot if `feed=sip` is always passed).
- Whether `delayed_sip` is accepted on the historical bars endpoint
  (irrelevant to a next-day cache).
- Exact 429 body for market data (only user reports, not official docs).
- How often, if ever, a `raw` daily close is restated after the session;
  the cache's disagree-and-refuse rule covers it without needing the answer.

## Sources

Repository (commit `248c467`):

- `scripts/alpaca.sh` lines 32-46, 209-224 (`bars` verb, endpoint guard)
- `scripts/reconcile_equity.py` lines 66-99 (`fetch_closes`, `load_exceptions`)
- `scripts/validate_order.py` lines 106-137 (`adapter`, `parse_float=str`)
- `risk_engine/models.py` lines 56-70 (`to_money` rejects floats)
- `risk_engine/accounting.py` lines 57-61, 119-154 (`session_of`, missing-close error)
- `tests/test_reconcile_equity.py` lines 47-56, 84 (URL pin, bars fixture)
- `docs/adr/0008-equity-reconciles-to-sip-closes-with-recorded-exceptions.md`
- `docs/research/0006-paper-results-reconciliation.md` lines 1-10, 109-132
- `memory/BLOTTER.json`, `memory/RECONCILIATION-EXCEPTIONS.json`, `memory/TRADE-LOG.md`, `state/events.jsonl`
- `routines/daily-summary.md` lines 49-56, 81-101
- `.github/workflows/tests.yml`, `dashboard.yml`, `heartbeat.yml`, `protection-monitor.yml`
- `scripts/build_dashboard_data.py` lines 410-430, 636-650 (golden `--check` pattern)

Alpaca (read 2026-10-15):

- Historical bars reference: https://docs.alpaca.markets/reference/stockbars
- Market data FAQ (15-minute SIP rule, 403 code 42210000, bar timestamps, condition codes): https://docs.alpaca.markets/docs/market-data-faq
- About Market Data API (plans, 200/min vs 10,000/min, "since 2016", 15-minute limitation): https://docs.alpaca.markets/docs/about-market-data-api
- Historical stock data overview: https://docs.alpaca.markets/docs/historical-stock-data-1
- Latest bars reference (feed enum incl. delayed_sip/overnight): https://docs.alpaca.markets/us/reference/stocklatestbars-1
- Pricing/plans page: https://alpaca.markets/data
- Fetch historical data guide (limit 1-10,000, paging, adjustment default raw): https://alpaca.markets/learn/fetch-historical-data
- Bars with pandas guide (1Day `t` examples): https://alpaca.markets/learn/understanding-alpacas-market-data-api-with-pandas-and-plotly
- API usage limits (429): https://alpaca.markets/support/usage-limit-api-calls
- Data timeline (no data before 2016): https://alpaca.markets/support/alpaca-data-timeline
- alpaca-py enums (`DataFeed`, `Adjustment`): https://raw.githubusercontent.com/alpacahq/alpaca-py/master/alpaca/data/enums.py
- Staff forum posts: paper vs live keys https://forum.alpaca.markets/t/key-limitations-on-paper-trading-keys/17789 ; recent SIP 403 https://forum.alpaca.markets/t/subscription-does-not-permit-querying-recent-sip-data/14751 ; 2016-01-04 start https://forum.alpaca.markets/t/wrong-historical-data-for-past-4-years/14802 ; delisted symbols https://forum.alpaca.markets/t/are-alpaca-historical-tick-data-point-in-time/8493 and https://forum.alpaca.markets/t/delisted-tickers/18227 ; multi-symbol size https://forum.alpaca.markets/t/get-minute-bars-for-multiple-symbols/12773 ; adjusted history edits https://forum.alpaca.markets/t/adjusted-historic-bar-data-is-inaccurate/15101 ; daily bars and extended hours https://forum.alpaca.markets/t/historical-vwap-data-very-wrong/14272
