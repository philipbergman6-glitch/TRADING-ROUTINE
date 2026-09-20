# Paper-to-live broker readiness

Retrieved: **2026-09-19**. Scope: official broker and regulator documentation;
no account access, trades, policy changes, or deployment verification.

## Paper results are useful but execution differs

Alpaca's simulator omits market impact, latency slippage, queue position,
regulatory fees, and dividends. It does not constrain fill quantities to
displayed NBBO liquidity; eligible orders receive random partial fills 10% of
the time. Paper-only accounts have IEX data entitlement, while simulated fills
use NBBO. These differences matter when interpreting three months of paper
results. [Alpaca paper trading](https://docs.alpaca.markets/us/docs/paper-trading)

Recommendation (inference): preserve the existing history, reconcile it against
broker records, and report execution assumptions and dividend treatment beside
benchmark results. A later small live pilot would measure execution differences;
its existence would not establish that the strategy has an investment edge.

## Protection has operational and market limits

Alpaca documents bracket exits activating after the entry completely fills.
OTO attaches one exit, with the other bracket requirements applying. Brackets
exclude extended hours; both exits can fill before cancellation in fast markets.
Trailing stops are standalone, cannot serve as bracket/OCO legs, trigger only
during regular hours, and become market orders. Their execution price can differ
from the stop. Stop-limit orders can remain unfilled after a gap. GTC orders
are subject to cancellation after 90 days. The page inconsistently describes
replacement support: bracket replacement is supported, while the OTO section
says replacement is unsupported “like bracket orders.” Confirm the exact OTO
behavior before relying on it.
[Alpaca order documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca)

Recommendation (inference): test partial entries, stop activation, conversion,
expiry and interrupted replacement; monitor protection independently of the
research routine. A 10% trailing distance is not a guaranteed 10% maximum loss.
Size any eventual pilot against gap losses and operational failures as well as
the intended stop distance. Do not treat an accepted parent order as proof of
active protection.

## PDT migration: the repository's date has official support

Alpaca's July 6, 2026 changelog confirms removal of `daytrade_count`,
`daytrading_buying_power`, and `pattern_day_trader` from Trading API account
schemas, and `dtbp_check`/`pdt_check` from configurations.
[Alpaca removal changelog](https://docs.alpaca.markets/us/changelog/2026-07-06-pdt-db49dba)

Its production announcement says the replacement intraday-margin framework was
implemented June 4. July 6 is the API-field removal milestone, not the original
effective date. [Alpaca production announcement](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/)

FINRA states that the new rules became effective June 4, 2026, but permits firms
to transition through October 20, 2027. It also explains that sub-$2,000 margin
accounts cannot use leverage. Broker-specific requirements therefore still
matter. [FINRA explanation](https://syndication.finra.org/content/understanding-new-intraday-margin-requirements)

Alpaca's customer agreement reserves phased implementation and continued legacy
requirements for particular accounts during the transition. Its general
production announcement is consequently not a substitute for confirming the
actual live account's restrictions.
[Alpaca customer agreement, section 32](https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf)

Recommendation (inference): do not restore obsolete PDT counting as a generic
readiness requirement. Verify the intended account's current buying power,
margin configuration, restrictions, permissions and broker agreement; enforce
the project's no-leverage policy independently of buying power offered by the
broker. None of those account-specific facts were established by this research.

## Decision boundary

These sources support engineering acceptance criteria, not a recommendation to
fund an account or proof of strategy profitability. Live readiness requires
separate evidence for account configuration, deployed routines, reconciled
performance and failure recovery. This note does not change the project's
paper-only execution boundary.
