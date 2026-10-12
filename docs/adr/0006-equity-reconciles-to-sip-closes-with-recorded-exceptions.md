# 0006. Daily equity reconciles to SIP closes, with recorded exceptions

Date: 2026-10-12. Status: accepted.

Research 0006 reconciled the paper account by hand once. To make that a daily
check (`scripts/reconcile_equity.py`, pure logic in `risk_engine/accounting.py`)
three choices had to be made, each verified against the full account history
(122 sessions, 2026-04-17 to 2026-10-09).

1. **Cash and holdings reconcile to the cent, with no tolerance.** Every
   cash-moving activity (FILL, FEE, JNLC, and the dividend/interest/transfer
   types Alpaca documents) is summed and must equal `/account` cash; signed fill
   quantities must equal `/positions`. No price is involved, so any difference
   is a missing or unknown activity. Activity types this module does not know,
   and quantity-moving ones (JNLS, splits, reorganisations), are rejected rather
   than ignored.
2. **Past sessions are priced at the SIP daily close, tolerance $1.** Broker
   portfolio-history equity equals cash plus held lots at the consolidated
   (SIP) close on 119 of 122 sessions to the cent; IEX closes miss by $6 median
   and up to $100, so IEX is not used even though it is the live quote feed.
   Alpaca serves SIP bars only for data older than 15 minutes, so today's
   session is checked through cash and holdings only and the close check
   follows a session later. $1 absorbs fractional-cent price rounding and
   nothing else.
3. **Explained differences live in `memory/RECONCILIATION-EXCEPTIONS.json`,
   keyed by session, with the observed diff and a reason.** The three
   historical misses (2026-05-04, 2026-06-02, 2026-07-29) are broker 1D
   snapshot artefacts: the neighbouring sessions reconcile to the cent and one
   repeats the prior day's equity verbatim. A session is explained only while
   the live diff still matches the recorded one, so an exception cannot mask a
   new problem. Anything else beyond tolerance is UNEXPLAINED and the script
   exits 4, which stops `daily-summary` before it writes the EOD snapshot.

Considered and rejected: widening the tolerance to cover the three misses
(hides real $800 gaps); reconciling only the latest session (loses the proof
that cash flows explain the whole history); committing the daily output
(the check is reproducible from broker data, so the verdict in the EOD email
and the trade-log notes is enough).
