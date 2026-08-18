// ============ DATA — origin/main, latest log 2026-08-18 ============

// Two independent dates. LOG_ASOF moves nightly with the trade log;
// ANALYSIS_ASOF only moves when a human rewrites the editorial prose.
// The dashboard shows both, so curated text can never pass as live.
const LOG_ASOF = "2026-08-18";
const ANALYSIS_ASOF = "2026-08-11";

// {d, n: phase day, v: portfolio $, cash: cash %, dp: day P&L %}
const EQ = [
{d:"2026-04-27",n:0,v:100000.00,cash:100.0,dp:0,note:"Day 0 baseline"},
{d:"2026-04-30",n:3,v:101188.25,cash:41.0,dp:0.37,note:"AMD +11.96% unrealized"},
{d:"2026-05-01",n:4,v:102159.73,cash:40.6,dp:0.96,note:""},
{d:"2026-05-04",n:5,v:101531.49,cash:40.9,dp:-0.61,note:""},
{d:"2026-05-05",n:6,v:100544.39,cash:41.3,dp:-1.58,note:""},
{d:"2026-05-06",n:7,v:104300.81,cash:82.1,dp:3.78,note:""},
{d:"2026-05-07",n:8,v:104462.50,cash:23.1,dp:0.12,note:""},
{d:"2026-05-08",n:9,v:106883.36,cash:22.5,dp:2.29,note:""},
{d:"2026-05-12",n:11,v:107421.02,cash:22.4,dp:-0.61,note:""},
{d:"2026-05-13",n:12,v:107180.71,cash:22.5,dp:-0.47,note:""},
{d:"2026-05-14",n:13,v:108988.76,cash:22.1,dp:1.64,note:""},
{d:"2026-05-15",n:14,v:107377.97,cash:22.4,dp:-1.54,note:""},
{d:"2026-05-18",n:15,v:107759.59,cash:41.5,dp:0.13,note:""},
{d:"2026-05-19",n:16,v:107915.62,cash:41.5,dp:0.15,note:""},
{d:"2026-05-20",n:17,v:107634.89,cash:41.6,dp:-0.26,note:""},
{d:"2026-05-21",n:18,v:107112.97,cash:41.8,dp:-0.43,note:""},
{d:"2026-05-22",n:19,v:106564.66,cash:42.0,dp:-0.51,note:""},
{d:"2026-05-26",n:20,v:106636.22,cash:39.9,dp:0.03,note:""},
{d:"2026-05-27",n:21,v:106240.66,cash:43.2,dp:-0.40,note:"MU +8.58% · XOM closed +$95"},
{d:"2026-05-28",n:22,v:107848.46,cash:42.6,dp:1.58,note:""},
{d:"2026-05-29",n:23,v:111707.65,cash:41.1,dp:3.55,note:""},
{d:"2026-06-01",n:24,v:114530.97,cash:40.1,dp:2.37,note:""},
{d:"2026-06-02",n:25,v:115135.09,cash:60.0,dp:0.43,note:""},
{d:"2026-06-03",n:26,v:114269.45,cash:24.8,dp:0.80,note:""},
{d:"2026-06-04",n:27,v:110269.20,cash:63.6,dp:-3.59,note:"PEAK +10.27% — only 36% deployed"},
{d:"2026-06-05",n:28,v:108427.98,cash:64.7,dp:-1.73,note:""},
{d:"2026-06-08",n:29,v:108665.16,cash:64.5,dp:0.09,note:""},
{d:"2026-06-09",n:30,v:107304.78,cash:100.0,dp:-1.24,note:"MSFT & NVDA stops fired — full reset"},
{d:"2026-06-10",n:31,v:107380.00,cash:80.1,dp:0.07,note:"Redeployed into XOM"},
{d:"2026-06-11",n:32,v:106802.05,cash:80.5,dp:-0.54,note:""},
{d:"2026-06-12",n:33,v:106860.27,cash:80.5,dp:0.05,note:"First weekly review written"},
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
{d:"2026-08-04",n:70,v:106553.93,cash:39.5,dp:0.89,note:"Fresh phase high — all 3 green on cost"},
{d:"2026-08-05",n:71,v:106751.43,cash:39.5,dp:0.19,note:""},
{d:"2026-08-06",n:72,v:106318.35,cash:39.6,dp:-0.41,note:""},
{d:"2026-08-07",n:73,v:106626.35,cash:39.5,dp:0.29,note:"Rule 12 written: deployment backstop after 3 idle sessions"},
{d:"2026-08-10",n:74,v:106511.38,cash:19.8,dp:-0.11,note:"Rule 12 fires: XLK bought — 60.4% → 80.2%, back in band"},
{d:"2026-08-11",n:75,v:106566.02,cash:19.8,dp:0.05,note:""},
{d:"2026-08-12",n:76,v:106722.69,cash:19.7,dp:0.15,note:""},
{d:"2026-08-13",n:77,v:107045.71,cash:19.7,dp:0.30,note:""},
{d:"2026-08-14",n:78,v:107073.85,cash:19.7,dp:0.03,note:""},
{d:"2026-08-17",n:79,v:106707.17,cash:19.8,dp:-0.34,note:""},
{d:"2026-08-18",n:80,v:105887.25,cash:19.9,dp:-0.77,note:""}
];

// weekly reviews. spx = as logged that week (contemporaneous record);
// spxc = re-chained from the logged closes so the series is continuous;
// est:1 = no index levels in the log, spxc falls back to spx.
const WEEKS = [
{w:"05/01", bot:2.14, spx:0.56, spxc:0.56, est:1},
{w:"05/08", bot:5.40, spx:1.78, spxc:1.78, est:1},
{w:"05/15", bot:0.53, spx:0.08, spxc:0.08, est:1},
{w:"05/22", bot:-1.17, spx:0.50, spxc:0.50, est:1},
{w:"05/29", bot:4.85, spx:1.50, spxc:1.50, est:1},
{w:"06/05", bot:-3.06, spx:-2.35, spxc:-2.35, est:1},
{w:"06/12", bot:-1.65, spx:0.70, spxc:0.70, est:1},
{w:"06/19", bot:-0.70, spx:0.93, spxc:0.93, est:1},
{w:"06/26", bot:-0.07, spx:-1.91, spxc:-1.91, est:0},
{w:"07/03", bot:2.24, spx:1.71, spxc:1.71, est:0},
{w:"07/10", bot:-0.97, spx:0.81, spxc:0.81, est:0},
{w:"07/17", bot:-0.83, spx:-0.90, spxc:-0.90, est:0},
{w:"07/24", bot:-0.96, spx:-0.33, spxc:-0.78, est:0},
{w:"07/31", bot:-0.40, spx:0.35, spxc:0.28, est:0},
{w:"08/07", bot:1.53, spx:3.58, spxc:4.30, est:0},
{w:"08/14", bot:0.42, spx:0.53, spxc:0.53, est:0}
];

const BOOK = [ // Aug 18 EOD
{s:"XLB", q:412, in:51.07, pl:292.39, plp:1.39, stop:48.24, w:20.1},
{s:"XLI", q:116, in:182.16, pl:163.56, plp:0.77, stop:169.37, w:20.1},
{s:"XLK", q:112, in:187.85, pl:-249.76, plp:-1.19, stop:172.575, w:19.6},
{s:"XLP", q:250, in:83.76, pl:455.00, plp:2.17, stop:79.902, w:20.2}
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
{d:"Jun 29", s:"XLI",  sec:"etf",  q:116, in:"182.16", out:"OPEN", open:1, pl:null, th:"Industrials leader"},
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

const RULES = [
{ok:"✓", c:"up",   t:"10% trailing GTC on every position", v:"4/4 live · none ever lowered"},
{ok:"✓", c:"up",   t:"Max 3 trades/wk · 20% cap · ≤6 positions", v:"never breached in 80 days"},
{ok:"✓", c:"up",   t:"Cut on thesis break, don't wait for −7%", v:"XOM Jun 15 at −5.6%"},
{ok:"✓", c:"up",   t:"Exit sector after 2 failed trades", v:"tech flagged Jun 09, re-entry gated"},
{ok:"✓", c:"up",   t:"75–85% deployed", v:"restored Aug 10 by rule 12 · now 80.1%"},
{ok:"✓", c:"up",   t:"Rule 12 — deployment backstop (self-written Aug 07)", v:"fired on schedule Aug 10 → XLK"},
{ok:"✗", c:"dn",   t:"Trim a stalled +10–15% single-name", v:"GOOGL flagged, not trimmed → round-trip"}
];

// Open-risk panel — editorial, dated with INSIGHTS above.
const RISK = [
{t:"Correlation", v:"4 sector ETFs, no single-name engine", c:"dn"},
{t:"Concentration", v:"every position sized 19.6–20.6% — one bad tape hits all", c:"warn"},
{t:"Next binary", v:"July CPI · Wed Aug 12, 8:30am ET", c:"warn"},
{t:"Weekly budget", v:"1 of 3 trades used", c:""},
{t:"Benchmark gap", v:"−0.6pp over 15 reviewed weeks — but −7.0pp over the last 9", c:"warn"}
];

// ---- EDITORIAL SECTION — analysis as of 2026-08-11; not derived from the logs ----
const INSIGHTS = [
{c:"var(--green)", n:"01", h:"It wrote a rule into its own strategy, then obeyed it on deadline.", p:"For 6 weeks the bot sat below its 75–85% deployment mandate, deferring redeployment every session under 'patience > activity'. On <b>Aug 07 the weekly review amended TRADING-STRATEGY.md itself</b> — Rule 12, deployment backstop — with the reason written in plain text: <i>'patience was masking non-compliance.'</i> On Aug 10 the market-open routine cited that rule and bought XLK, lifting deployment 60.4% → 80.2%. Diagnose → legislate → execute, unattended. This is the thing the weekly reviews kept flagging and never acting on: <b>a flag that finally became an order</b>."},
{c:"var(--red)", n:"02", h:"The tech book made everything. The ETF book has given most of it back.", p:"Six weeks of reviews were recovered on Aug 12 from unmerged branches, and they split the record cleanly at the June reset. Through the recovered weeks to Jun 05 the bot returned <b>+8.72% against a chained S&P of +2.03%</b>, peaking at <b>$115,135 on Jun 02</b>. Across the nine weeks since: <b>−1.86% against +5.13%</b>, ending at $106,566 — an <b>$8,569 giveback</b>. Over all 15 weeks that nets to +6.70% against +7.26%, a −0.57pp gap, 6 up weeks of 15. The April–May tech book made every dollar; the June–August ETF regime has bought discipline, not return. The open question is unchanged and now overdue: <b>which regime is the actual strategy?</b>"},
{c:"var(--amber)", n:"03", h:"The blotter's missing half has been recovered — and it is where the profit was.", p:"For months only six exits were written down, summing to −$5,531 (XOM +95, MSFT −1,690, NVDA −1,857, XOM −1,193, GOOGL −833, XLF −53), and the profitable Apr–May exits existed nowhere on main. On <b>Aug 12 they were recovered</b> from 136 unmerged session branches: <b>AMD +$5,826, MU +$3,995, PLTR −$1,416 then +$2,118 on a re-entry, AVGO −$714</b>. Keep the caveat attached: several were reconstructed days later from the positions API rather than logged at the fill, and two sessions disagree on AMD's exit ($408.93 vs ~$456). <b>The winning half is on the blotter now — as reconstruction, not observation.</b>"},
{c:"var(--cyan)", n:"04", h:"The benchmark — not the bot — was the least rigorous number here.", p:"An Aug 11 audit found the logged S&P series <b>re-fetched its starting level 3 times</b> instead of chaining from the prior week's close (07/24 −34.01 pts, 07/31 −5.12, 08/07 +52.09), so 'beat the S&P' was being scored against a discontinuous series. The chart now plots the re-chained series and the weekly reviews carry an errata section. Note the direction: <b>the corrected benchmark is worse for the bot</b> (across the nine weeks that carry index levels, +5.12% chained vs +3.26% as logged). It is used anyway; the build now hard-fails on any new break."},
{c:"var(--green)", n:"05", h:"Risk control is genuinely solved.", p:"80 trading days, zero rule breaches, no stop ever lowered, worst single loss −9.4%, and improving: June's exits waited for stops at −8/−9%; by Jun 15 it cut XOM on thesis break at −5.6%; GOOGL's damage was capped at −4% by the ratcheted trail. Every open position carries a live GTC trailing stop — reconciled by hand against the broker on 2026-08-11, share for share and stop for stop. Loss size shrank every month. This remains the strongest evidence for going live."},
{c:"var(--violet)", n:"06", h:"Back in band — but still one macro bet.", p:"The book is XLB + XLI + XLP + XLK at 80.1% deployed, each sized 19.6–20.6%. Rule 12 fixed the <i>quantity</i> of risk; the <i>shape</i> is unchanged — four sector ETFs, no single-name engine, which the Jul 24 review called 'the book's missing half'. XLK at least ends the zero-tech gap against the #1 momentum sector. Next binary: <b>July CPI, Wed Aug 12</b>, with 2 of 3 weekly trades still unused."}
];
