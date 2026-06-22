---
description: Conviction — deep-research-driven trade decision. Scan 3 ideas, adversarially verify, output a ranked TRADE/PASS verdict. Advice-only; hands off to /trade.
---

You are running CONVICTION — an ad-hoc decision skill, NOT a scheduled routine.
Goal: produce a *reliable, auditable trade decision* that complies with the
rulebook. You do NOT place orders. You output a ranked decision and hand off to
/trade. See docs/adr/0001-decision-skill-is-advice-only.md and CONTEXT.md for
the vocabulary (Scan, Verification, Verdict, Decision).

Resolve today's date: DATE=$(date +%Y-%m-%d).

STEP 1 — Context. Read:
- memory/TRADING-STRATEGY.md (the rulebook — never violate)
- tail of memory/TRADE-LOG.md (open positions, recent exits, burned sectors)
- tail of memory/RESEARCH-LOG.md (recent ideas/decisions)
Pull live state:
- bash scripts/alpaca.sh account
- bash scripts/alpaca.sh positions
- bash scripts/alpaca.sh orders
Note: current deployment %, open position count, week trade count, daytrade_count,
and any sector you were recently stopped out of.

STEP 2 — SCAN (idea generation, lightweight). Surface exactly 3 candidate ideas
via a quick sweep. Run bash scripts/perplexity.sh "<query>" (fall back to
WebSearch on exit 3, note the fallback) for market context + catalysts, e.g.:
- "Top stock market catalysts and momentum sectors today $DATE"
- "Stocks with confirmed near-term catalysts this week $DATE"
- sector/earnings/macro queries as needed
Output: 3 candidates, each with ticker, proposed catalyst, sector, rough
entry/stop/target. Do NOT vet here — generation only.

STEP 3 — VERIFICATION (deep, citing, adversarial). Invoke the deep-research
skill (/deep-research) with a single question covering all 3 candidates:
"For each of [T1, T2, T3]: (a) confirm a specific, dated, CITED catalyst —
not vague momentum; (b) build and then try to REFUTE the bear case. Report
whether each thesis survives, with sources."
Require an evidence table and citation verification. A candidate with no cited
catalyst, or whose bear case is NOT refuted, fails gate 1.

STEP 4 — VERDICT (two gates per idea). Mark each candidate TRADE or PASS:
- GATE 1 (research): cited specific catalyst AND bear case refuted.
- GATE 2 (strategy): real catalyst (entry checklist), sector in momentum and
  NOT one you were just stopped out of, R:R >= 2:1 with stop at a real level.
TRADE only if BOTH gates pass. State the one-line reason for each verdict.

STEP 5 — DECISION. Rank the surviving TRADE candidates (best first). Note
portfolio fit briefly: avoid stacking correlated names; respect 75-85% deployed
/ 5-6 positions / max 20% each / max 3 new trades per week. Recommend the top
1-2 to execute today (leg in from cash; patience > activity). If zero survive,
the decision is HOLD — say so plainly.

STEP 6 — LOG. Write a dated entry to memory/RESEARCH-LOG.md matching the
existing format: account snapshot, the 3 candidates, per-idea VERDICT + reason +
key citation, the ranked decision, and risk factors. This entry is what the next
routine will read — write it so /pre-market can independently agree or disagree.

STEP 7 — HAND OFF. Print the ranked decision and the exact /trade command(s) for
the top pick(s), e.g. `/trade NVDA 90 buy`. Do NOT execute — the trader runs
/trade, which enforces hard rules and places the order + GTC trailing stop.
Notification: bash scripts/email.sh "<one line: decision summary>".
