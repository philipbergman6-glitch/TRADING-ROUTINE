# Can entry + protective stop be one atomic Alpaca call?

Research note for Wayfinder ticket
[#22](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/22).
Researched 2026-08-11. Primary sources only (Alpaca docs, Alpaca SDK reference,
Alpaca changelog) plus a live empirical test against this repo's PAPER account
(`PA38JXAA3CY1`, `https://paper-api.alpaca.markets/v2`).

Location note: this repo had no `docs/research/` convention before; it has
`docs/adr/` for decisions. This is a research note, not a decision, so it gets
its own numbered file under `docs/research/`. Decisions that follow from it
belong in `docs/adr/`.

---

## VERDICT ON Q2 FIRST (the one the map hinges on)

**No. A trailing stop cannot be the protective leg of a bracket or OTO order.
The API hard-rejects it, and — worse — one specific malformed spelling is
accepted and silently downgraded to a fixed stop.**

This is not an inference. Both the docs and the live API say it.

Docs (`docs.alpaca.markets/us/docs/orders-at-alpaca`, page updated 2026-08-10),
verbatim:

> "Trailing stop orders are currently supported only with single orders.
> However, we plan to support trailing stop as the stop loss leg of bracket/OCO
> orders in the future."

Live PAPER API, verbatim request and response (2026-08-11 19:29 UTC):

```
POST /v2/orders
{"symbol":"F","qty":"1","side":"buy","type":"market","time_in_force":"day",
 "order_class":"oto","stop_loss":{"trail_percent":"10"}}

HTTP 422
{"code":40010001,"message":"oto orders require stop_loss.stop_price"}
```

```
POST /v2/orders
{"symbol":"F","qty":"1","side":"buy","type":"market","time_in_force":"day",
 "order_class":"bracket","take_profit":{"limit_price":"20.00"},
 "stop_loss":{"trail_percent":"10"}}

HTTP 422
{"code":40010001,"message":"bracket orders require stop_loss.stop_price"}
```

Same 422 for `stop_loss:{"trail_price":"1.00"}` and for
`stop_loss:{"type":"trailing_stop","trail_percent":"10"}`. There is no spelling
of "trailing protective leg" that the API accepts.

**The dangerous case — silent downgrade.** If you send *both* `stop_price` and
`trail_percent` in `stop_loss`, the order is **accepted** and `trail_percent`
is **silently discarded**:

```
POST /v2/orders
{"symbol":"F","qty":"1","side":"buy","type":"market","time_in_force":"day",
 "order_class":"oto","stop_loss":{"stop_price":"12.58","trail_percent":"10"}}

HTTP 200 -> parent ee1d89ad (filled), leg d439a79c:
  "type":"stop", "stop_price":"12.58", "trail_percent":null, "trail_price":null
```

Observed fact: `trail_percent` came back `null` on the leg. A caller that
assumed "I asked for a trail, I got a fill, therefore I have a trailing stop"
would be running a **fixed** stop that never ratchets — a direct violation of
strategy rule 4 ("10% trailing stop on every position as a real GTC order") that
produces no error anywhere. Any implementation MUST NOT send a trail field
inside `stop_loss` on the assumption it will either work or fail loudly.

Corroborating primary source — the official Python SDK reference
(`alpaca.markets/sdks/python/api_reference/trading/requests.html`):

> `class alpaca.trading.requests.StopLossRequest(*, stop_price: float, limit_price: float | None = None)`

`stop_price` is required; there is no `trail_price` or `trail_percent` field on
`StopLossRequest` at all. Trail fields live only on `TrailingStopOrderRequest`,
which is a standalone-order request type.

### What the docs do NOT say (stated plainly, per the ticket's ask)

- They do not give a date, changelog entry, or roadmap item for when trailing
  legs will ship. "in the future" is the entire commitment.
- They do not document the silent-downgrade behaviour when `stop_price` and
  `trail_percent` are both supplied. That is an empirical finding only, from
  one account on one day. Treat it as real but unversioned — it could change.
- They do not mention OTO in that sentence (it says "bracket/OCO"), but the
  live API rejects it for OTO too, so the restriction is broader than the
  sentence.

---

## Q1 — Does `oto` / `bracket` place entry + protective leg in one atomic request?

**Yes.** One POST, one request, and either everything is created or nothing is.

Docs, verbatim:

> "A bracket order is a chain of three orders that can be used to manage your
> position entry and exit. It is a common use case of an OTOCO (One Triggers OCO
> {One Cancels Other}) order."

> "OTO (One-Triggers-Other) is a variant of bracket order. It takes one of the
> take-profit or stop-loss order in addition to the entry order. For example, if
> you want to set only a stop-loss order attached to the position, without a
> take-profit, you may want to consider OTO orders. The order submission is done
> with the order_class parameter be 'oto'."

> "In order to submit a bracket order, you need to supply additional parameters
> to the API. First, add a parameter order_class as 'bracket'. Second, give two
> additional fields take_profit and stop_loss both of which are nested JSON
> objects. ... the stop_loss object needs a mandatory stop_price field and
> optional limit_price field. If limit_price is specified in stop_loss, the
> stop-loss order is queued as a stop-limit order, but otherwise it is queued as
> a stop order."

> "The second and third orders won't be active until the first order is
> completely filled."

Empirically confirmed on PAPER: a single POST returned a parent with a populated
`legs[]` array in the same response body, entry `pending_new` and leg `held`:

```
parent d3c28d7e status=pending_new   leg 44683c0c status=held  (type=stop, stop_price=9)
```

Atomicity on the failure side is also confirmed: an OTO whose entry exceeded
buying power was refused up front with **no orders created at all** —

```
POST .../orders  qty=1000000 order_class=oto
HTTP 403
{"buying_power":"323561.7","code":40310000,"cost_basis":"13980003","message":"insufficient buying power"}
```

A subsequent `GET /v2/orders?status=all` showed no orphan leg from that request.
So: no half-created state. **This is the real win over the current two-call
flow** — today's `market-open` routine can fill an entry and then fail to place
the stop, leaving a naked position. `oto` removes that window.

Caveat (observed): "atomic" means *creation* is atomic. The protective leg is
`held` and does not become live until the entry is **completely** filled — see
Q3.

## Q3 — What happens to the leg on reject / partial fill / cancel?

**Rejected entry:** nothing is created. Validation and buying-power failures
return 4xx before any order object exists (see the 403 above). Observed.

**Cancelled entry:** the leg is cancelled automatically. Docs, verbatim:

> "If any one of the orders is canceled, any remaining open order in the group
> is canceled."

Empirically confirmed — cancelling the parent auto-cancelled the child 1s later:

```
DELETE /v2/orders/d3c28d7e...  -> HTTP 204
GET    /v2/orders/44683c0c...  -> {"status":"canceled",
                                   "canceled_at":"2026-08-11T19:30:07.028Z",
                                   "type":"stop","stop_price":"9"}
```

**Partially filled entry:** the docs are explicit that activation requires a
*complete* fill —

> "The second and third orders won't be active until the first order is
> completely filled."

The only partial-fill rule the docs state is about the **exit** legs, not the
entry:

> "If the take-profit order is partially filled, the stop-loss order will be
> adjusted to the remaining quantity."

**I don't know** what the terminal behaviour is when a bracket/OTO entry is
partially filled and then expires or is done-for-day — i.e. whether the leg
resizes to the partial quantity and activates, or is cancelled leaving a
partially-filled position unprotected. The docs do not say, and I could not
force a partial fill on 1 share of a liquid name without placing a large order.
**This is a real gap and it matters**: a partially-filled `day` market entry
that leaves an unprotected position is exactly the failure the bot is trying to
eliminate. Do not assume the leg covers it. (Mitigating factor: a `market` +
`day` entry on a liquid name filling completely and instantly is the
overwhelmingly common case — but "overwhelmingly common" is not "always".)

Also relevant, docs verbatim:

> "Each order in the group is always sent with a DNR/DNC (Do Not Reduce/Do Not
> Cancel) instruction. Therefore, the order price will not be adjusted and the
> order will not be canceled in the event of a dividend or other corporate
> action."

Inference (flagged as such): with DNR/DNC, a bracket stop leg will NOT be
adjusted for a dividend or split, whereas a standalone GTC trailing stop is
subject to corporate-action price adjustment. For a long-held position across an
ex-div date this is a behavioural difference the bot would inherit.

## Q4 — Does PDT rejection behave differently for a bracket?

**The question is moot as of 2026: PDT no longer exists at Alpaca.**

This is the biggest surprise of the investigation and it invalidates live logic
in this repo.

Alpaca changelog `docs.alpaca.markets/us/changelog/2026-06-03-pdt-651df23`
(dated 2026-06-03) deprecates the entire PDT surface, **removed on 2026-07-06**,
including on the Trading API account object: `daytrade_count`,
`daytrading_buying_power`, and `pattern_day_trader`, plus the `pdt_check` /
`dtbp_check` account configurations and the PDT status/removal endpoints.
Background: `docs.alpaca.markets/us/docs/understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt`
— FINRA replaced Rule 4210's pattern-day-trader framework with an intraday
margin regime; the round-trip count and the $25k day-trading minimum are gone.

Empirically confirmed against this very account today — `GET /v2/account`
returns **no** `pattern_day_trader`, **no** `daytrade_count`, **no**
`daytrading_buying_power` field. Those keys are simply absent from the response.

So: there is no PDT rejection to compare between the two flows, for brackets or
anything else. The replacement blocking mechanism is the Intraday Margin
Deficit / margin-call regime, which is an account-level end-of-day or
real-time-monitoring construct, not a per-order class-specific rejection. **I
have no primary-source evidence that IMD treats bracket and two-call flows
differently, and I did not test it** (this account is at ~$106k equity with
4x multiplier, so no deficit could be provoked safely).

**Action for the map, independent of ticket #22:** `routines/market-open.md`
lines 47 and 56-59 are now dead logic. Line 47 gates on
`daytrade_count leaves room (PDT: 3/5 rolling business days)` against a field
that no longer exists; lines 56-59 define a PDT-error fallback path
("fall back to fixed stop", "queue the stop in TRADE-LOG as PDT-blocked") that
can never trigger. `memory/TRADING-STRATEGY.md:10` ("PDT limit: not a
constraint (account >= $25k)") is right by accident for the wrong reason. Left
as-is, a routine reading `daytrade_count` from the account JSON will read
`None` and either crash or silently skip its own guard.

## Q5 — Restrictions that would rule it out for `market` + `day` entries?

**None that block the intended use.** `market` + `day` + whole shares works.
But three restrictions do bite elsewhere. All verified live, all 1-share tests:

| Restriction | Result | Evidence |
|---|---|---|
| `market` + `day`, qty 1 | **accepted, filled** | order `ee1d89ad` |
| `market` + `gtc`, qty 1 | **accepted, filled** | order `30db8964` |
| `time_in_force: ioc` | **422** | `{"code":40010001,"message":"oto orders support only \"day\" or \"gtc\" time_in_force"}` |
| `time_in_force: opg` | **422** | same message |
| `extended_hours: true` | **403** | `{"code":40310000,"message":"oto orders do not support extended hours trading"}` |
| fractional `qty: "1.5"` | **422** | `{"code":42210000,"message":"fractional orders must be simple orders"}` |
| `notional: "20"` | **422** | `{"code":42210000,"message":"fractional orders must be simple orders"}` |
| stop too close to base price | **422** | `{"base_price":"10","code":42210000,"message":"stop_loss.stop_price must be <= base_price - 0.01"}` |

Docs corroborate the first three, verbatim:

> "Extended hours are not supported. extended_hours must be 'false' or omitted."
> "time_in_force must be day or gtc."

And on the stop-price threshold, verbatim:

> "For the stop-loss order leg of advanced orders, please be aware the order
> request can be rejected because of the restriction of the stop_price parameter
> value. The stop price input has to be at least $0.01 below (for stop-loss
> sell, above for buy) than the 'base price'. The base price is determined as
> follows. It is the limit price of the take-profit, for OCO orders. It is the
> limit price of the entry order, for bracket or OTO orders if the entry type is
> limit. It is also the current market price for any, of OCO, OTO and bracket."

Note the base price is the **entry limit price** for a limit entry — confirmed
live: with `limit_price: 10.00` the API reported `base_price: "10"`, not the
~$13.98 market price. For a `market` entry the base is the current market price.
The repo's own "never within 3% of current price" rule is stricter than
Alpaca's $0.01, so this threshold will not bind in practice.

**Fractional is the one that could bite.** The current sizing path must not hand
a fractional or notional quantity to an OTO/bracket call; it will 422. Whole
shares only.

---

## What this means for the map

1. **Ticket #22's headline answer is: atomic entry+stop is available, but not
   with a trailing stop.** You can have atomicity OR a trailing protective leg,
   not both. Strategy rule 4 mandates a *trailing* stop, so `oto` cannot replace
   the current flow as-is.
2. The realistic options are (a) keep the two-call flow (entry, then standalone
   `trailing_stop` GTC) and accept the gap, (b) use `oto` with a **fixed** stop
   at entry as a safety net and then replace it with a trailing stop once
   filled — closing the naked-position window at the cost of one extra
   round-trip and a brief non-trailing period, or (c) wait for Alpaca to ship
   trailing legs, with no date on offer. Choosing between these is an ADR, not
   this note.
3. **Guard against the silent downgrade.** If any code ever constructs a
   `stop_loss` object, it must be asserted to contain `stop_price` and to
   contain no trail fields. A dropped `trail_percent` is invisible.
4. **Unrelated but urgent: strip the dead PDT logic** from
   `routines/market-open.md`. Those fields were removed from the API on
   2026-07-06.

## Empirical test hygiene

All tests ran against the PAPER endpoint only; `scripts/alpaca.sh`'s paper guard
(lines 17-21) was in force, and the account number `PA38JXAA3CY1` confirms a
paper account. Ticker F, 1 share per test. Everything opened was unwound:

- Cancelled: `c1ceb938` (unfilled trailing-stop entry + its `held` leg),
  `d439a79c` and `3e44b9be` (two active stop legs from filled test entries).
- Closed: the 2-share F position created by the two filled test entries.
- **Final verified state:** `GET /v2/positions/F` -> `HTTP 404
  {"code":40410000,"message":"position does not exist"}`. `GET
  /v2/orders?status=open` -> only the four pre-existing production trailing
  stops (XLK, XLP, XLB, XLI), none touched. Net P&L impact of the test was
  a few cents.

## Sources

- https://docs.alpaca.markets/us/docs/orders-at-alpaca (page updated 2026-08-10) — primary, all order-class quotes
- https://alpaca.markets/sdks/python/api_reference/trading/requests.html — official Python SDK reference, `StopLossRequest` signature
- https://docs.alpaca.markets/us/changelog/2026-06-03-pdt-651df23 — PDT/DTBP deprecation, removal 2026-07-06
- https://docs.alpaca.markets/us/docs/understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt — replacement regime
- https://docs.alpaca.markets/us/docs/user-protection (page dated 2026-07-07) — wash-trade handling; contains no PDT content
- Live PAPER API `https://paper-api.alpaca.markets/v2`, account `PA38JXAA3CY1`, 2026-08-11 19:28-19:31 UTC

No blog posts, forum threads, or third-party write-ups were used as evidence.
No "unconfirmed signal" sources were needed — every question except the
partial-fill edge case in Q3 and the IMD comparison in Q4 was answerable from
primary sources plus direct API observation.
