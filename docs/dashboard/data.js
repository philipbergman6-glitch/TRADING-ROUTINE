// ============ DATA — origin/main, latest log 2026-10-28 ============

// Two independent dates. LOG_ASOF moves nightly with the trade log;
// ANALYSIS_ASOF only moves when a human rewrites the editorial prose.
// The dashboard shows both, so curated text can never pass as live.
const LOG_ASOF = "2026-10-28";
const ANALYSIS_ASOF = "2026-10-15";

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
{d:"2026-08-18",n:80,v:105887.25,cash:19.9,dp:-0.77,note:""},
{d:"2026-08-19",n:81,v:106022.45,cash:19.9,dp:0.13,note:""},
{d:"2026-08-20",n:82,v:105371.69,cash:20.0,dp:-0.61,note:""},
{d:"2026-08-21",n:83,v:106071.03,cash:19.9,dp:0.66,note:""},
{d:"2026-08-24",n:84,v:105952.51,cash:19.9,dp:-0.11,note:""},
{d:"2026-08-25",n:85,v:105829.57,cash:19.9,dp:-0.12,note:""},
{d:"2026-08-26",n:86,v:106248.71,cash:19.8,dp:0.40,note:""},
{d:"2026-08-27",n:87,v:106141.21,cash:19.9,dp:-0.10,note:""},
{d:"2026-08-28",n:88,v:105684.55,cash:19.9,dp:-0.43,note:""},
{d:"2026-08-31",n:89,v:105229.19,cash:20.0,dp:-0.43,note:""},
{d:"2026-09-01",n:90,v:104481.99,cash:20.2,dp:-0.71,note:""},
{d:"2026-09-02",n:91,v:104878.91,cash:20.1,dp:0.38,note:""},
{d:"2026-09-03",n:92,v:105169.41,cash:20.0,dp:0.28,note:""},
{d:"2026-09-04",n:93,v:105132.29,cash:20.0,dp:-0.04,note:""},
{d:"2026-09-07",n:94,v:105132.29,cash:20.0,dp:0,note:""},
{d:"2026-09-08",n:95,v:104753.77,cash:20.1,dp:-0.36,note:""},
{d:"2026-09-09",n:96,v:103998.63,cash:20.3,dp:-0.72,note:""},
{d:"2026-09-10",n:97,v:103289.39,cash:20.4,dp:-0.68,note:""},
{d:"2026-09-11",n:98,v:103925.69,cash:20.3,dp:0.62,note:""},
{d:"2026-09-14",n:99,v:103176.77,cash:39.4,dp:-0.72,note:"XLI stop fires: −$1,575 after 77 days"},
{d:"2026-09-15",n:100,v:103071.25,cash:39.4,dp:-0.10,note:""},
{d:"2026-09-16",n:101,v:102827.45,cash:39.5,dp:-0.24,note:""},
{d:"2026-09-17",n:102,v:103631.88,cash:20.0,dp:0.78,note:"XLE bought — energy sleeve opened"},
{d:"2026-09-18",n:103,v:103282.35,cash:20.1,dp:-0.34,note:""},
{d:"2026-09-21",n:105,v:102959.64,cash:20.1,dp:-0.31,note:""},
{d:"2026-09-22",n:106,v:103477.27,cash:20.1,dp:0.50,note:""},
{d:"2026-09-23",n:107,v:103339.91,cash:20.1,dp:-0.13,note:""},
{d:"2026-09-24",n:108,v:102896.62,cash:20.2,dp:-0.43,note:""},
{d:"2026-09-25",n:109,v:103093.11,cash:20.1,dp:0.19,note:""},
{d:"2026-09-28",n:110,v:102720.45,cash:15.2,dp:-0.36,note:"MPC bought — first single name since GOOGL (rule 14)"},
{d:"2026-09-29",n:111,v:102329.13,cash:15.2,dp:-0.38,note:""},
{d:"2026-09-30",n:112,v:101934.29,cash:35.0,dp:-0.39,note:"XLB stop fires: −$948 after 93 days"},
{d:"2026-10-01",n:113,v:102909.79,cash:34.7,dp:0.96,note:""},
{d:"2026-10-02",n:114,v:103268.31,cash:20.0,dp:0.35,note:"PSX bought — second refiner"},
{d:"2026-10-05",n:115,v:104115.94,cash:19.8,dp:0.82,note:""},
{d:"2026-10-06",n:116,v:104530.87,cash:19.7,dp:0.40,note:""},
{d:"2026-10-07",n:117,v:104538.19,cash:19.7,dp:0.01,note:""},
{d:"2026-10-08",n:118,v:105990.39,cash:19.5,dp:1.39,note:""},
{d:"2026-10-09",n:119,v:105778.92,cash:19.5,dp:-0.20,note:""},
{d:"2026-10-12",n:120,v:106269.74,cash:19.4,dp:0.46,note:""},
{d:"2026-10-13",n:121,v:107397.51,cash:19.2,dp:1.06,note:"STRATEGY_VERSION unset: market-open halts at the version gate"},
{d:"2026-10-14",n:122,v:107650.97,cash:19.2,dp:0.24,note:""},
{d:"2026-10-15",n:123,v:106854.43,cash:19.3,dp:-0.74,note:""},
{d:"2026-10-16",n:124,v:107225.88,cash:38.4,dp:0.33,note:""},
{d:"2026-10-19",n:125,v:106292.25,cash:20.3,dp:-0.82,note:""},
{d:"2026-10-20",n:126,v:106043.69,cash:26.1,dp:-0.21,note:""},
{d:"2026-10-21",n:127,v:106625.98,cash:25.9,dp:0.56,note:""},
{d:"2026-10-22",n:128,v:104734.41,cash:33.3,dp:-1.77,note:""},
{d:"2026-10-23",n:129,v:105550.90,cash:19.9,dp:0.78,note:""},
{d:"2026-10-26",n:130,v:106067.08,cash:19.8,dp:0.49,note:""},
{d:"2026-10-27",n:131,v:104697.61,cash:34.7,dp:-1.29,note:""},
{d:"2026-10-28",n:132,v:104869.29,cash:34.6,dp:0.16,note:""}
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
{w:"08/14", bot:0.42, spx:0.53, spxc:0.53, est:0},
{w:"08/21", bot:-0.94, spx:-1.90, spxc:-2.07, est:0},
{w:"08/28", bot:-0.36, spx:0.64, spxc:1.12, est:0},
{w:"09/04", bot:-0.52, spx:0.03, spxc:0.03, est:0},
{w:"09/11", bot:-1.15, spx:-0.90, spxc:-0.90, est:0},
{w:"09/18", bot:-0.62, spx:-0.38, spxc:-0.38, est:0},
{w:"09/25", bot:-0.18, spx:1.20, spxc:1.20, est:0},
{w:"10/02", bot:0.17, spx:0.03, spxc:0.03, est:0},
{w:"10/09", bot:2.43, spx:0.91, spxc:0.91, est:0},
{w:"10/16", bot:1.37, spx:-1.71, spxc:-1.71, est:0},
{w:"10/23", bot:-1.56, spx:-0.47, spxc:-0.47, est:0}
];

const BOOK = [ // Oct 28 EOD
{s:"SLB", q:277, in:50.08, pl:1016.59, plp:7.33, stop:49.14, protection:"trailing", w:14.2},
{s:"TMO", q:15, in:696.57, pl:113.70, plp:1.09, stop:639.729, protection:"trailing", w:10.1},
{s:"XLE", q:311, in:63.92, pl:1417.61, plp:7.13, stop:62.874, protection:"trailing", w:20.3},
{s:"XLP", q:250, in:83.76, pl:860.00, plp:4.11, stop:80.991, protection:"trailing", w:20.8}
];

// Run records (ADR 0012), from state/events.jsonl: machine-written by every
// routine and protection-monitor run, reconciled, never curated. Runs started
// before LOG_ASOF only. Runs before `since` (or all runs, while it is null)
// are unprovenanced: no record of code, rulebook, prompt or model exists and
// none is backfilled.
const RUNS = {"outcomes": {"actions": 7, "incident": 8, "no-trade": 26, "refused": 24}, "recent": [{"dirty": false, "e": "2026-10-27T22:52:58+00:00", "m": "not-applicable", "n": {"a": 0, "i": 0, "in": 0, "r": 1}, "o": "refused", "r": "protection-monitor", "rb": "v1.3", "run": "protection-monitor-20261027T225256Z-9779eb", "s": "2026-10-27T22:52:56+00:00", "sha": "55ff290", "t": "schedule"}, {"dirty": false, "e": "2026-10-27T20:12:57+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "daily-summary", "rb": "v1.3", "run": "daily-summary-20261027T201206Z-efb78f", "s": "2026-10-27T20:12:06+00:00", "sha": "a2018d9", "t": "cloud"}, {"dirty": false, "e": "2026-10-27T18:36:07+00:00", "m": "not-applicable", "n": {"a": 0, "i": 0, "in": 0, "r": 1}, "o": "refused", "r": "protection-monitor", "rb": "v1.3", "run": "protection-monitor-20261027T183603Z-917e46", "s": "2026-10-27T18:36:03+00:00", "sha": "9cd8bd2", "t": "schedule"}, {"dirty": false, "e": "2026-10-27T17:07:42+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "midday", "rb": "v1.3", "run": "midday-20261027T170622Z-946f23", "s": "2026-10-27T17:06:22+00:00", "sha": "3cfea88", "t": "cloud"}, {"dirty": false, "e": "2026-10-27T13:35:48+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "market-open", "rb": "v1.3", "run": "market-open-20261027T133513Z-deab41", "s": "2026-10-27T13:35:13+00:00", "sha": "f026fa5", "t": "cloud"}, {"dirty": false, "e": "2026-10-27T11:34:34+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "pre-market", "rb": "v1.3", "run": "pre-market-20261027T113314Z-82eb46", "s": "2026-10-27T11:33:14+00:00", "sha": "c739cda", "t": "cloud"}, {"dirty": false, "e": "2026-10-26T23:15:43+00:00", "m": "not-applicable", "n": {"a": 0, "i": 0, "in": 0, "r": 1}, "o": "refused", "r": "protection-monitor", "rb": "v1.3", "run": "protection-monitor-20261026T231542Z-2f6b6a", "s": "2026-10-26T23:15:42+00:00", "sha": "29a691b", "t": "schedule"}, {"dirty": false, "e": "2026-10-26T20:11:22+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 1, "in": 0, "r": 0}, "o": "incident", "r": "daily-summary", "rb": "v1.3", "run": "daily-summary-20261026T201025Z-30ee8d", "s": "2026-10-26T20:10:25+00:00", "sha": "f84908f", "t": "cloud"}, {"dirty": false, "e": "2026-10-26T19:04:52+00:00", "m": "not-applicable", "n": {"a": 0, "i": 0, "in": 0, "r": 1}, "o": "refused", "r": "protection-monitor", "rb": "v1.3", "run": "protection-monitor-20261026T190450Z-0b6daf", "s": "2026-10-26T19:04:50+00:00", "sha": "3d1e3a0", "t": "schedule"}, {"dirty": false, "e": "2026-10-26T17:06:34+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "midday", "rb": "v1.3", "run": "midday-20261026T170551Z-7c4527", "s": "2026-10-26T17:05:51+00:00", "sha": "408bf2d", "t": "cloud"}, {"dirty": false, "e": "2026-10-26T13:42:40+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "market-open", "rb": "v1.3", "run": "market-open-20261026T134151Z-64f2b4", "s": "2026-10-26T13:41:51+00:00", "sha": "3b9a820", "t": "cloud"}, {"dirty": false, "e": "2026-10-26T11:34:38+00:00", "m": "claude-opus-5-5", "n": {"a": 0, "i": 0, "in": 0, "r": 0}, "o": "no-trade", "r": "pre-market", "rb": "v1.3", "run": "pre-market-20261026T113316Z-1390b0", "s": "2026-10-26T11:33:16+00:00", "sha": "bdb1042", "t": "cloud"}], "since": "2026-10-12", "through": "2026-10-27", "total": 65, "unfinished": 0};

// Trade blotter from memory/BLOTTER.json (scripts/blotter.py --json: broker
// fills, FIFO). Open lots first, newest entry first; then closed round trips,
// newest exit first. Test symbols excluded: ['F'].
const TRADES = [
{"d": "2026-10-23", "s": "SLB", "sec": "enrg", "lbl": "ENERGY", "q": 277, "in": "50.08", "out": null, "days": 5, "pl": null, "plp": null, "open": 1},
{"d": "2026-10-22", "s": "TMO", "sec": "oth", "lbl": "HEALTH CARE", "q": 15, "in": "696.57", "out": null, "days": 6, "pl": null, "plp": null, "open": 1},
{"d": "2026-09-17", "s": "XLE", "sec": "etf", "lbl": "ENERGY ETF", "q": 311, "in": "63.92", "out": null, "days": 41, "pl": null, "plp": null, "open": 1},
{"d": "2026-06-30", "s": "XLP", "sec": "etf", "lbl": "STAPLES ETF", "q": 250, "in": "83.76", "out": null, "days": 120, "pl": null, "plp": null, "open": 1},
{"d": "2026-10-02", "s": "PSX", "sec": "enrg", "lbl": "ENERGY", "q": 57, "in": "264.20", "out": "2026-10-27 · 269.18", "days": 25, "pl": {"v": "+283.86", "up": 1}, "plp": "+1.88", "open": 0},
{"d": "2026-10-19", "s": "GEV", "sec": "oth", "lbl": "INDUSTRIALS", "q": 21, "in": "930.12", "out": "2026-10-22 · 839.37", "days": 3, "pl": {"v": "−1,905.75", "up": 0}, "plp": "−9.76", "open": 0},
{"d": "2026-09-28", "s": "MPC", "sec": "enrg", "lbl": "ENERGY", "q": 13, "in": "396.33", "out": "2026-10-20 · 468.37", "days": 22, "pl": {"v": "+936.52", "up": 1}, "plp": "+18.18", "open": 0},
{"d": "2026-08-10", "s": "XLK", "sec": "etf", "lbl": "TECH ETF", "q": 112, "in": "187.85", "out": "2026-10-16 · 182.90", "days": 67, "pl": {"v": "−554.40", "up": 0}, "plp": "−2.64", "open": 0},
{"d": "2026-06-29", "s": "XLB", "sec": "etf", "lbl": "MATERIALS ETF", "q": 412, "in": "51.07", "out": "2026-09-30 · 48.77", "days": 93, "pl": {"v": "−947.79", "up": 0}, "plp": "−4.50", "open": 0},
{"d": "2026-06-29", "s": "XLI", "sec": "etf", "lbl": "INDUSTRIALS ETF", "q": 116, "in": "182.16", "out": "2026-09-14 · 168.58", "days": 77, "pl": {"v": "−1,575.36", "up": 0}, "plp": "−7.46", "open": 0},
{"d": "2026-06-25", "s": "GOOGL", "sec": "tech", "lbl": "COMMS", "q": 62, "in": "336.36", "out": "2026-07-23 · 322.93", "days": 28, "pl": {"v": "−832.73", "up": 0}, "plp": "−3.99", "open": 0},
{"d": "2026-06-25", "s": "XLF", "sec": "etf", "lbl": "FINANCIALS ETF", "q": 390, "in": "53.97", "out": "2026-06-29 · 53.83", "days": 4, "pl": {"v": "−52.85", "up": 0}, "plp": "−0.25", "open": 0},
{"d": "2026-06-10", "s": "XOM", "sec": "enrg", "lbl": "ENERGY", "q": 142, "in": "150.14", "out": "2026-06-15 · 141.74", "days": 5, "pl": {"v": "−1,192.80", "up": 0}, "plp": "−5.59", "open": 0},
{"d": "2026-06-03", "s": "MSFT", "sec": "tech", "lbl": "TECH", "q": 48, "in": "436.20", "out": "2026-06-09 · 401.09", "days": 6, "pl": {"v": "−1,685.28", "up": 0}, "plp": "−8.05", "open": 0},
{"d": "2026-06-03", "s": "NVDA", "sec": "tech", "lbl": "TECH", "q": 90, "in": "219.64", "out": "2026-06-09 · 199.37", "days": 6, "pl": {"v": "−1,823.96", "up": 0}, "plp": "−9.23", "open": 0},
{"d": "2026-05-26", "s": "MU", "sec": "tech", "lbl": "TECH", "q": 25, "in": "853.58", "out": "2026-06-04 · 1013.36", "days": 9, "pl": {"v": "+3,994.50", "up": 1}, "plp": "+18.72", "open": 0},
{"d": "2026-05-27", "s": "AVGO", "sec": "tech", "lbl": "TECH", "q": 40, "in": "427.95", "out": "2026-06-04 · 410.09", "days": 8, "pl": {"v": "−714.57", "up": 0}, "plp": "−4.17", "open": 0},
{"d": "2026-05-07", "s": "PLTR", "sec": "tech", "lbl": "TECH", "q": 152, "in": "136.96", "out": "2026-06-02 · 152.21", "days": 26, "pl": {"v": "+2,317.64", "up": 1}, "plp": "+11.13", "open": 0},
{"d": "2026-05-07", "s": "XOM", "sec": "enrg", "lbl": "ENERGY", "q": 140, "in": "145.94", "out": "2026-05-27 · 146.62", "days": 20, "pl": {"v": "+95.21", "up": 1}, "plp": "+0.47", "open": 0},
{"d": "2026-04-28", "s": "NVDA", "sec": "tech", "lbl": "TECH", "q": 90, "in": "208.64", "out": "2026-05-26 · 212.71", "days": 28, "pl": {"v": "+366.30", "up": 1}, "plp": "+1.95", "open": 0},
{"d": "2026-05-21", "s": "WMT", "sec": "oth", "lbl": "STAPLES", "q": 175, "in": "122.44", "out": "2026-05-21 · 122.38", "days": 0, "pl": {"v": "−11.43", "up": 0}, "plp": "−0.05", "open": 0},
{"d": "2026-05-07", "s": "AMD", "sec": "tech", "lbl": "TECH", "q": 49, "in": "414.16", "out": "2026-05-18 · 421.44", "days": 11, "pl": {"v": "+356.86", "up": 1}, "plp": "+1.76", "open": 0},
{"d": "2026-04-28", "s": "AMD", "sec": "tech", "lbl": "TECH", "q": 62, "in": "314.97", "out": "2026-05-06 · 408.93", "days": 8, "pl": {"v": "+5,825.49", "up": 1}, "plp": "+29.83", "open": 0},
{"d": "2026-04-28", "s": "PLTR", "sec": "tech", "lbl": "TECH", "q": 142, "in": "142.30", "out": "2026-05-06 · 132.33", "days": 8, "pl": {"v": "−1,415.78", "up": 0}, "plp": "−7.01", "open": 0}
];

// ============ Curated: hand-written, dated by ANALYSIS_ASOF ============

// Commentary as of 2026-10-15; not a live safety certification.
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

const RULES = [{"ok": "?", "c": "warn", "t": "Logged protection", "v": "4 trailing / 0 fixed; broker status unverified"}, {"ok": "?", "c": "warn", "t": "Historical rule compliance", "v": "not independently verified"}, {"ok": "!", "c": "warn", "t": "Logged deployment", "v": "65.4% as of 2026-10-28"}];

const RISK = [
{t:"Evidence", v:"Fills reconciled to equity to the cent at 2026-09-18 (research 0006); blotter rebuilt from broker fills each EOD", c:"up"},
{t:"Execution", v:"Every mutation under the coordinator lease with intent recovery (ADR 0010) since 2026-10-13", c:"up"},
{t:"Benchmark", v:"Some weeks estimated; see comparison labels", c:"warn"}
];
