# Does an open GTC trailing stop reserve shares, blocking a validated sell?

Research note for Wayfinder ticket
[#33](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/33).
Researched 2026-08-11. Primary sources only (Alpaca reference docs, Alpaca
official `alpaca-py` SDK source) plus a live empirical test against this repo's
PAPER account (`https://paper-api.alpaca.markets/v2`).

Companion to `0001-alpaca-atomic-entry-plus-protective-stop.md`, which
established that rule 4's trailing stop cannot be a bracket leg — so it must be
a *standalone open sell order*. This note establishes what that standalone
order costs you.

---

## VERDICT (all three questions, up front)

1. **Yes. The reservation is real, exact, and currently total.** Every share
   backing an open sell order is unavailable. All four production positions on
   this account report `qty_available: "0"` right now.
2. **`Position` must gain `qty_available`, and `_validate_sell` must check
   against it, not `qty`.** Today the engine approves sells the broker refuses
   with HTTP 403 — verified end-to-end, not inferred.
3. **The correct sequence is cancel-the-stop-then-sell.** "Sell only what is
   free" works but is a no-op for this bot, because rule 4 mandates a
   full-size stop, so nothing is ever free. `alpaca.sh close SYM` is **not** a
   way around this — it fails with the same 403.

And one finding nobody asked for, which is worse than any of the above:

4. **`routines/midday.md` has the two commands in the wrong order, and the
   rule-5 "cut losers at -7%" path is broken in production today.** It closes
   *then* cancels. The close 403s; the cancel succeeds. Net result: the loser
   is still held **and** its protective stop is gone. See "Consequence 3".

---

## Q1 — Does the reservation exist? (directly observed)

### The live production account, read-only

`bash scripts/alpaca.sh positions`, 2026-08-11 19:54 UTC. All four positions
carry a full-size GTC trailing stop placed by the bot:

```
XLB qty=412 qty_available=0
XLI qty=116 qty_available=0
XLK qty=112 qty_available=0
XLP qty=250 qty_available=0
```

`bash scripts/alpaca.sh orders open` — the matching orders:

```
934ca71d XLK trailing_stop qty=112 trail_percent=10 gtc status=new  created 2026-08-10T13:47:48Z
c2159960 XLP trailing_stop qty=250 trail_percent=10 gtc status=new  created 2026-06-30T13:34:30Z
8cda2f73 XLB trailing_stop qty=412 trail_percent=10 gtc status=new  created 2026-06-29T13:38:26Z
108d5958 XLI trailing_stop qty=116 trail_percent=10 gtc status=new  created 2026-06-29T13:38:25Z
```

Every stop is sized to the full position. Every position reports **zero**
available. The ticket's hypothesis — "plausibly zero for every position this
bot holds" — is not plausible, it is the observed state of all four.

### Alpaca's own definition

`https://docs.alpaca.markets/reference/getallopenpositions` and
`https://docs.alpaca.markets/reference/getopenposition-1`, response schema,
verbatim:

> `qty` — "The number of shares"

> `qty_available` — "Total number of shares available minus open orders / locked for options covered call"

The official SDK says the same. `alpaca-py`, `alpaca/trading/models.py`,
`Position` docstring, verbatim:

> `qty (str): The number of shares of the position.`

> `qty_available (Optional[str]): Total number of shares available minus open orders.`

Note the phrase is **"minus open orders"** — not "minus open sell orders", not
"minus trailing stops". Alpaca draws no distinction by order type or
time-in-force anywhere in its documentation (see "What the docs do NOT say").

### Controlled test: the reservation is linear and exact

Ticker `F` (Ford, ~$13.97, liquid, deliberately not one of XLK/XLP/XLB/XLI),
3 shares, PAPER, 2026-08-11 19:54-19:55 UTC.

**Baseline — position with no open sell order:**

```
POST /v2/orders {"symbol":"F","qty":"3","side":"buy","type":"market","time_in_force":"day"}
HTTP 200 -> 74bd81ce, filled 3 @ 13.97

GET /v2/positions/F
{"symbol":"F","qty":"3","qty_available":"3","avg_entry_price":"13.97",...}
```

**Full-size trailing stop — availability drops to zero:**

```
POST /v2/orders {"symbol":"F","qty":"3","side":"sell","type":"trailing_stop",
                 "time_in_force":"gtc","trail_percent":"10"}
HTTP 200 -> fe46998e  status=new  trail_percent=10  stop_price=12.5685  hwm=13.965

GET /v2/positions/F
{"symbol":"F","qty":"3","qty_available":"0",...}
```

**Partial-size trailing stop (2 of 3) — availability is exactly the remainder:**

```
DELETE /v2/orders/fe46998e -> HTTP 204
POST /v2/orders {"symbol":"F","qty":"2","side":"sell","type":"trailing_stop",
                 "time_in_force":"gtc","trail_percent":"10"}
HTTP 200 -> da7ed71f

GET /v2/positions/F
{"symbol":"F","qty":"3","qty_available":"1",...}
```

Observed: `qty_available == qty - (open sell order qty)`. 3-3=0, 3-2=1. Exact,
immediate (readable within ~2s of order acceptance), no rounding, no partial
credit for a stop that is far out of the money. **The stop being 10% away from
the market and having essentially no chance of triggering today buys you
nothing — the reservation is on the order's quantity, not on its likelihood of
filling.**

## Q2 — Is a partial sell against a fully-reserved position rejected? (directly observed)

**Rejected. HTTP 403.** With the 3-share position fully reserved by the
3-share trailing stop, a market sell for a *single* share:

```
POST /v2/orders {"symbol":"F","qty":"1","side":"sell","type":"market","time_in_force":"day"}

HTTP 403
{"available":"0",
 "code":40310000,
 "existing_qty":"3",
 "held_for_orders":"3",
 "message":"insufficient qty available for order (requested: 1, available: 0)",
 "related_orders":["fe46998e-bb31-49a5-9266-8e5d99d84363"],
 "symbol":"F"}
```

Three things worth noting in that payload:

- `held_for_orders: "3"` — Alpaca names the mechanism explicitly. This field
  is **not** present on the position payload; it appears only in the error.
- `related_orders` names the exact order responsible. This is a gift for
  error handling: the remediation target is handed to you.
- `existing_qty: "3"` vs `available: "0"` — the broker itself distinguishes
  held from available. The engine currently does not.

**And the converse — selling what is free is accepted.** With the 2-share stop
open (`qty_available: "1"`):

```
POST /v2/orders {"symbol":"F","qty":"1","side":"sell","type":"market","time_in_force":"day"}
HTTP 200 -> b45a3690  status=pending_new -> filled 1 @ 13.95
```

So the rule is simply: `requested_qty <= qty_available` or 403. There is no
special case for partials, no "reduce the stop automatically", no netting.

### `close SYM` is not an escape hatch — verified

This is the most operationally important test in the note, because
`routines/midday.md:41` is built on it. With a 2-share position and a 2-share
trailing stop open (`qty_available: "0"`):

```
DELETE /v2/positions/F

HTTP 403
{"available":"0","code":40310000,"existing_qty":"2","held_for_orders":"2",
 "message":"insufficient qty available for order (requested: 2, available: 0)",
 "symbol":"F"}
```

Confirmed immediately afterwards that the trailing stop `da7ed71f` was still
`status=new` and the position still existed at `qty=2`. **`DELETE
/v2/positions/{symbol}` does not cancel the position's open orders. It is
liquidation-by-market-order under the hood, and it is subject to the identical
availability check.** The docs are silent on this
(`https://docs.alpaca.markets/reference/deleteopenposition-1` says only
*"Closes (liquidates) the account's open position for the given symbol. Works
for both long and short positions."* — no mention of orders at all), so this is
an empirical finding, but an unambiguous one.

Cancel-then-close works, and works immediately:

```
DELETE /v2/orders/da7ed71f -> HTTP 204
DELETE /v2/positions/F     -> HTTP 200, order 42df3f27, filled 2 @ 13.95
GET    /v2/positions/F     -> HTTP 404 {"code":40410000,"message":"position does not exist"}
```

No sleep or retry was needed between the cancel and the close; they were
issued ~1s apart and the second succeeded. **I would still not build on that
timing** — one observation on a paper account is not a latency guarantee, and
a cancel is a request to cancel, not a cancellation. See "Open questions".

### The one documented escape hatch — and we do not expose it

`https://docs.alpaca.markets/us/reference/deleteallopenpositions-1`
(`DELETE /v2/positions`), verbatim:

> `cancel_orders` — "If true is specified, cancel all open orders before liquidating all positions."

That flag exists **only** on close-*all*. There is no `cancel_orders` on the
single-symbol endpoint, and no equivalent on `ClosePositionRequest` in
`alpaca-py` (whose only fields are `qty` and `percentage`). `scripts/alpaca.sh`'s
`close-all` subcommand does not pass the parameter, so even the blunt version
is unavailable to us today. Not tested live — exercising close-all on this
account would liquidate the four production positions.

## Q3 — What is the correct sequence?

**Cancel the protective stop, then sell.** Not "sell only what is free".

The two candidate designs the ticket names are not equally viable, and the
reason is rule 4 rather than anything about Alpaca:

- **"Sell only what is free"** is mechanically sound — proven above, the
  1-share sell against `qty_available: "1"` filled. But rule 4 requires *every*
  position to carry a full-size trailing stop, so `qty_available` is
  structurally `0` for every position this bot holds. The strategy that makes
  the shares safe is the same strategy that makes them unsellable. A
  "sell what is free" engine would refuse 100% of real sells. **It is not a
  design option; it is a description of the deadlock.**
- **Cancel-then-sell** is the only sequence that can execute a rule-5 exit.

For a *partial* sell (trimming a position, which rule 3b sizing could call
for), the sequence has three steps, because the remaining shares must not be
left naked:

1. Cancel the full-size stop (or `PATCH` it down — untested, see below).
2. Submit the sell for the intended quantity.
3. Place a new full-size trailing stop for the **remaining** quantity.

Between steps 1 and 3 the position is unprotected. That window is unavoidable
given `0001`'s finding that a trailing stop cannot be an atomic bracket leg,
and it is the same class of exposure `0001` identified on entry. **The window
is real and should be named in whatever ADR settles this, not papered over.**

For a *full* exit, steps 1 and 2 suffice and step 3 does not apply.

---

## What this means for the map

### Consequence 1 — `Position` gains `qty_available`; `_validate_sell` uses it

`risk_engine/engine.py:146` today (the ticket cites 147; the line is 146):

```python
    if proposal.qty > held.qty:
```

`held.qty` is the wrong number. It is the number the broker calls
`existing_qty` in the very payload where it refuses the order. The check must
be against `qty_available`.

`scripts/validate_order.py:112-116` constructs `Position` from three fields and
drops the rest:

```python
            Position(
                symbol=p["symbol"],
                qty=str(p["qty"]),
                market_value=str(p["market_value"]),
            )
```

The field is present in the payload and thrown away one line before it would
have been useful.

This is not a hypothetical mis-validation. **Given all four positions are at
`qty_available: "0"`, the engine would currently APPROVE a sell of any size up
to the full position on any of them, and the broker would refuse every one of
them with 403.** That is precisely the "APPROVED order that fails at
submission" failure mode issue #19 exists to eliminate, and it is live right
now, not latent.

Whether the resulting refusal is a `Violation` (recorded in the ledger, per
#21's "a disallowed account state is a `Violation`") or a raise is a design
call for the implementing ticket. I lean `Violation`: a sell blocked by the
bot's own stop is an ordinary, expected, recoverable state that the ledger
should record — not incoherent input. But #21's principle also says incoherent
*data* raises, and `qty_available > qty` would be incoherent data and should
raise.

### Consequence 2 — the sell path needs a cancel step, and it must be ordered correctly

Whatever object ends up binding validation to execution (the map's open
question about whether `validate_order.py` survives) cannot model a sell as a
single POST. A validated sell of a protected position is inherently a
**sequence**, and the intermediate state is a position with no stop. That has
implications for the ledger schema — #23 already found the ledger "cannot
express the protective stop as an addressable order", and this note makes that
gap sharper: the sell path needs to *cancel a specific order id* and record
that it did.

Helpfully, Alpaca hands you the id: `related_orders` in the 403 body.

### Consequence 3 — `routines/midday.md` rule-5 exit is broken in production, today

`routines/midday.md:39-42` (identical text at `.claude/commands/midday.md:17-20`):

```
STEP 3 — Cut losers immediately. For every position where
unrealized_plpc <= -0.07:
bash scripts/alpaca.sh close SYM
bash scripts/alpaca.sh cancel ORDER_ID   # cancel its trailing stop
```

The two commands are **in the wrong order**. Given every position on this
account is at `qty_available: "0"`, executing this as written produces:

1. `close SYM` -> **HTTP 403**, nothing sold, position still open.
2. `cancel ORDER_ID` -> **HTTP 204**, protective stop destroyed.

**Terminal state: the losing position is still held, and it is now
unprotected.** The routine intended to cut a loser instead strips its only
protection and leaves it running. This is strictly worse than doing nothing,
and it is the exact inversion of the routine's purpose.

Two things make this worse than a simple ordering bug:

- `scripts/alpaca.sh` uses `curl -fsS`, which **suppresses the response body on
  HTTP errors**. An agent running this routine sees a bare
  `curl: (22) ... error: 403` on stderr, not
  `insufficient qty available for order`. The diagnostic that explains the
  failure is discarded by our own wrapper. (I worked around this for these
  tests with a scratchpad `curl` shim — see "Empirical test hygiene".)
- The failure is silent to the operator: `routines/market-open.md:64-65` only
  emails *if* a trade was placed (*"Notification: only if a trade was
  placed"*), and this path places no trade.

I have **no evidence this has ever fired** — no position on this account has
hit -7%, and I did not audit `memory/TRADE-LOG.md` for historical -7% exits.
But it is armed. **This deserves its own ticket and it should not wait for the
engine work.** The fix in the routine is a two-line swap (cancel, then close);
the fix in the engine is Consequence 1.

The same latent problem exists in `.claude/commands/trade.md:36`, which posts a
bare market sell with no cancel step at all — a `/trade SYM N sell` against any
currently-held position will 403.

### Consequence 4 — a rejected stop now has a second way to hurt you

#37 already notes that `unprotected_orders()` counts a broker-**rejected** stop
as protection. This note adds the mirror image: because the engine reads `qty`
rather than `qty_available`, it cannot tell a protected position from an
unprotected one *at all*. `qty_available < qty` is, in fact, a usable
independent signal that a real reserving sell order exists — weaker than
reading the order itself (it cannot tell you the stop is at 10% rather than
40%, or that it is a limit sell rather than a stop), but it is a cheap
cross-check that comes free on a payload the system already fetches.

---

## What the docs do NOT say (stated plainly)

Alpaca's documentation is much thinner here than the behaviour warrants. The
following are **empirical findings only**, from one paper account on one day:

- **There is no doc sentence stating that open sell orders hold shares.** The
  entire documented basis is the schema gloss "minus open orders" on
  `qty_available`. Alpaca never writes a sentence about it in prose.
- **The equity error string
  `insufficient qty available for order (requested: X, available: Y)` appears
  nowhere on docs.alpaca.markets.** Error code `40310000` is documented only on
  the *options* overview page, and only with the covered-call variant of the
  message. There is no error-codes reference page —
  `https://docs.alpaca.markets/docs/error-codes` is a 404. Do not string-match
  this message; match on `code == 40310000` and read `available`.
- **`held_for_orders` and `related_orders` are undocumented fields.** They are
  useful and I would use them, but with a fallback, since nothing commits
  Alpaca to keeping them.
- **No documented distinction between GTC and DAY, or between trailing-stop
  and plain stop/limit, in hold behaviour.** I tested only GTC trailing stops
  (plus, in `0001`, `day` bracket legs). **I don't know** whether a DAY sell
  releases its hold at session end or at cancellation — I did not test it, and
  it does not matter for this bot, whose stops are all GTC by rule 4.
- **No documented statement that you must cancel a protective order before
  selling.** The requirement is real (proven above) and entirely undocumented.
- **`DELETE /v2/positions/{symbol}` is documented without any mention of open
  orders.** Its 403-on-reserved behaviour is empirical only.

## Open questions this note did not settle

- **Can `PATCH /v2/orders/{id}` resize a trailing stop downward, and does the
  released quantity become available immediately?** If yes, a partial trim
  becomes replace-then-sell with a *smaller* unprotected window (the position
  keeps a stop over the shares it retains) rather than cancel-then-sell. This
  is strictly better than the three-step sequence in Q3 and would change the
  recommended design. **I did not test it** — the market closed at 20:00 UTC
  mid-investigation. Worth a ticket; it is a 5-minute paper test.
- **Is the cancel -> sell transition guaranteed synchronous?** Observed to work
  at ~1s separation, once. Whether a cancel can be `pending_cancel` long enough
  for a following sell to 403 is unknown, and it determines whether the sell
  path needs a poll-until-released loop. **I don't know.**
- **Does `DELETE /v2/positions?cancel_orders=true` cancel orders for *all*
  symbols or only those being liquidated?** The doc says "cancel all open
  orders", which reads as global. Not tested — untestable safely on this
  account.
- **What is `qty_available` during a partial fill of the stop itself?** Not
  observed; a trailing stop that partially fills is plausible on an illiquid
  name.

## Empirical test hygiene

All tests ran against the PAPER endpoint only; `scripts/alpaca.sh`'s paper
guard (lines 17-21) was in force throughout and every call went through the
wrapper — no direct curl to the trading API.

One deviation, disclosed: `scripts/alpaca.sh` calls `curl -fsS`, which
suppresses response bodies on 4xx, and the 403 bodies are the whole point of
this note. Rather than edit the checked-in script, I put a `curl` shim on
`PATH` in the session scratchpad that strips `-f` and appends
`-w '<<HTTP %{http_code}>>'`, leaving every line of `alpaca.sh` — including the
paper guard and the endpoint resolution — untouched and executing normally.
The shim lives outside the repo and is not part of this branch. Separately, I
read `GET /v2/clock` with a direct curl because the wrapper has no `clock`
subcommand; that was a read-only call and is the only direct API call I made.

Test instrument: ticker `F`, 3 shares maximum, ~$42 notional.

**Everything opened was unwound:**

- Cancelled: `fe46998e` (3-share F trailing stop), `da7ed71f` (2-share F
  trailing stop). Both `status=canceled`, `filled_qty=0`.
- Closed: the 3-share F position — 1 share via market sell `b45a3690`, 2 shares
  via `DELETE /v2/positions/F` order `42df3f27`. Bought 3 @ 13.97, sold 3 @
  13.95. Realised P&L: **-$0.06**.

**Final verified state**, re-read after the unwind:

```
GET /v2/positions/F -> HTTP 404 {"code":40410000,"message":"position does not exist"}

GET /v2/positions
XLB qty=412 qty_available=0
XLI qty=116 qty_available=0
XLK qty=112 qty_available=0
XLP qty=250 qty_available=0

GET /v2/orders?status=open
934ca71d XLK trailing_stop 112 trail=10 new  created 2026-08-10T13:47:48.266728Z
c2159960 XLP trailing_stop 250 trail=10 new  created 2026-06-30T13:34:30.926384Z
8cda2f73 XLB trailing_stop 412 trail=10 new  created 2026-06-29T13:38:26.414919Z
108d5958 XLI trailing_stop 116 trail=10 new  created 2026-06-29T13:38:25.951866Z
```

**The four production trailing stops were never cancelled, replaced, modified
or read-modified.** Their `created_at` timestamps are unchanged from before the
test (2026-06-29, 2026-06-30, 2026-08-10), their quantities still match their
positions exactly, and all four are still `status=new` with `trail_percent=10`.
Every call touching XLK/XLP/XLB/XLI in this investigation was a GET.

No orders remain open other than those four. No options were involved at any
point.

## Sources

- https://docs.alpaca.markets/reference/getallopenpositions — `qty_available` definition
- https://docs.alpaca.markets/reference/getopenposition-1 — same schema, single position
- https://docs.alpaca.markets/reference/deleteopenposition-1 — close position; silent on open orders
- https://docs.alpaca.markets/us/reference/deleteallopenpositions-1 — `cancel_orders` parameter
- https://docs.alpaca.markets/us/docs/orders-at-alpaca — GTC semantics, trailing stops, buying-power holds
- https://docs.alpaca.markets/us/docs/options-trading-overview — the only documented home of error code `40310000`
- https://raw.githubusercontent.com/alpacahq/alpaca-py/master/alpaca/trading/models.py — official SDK `Position` docstring
- https://raw.githubusercontent.com/alpacahq/alpaca-py/master/alpaca/trading/requests.py — `ClosePositionRequest`
- Live PAPER API `https://paper-api.alpaca.markets/v2`, 2026-08-11 19:54-19:56 UTC

Dead URLs encountered, recorded so the next session does not re-chase them (all
404): `/docs/positions`, `/docs/error-codes`, `/docs/trailing-stop-orders`,
`/reference/getopenposition`, `/reference/deleteopenposition`,
`/reference/deleteallopenpositions`. Current paths use the `-1` suffix and/or
the `/us/` prefix.

No blog posts, forum threads, or third-party write-ups were used as evidence.
Where the only attestation for a string was a community forum or a GitHub
issue tracker, it is recorded above as **undocumented** rather than cited.

---

## Bottom line for the map

**The reservation is real and total, so `Position` must carry `qty_available`
and `_validate_sell` must check against it. Every sell this engine approves
today would be refused by the broker with HTTP 403.**

Three follow-ons, in priority order:

1. **Urgent, independent of the engine:** fix the command order in
   `routines/midday.md:41-42` and `.claude/commands/midday.md:19-20`. As
   written, the rule-5 exit strips a losing position's stop and fails to sell
   it. Two-line swap. Do not let this wait behind the engine work.
2. **Engine:** `Position` gains `qty_available`; `_validate_sell` compares
   against it; `read_portfolio` stops dropping it; a blocked sell becomes a
   `Violation` so the ledger records the refusal, per #21's principle.
3. **Execution interface:** a validated sell of a protected position is a
   *sequence* (cancel, sell, optionally re-protect), not a POST. This bears
   directly on the map's open question of whether `validate_order.py` survives
   as a public entry point, and on #23's finding that the ledger cannot address
   the protective stop as an order. Settle in an ADR alongside `0001`'s
   entry-side window — they are the same problem at the two ends of a trade.

Worth testing before that ADR is written: whether `PATCH /v2/orders/{id}` can
resize a trailing stop and release shares. If it can, the unprotected window on
a partial trim shrinks to nothing, and the ADR should say so.
