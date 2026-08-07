// ============ DATA — origin/main, latest log 2026-08-07 ============

// {d, n: phase day, v: portfolio $, cash: cash %, dp: day P&L %}
const EQ = [
{d:"2026-04-27",n:0,v:100000.00,cash:100.0,dp:0,note:"Day 0 baseline"},
{d:"2026-04-30",n:3,v:101188.25,cash:41.0,dp:0.37,note:"AMD +11.96% unrealized"},
{d:"2026-05-27",n:21,v:106240.66,cash:43.2,dp:-0.40,note:"MU +8.58% · XOM closed +$95"},
{d:"2026-06-04",n:27,v:110269.20,cash:63.6,dp:-3.59,note:"PEAK +10.27% — only 36% deployed"},
{d:"2026-06-09",n:30,v:107304.78,cash:100.0,dp:-1.24,note:"MSFT & NVDA stops fired — full reset"},
{d:"2026-06-10",n:31,v:107380.00,cash:80.1,dp:0.07,note:"Redeployed into XOM"},
{d:"2026-06-11",n:32,v:106802.05,cash:80.5,dp:-0.54,note:""},
{d:"2026-06-12",n:33,v:106860.27,cash:80.5,dp:0.05,note:"First weekly review written"},
{d:"2026-06-15",n:34,v:106111.93,cash:100.0,dp:-0.70,note:"XOM thesis-break cut at −5.6% — before the −7% trigger"},
{d:"2026-06-17",n:36,v:106111.89,cash:100.0,dp:0,note:"100% cash — FOMC hold"},
{d:"2026-06-18",n:37,v:106111.89,cash:100.0,dp:0,note:"100% cash"},
{d:"2026-06-19",n:38,v:106111.89,cash:100.0,dp:0,note:"100% cash"},
{d:"2026-06-22",n:39,v:106111.89,cash:100.0,dp:0,note:"/conviction run: DELL ✓ GNRC ✓ MU refused"},
{d:"2026-06-23",n:40,v:106111.89,cash:100.0,dp:0,note:"100% cash"},
{d:"2026-06-24",n:41,v:106111.89,cash:100.0,dp:0,note:"100% cash — 6th straight idle session"},
{d:"2026-06-25",n:42,v:106311.92,cash:60.4,dp:0.19,note:"Idle streak broken: GOOGL + XLF bought"},
{d:"2026-06-26",n:43,v:106037.79,cash:60.6,dp:-0.26,note:""},
{d:"2026-06-29",n:44,v:107036.18,cash:40.2,dp:0.94,note:"XLF→XLI/XLB sector rotation"},
{d:"2026-06-30",n:45,v:107390.64,cash:20.6,dp:0.33,note:"XLP added — INSIDE 75–85% band for the first time"},
{d:"2026-07-01",n:46,v:107577.99,cash:20.5,dp:0.17,note:""},
{d:"2026-07-02",n:47,v:108323.07,cash:20.4,dp:0.69,note:""},
{d:"2026-07-03",n:48,v:108416.69,cash:20.4,dp:0.09,note:"Best week: +2.24%, beat S&P"},
{d:"2026-07-06",n:49,v:108765.07,cash:20.3,dp:0.32,note:"Post-reset high"},
{d:"2026-07-07",n:50,v:108409.91,cash:20.4,dp:-0.33,note:""},
{d:"2026-07-08",n:51,v:107249.33,cash:20.6,dp:-1.07,note:""},
{d:"2026-07-09",n:52,v:106832.87,cash:20.7,dp:-0.39,note:""},
{d:"2026-07-10",n:53,v:107362.43,cash:20.6,dp:0.50,note:""},
{d:"2026-07-13",n:54,v:106859.33,cash:20.7,dp:-0.47,note:""},
{d:"2026-07-14",n:55,v:106970.97,cash:20.7,dp:0.10,note:""},
{d:"2026-07-15",n:56,v:107625.79,cash:20.5,dp:0.61,note:"GOOGL +10.55% intraweek high"},
{d:"2026-07-16",n:57,v:107395.43,cash:20.6,dp:-0.21,note:""},
{d:"2026-07-17",n:58,v:106468.17,cash:20.7,dp:-0.86,note:""},
{d:"2026-07-20",n:59,v:106425.55,cash:20.8,dp:-0.04,note:""},
{d:"2026-07-21",n:60,v:106043.03,cash:20.8,dp:-0.36,note:""},
{d:"2026-07-22",n:61,v:105964.35,cash:20.9,dp:-0.07,note:"GOOGL 0.7% above its stop into Q2 print"},
{d:"2026-07-23",n:62,v:104741.70,cash:40.2,dp:-1.15,note:"GOOGL gapped through stop: −$832.73 (−3.99%)"},
{d:"2026-07-24",n:63,v:105442.33,cash:39.9,dp:0.67,note:"Weekly review: source a single-name engine"},
{d:"2026-07-27",n:64,v:105878.53,cash:39.8,dp:0.41,note:"All 3 positions green on cost"},
{d:"2026-07-28",n:65,v:106612.57,cash:39.5,dp:0.69,note:""},
{d:"2026-07-29",n:66,v:105942.93,cash:39.8,dp:-0.63,note:""},
{d:"2026-07-30",n:67,v:105456.07,cash:39.9,dp:-0.46,note:""},
{d:"2026-07-31",n:68,v:105015.75,cash:40.1,dp:-0.42,note:""},
{d:"2026-08-03",n:69,v:105619.01,cash:39.9,dp:0.57,note:""},
{d:"2026-08-04",n:70,v:106553.93,cash:39.5,dp:0.89,note:""},
{d:"2026-08-05",n:71,v:106751.43,cash:39.5,dp:0.19,note:""},
{d:"2026-08-06",n:72,v:106318.35,cash:39.6,dp:-0.41,note:""},
{d:"2026-08-07",n:73,v:106626.35,cash:39.5,dp:0.29,note:""}
];

// weekly reviews, verbatim
const WEEKS = [
{w:"06/12", bot:-1.65, spx:0.70},
{w:"06/19", bot:-0.70, spx:0.93},
{w:"06/26", bot:-0.07, spx:-1.91},
{w:"07/03", bot:2.24, spx:1.71},
{w:"07/10", bot:-0.97, spx:0.81},
{w:"07/17", bot:-0.83, spx:-0.90},
{w:"07/24", bot:-0.96, spx:-0.33},
{w:"07/31", bot:-0.40, spx:0.35}
];

const BOOK = [ // Aug 7 EOD
{s:"XLB", q:412, in:51.07, pl:737.35, plp:3.50, stop:47.664, w:20.4},
{s:"XLI", q:116, in:182.16, pl:350.32, plp:1.66, stop:169.37, w:20.1},
{s:"XLP", q:250, in:83.76, pl:312.50, plp:1.49, stop:79.902, w:19.9}
];

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
{d:"07/28", b:"hold", x:"FOMC Jul 28–31: <b>no new risk into the decision</b>. Redeploy deferred again."}
];

const RULES = [
{ok:"✓", c:"up",   t:"10% trailing GTC on every position", v:"'spotless 4 straight weeks' · none lowered"},
{ok:"✓", c:"up",   t:"Max 3 trades/wk · 20% cap · ≤6 positions", v:"never breached in 73 days"},
{ok:"✓", c:"up",   t:"Cut on thesis break, don't wait for −7%", v:"XOM Jun 15 at −5.6%"},
{ok:"✓", c:"up",   t:"Exit sector after 2 failed trades", v:"tech flagged Jun 09, re-entry gated"},
{ok:"△", c:"warn", t:"75–85% deployed", v:"reached Jun 30 · lost Jul 23 · now 60.5%"},
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
