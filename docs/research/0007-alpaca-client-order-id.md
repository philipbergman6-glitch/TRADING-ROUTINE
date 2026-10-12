# 0007 — What Alpaca guarantees about `client_order_id` (uniqueness, lookup, lost responses)

Research note for Wayfinder ticket
[#98](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/98)
(parent map [#93](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/93)).
Researched 2026-10-12. Sources: Alpaca reference docs and guides
(docs.alpaca.markets, alpaca.markets/learn, alpaca.markets/support), the
official `alpacahq/alpaca-docs` and `alpacahq/alpaca-py` repos, Alpaca-staff
forum posts, plus **read-only GETs** against this repo's PAPER account
(`https://paper-api.alpaca.markets/v2`). No order was placed, cancelled or
modified.

Each claim is tagged **[DOC]** (Alpaca-published text), **[OBS]** (observed on
the paper account today), or **[INF]** (inference; could be wrong).

---

## VERDICT (up front)

`client_order_id` **is usable as a recovery index, with two caveats.**

- It is the only client-chosen key Alpaca indexes, lookups return terminal
  orders (filled / canceled) at least ~6 months back, and a duplicate POST is
  **rejected, not de-duplicated** (HTTP 422, code `40010001`,
  "client_order_id must be unique"). So "look up first, POST once, on ambiguity
  look up again" is sound: a 200 on lookup means the order exists; a 422
  duplicate on POST also means it exists.
- Caveat 1: Alpaca publishes **no** uniqueness scope, retention period, or
  read-after-write/consistency SLA. Everything in those areas below is
  observed or inferred, not guaranteed.
- Caveat 2: Alpaca's own guide scopes the duplicate rule to "another *active*
  order". Whether a canceled order frees its id is **not documented** and could
  not be tested read-only. The repo must not depend on either answer:
  **never reuse an id**; mint a fresh one per attempt and record it before
  POSTing.

---

## 1. Uniqueness scope and duplicate response

**[DOC]** Create Order reference, `client_order_id` request field: "A unique
identifier for the order. Automatically generated if not sent. (<= 128
characters)". Order object: "Each order has a unique identifier provided by the
client." The page lists only two error responses for POST /v2/orders: 403
"Buying power or shares is not sufficient" and 422 "Input parameters are not
recognized". No duplicate semantics are documented there.
— https://docs.alpaca.markets/reference/postorder

**[DOC]** Alpaca's error guide (official, alpaca.markets/learn), error 11:
"If you receive an HTTP 422 error like the one below, it likely means a
duplicate `client_order_id` was used for another active order."
Payload: `{"code":40010001,"message":"client_order_id must be unique"}`.
Fix: "Make sure to use a unique `client_order_id` for each active order."
— https://alpaca.markets/learn/how-to-fix-common-trading-api-errors-at-alpaca

**[DOC]** "Placing Orders": "Each order has a unique identifier provided by the
client. If the client does not provide one, the system will automatically
generate a client-side unique order ID." Silent on scope, reuse, duplicates.
— https://docs.alpaca.markets/docs/orders-at-alpaca

**[OBS]** The 70 orders on this paper account (2026-04-28 to 2026-10-08) have
70 distinct `client_order_id`s; auto-generated ones are 36-char UUIDs.
`GET /v2/orders:by_client_order_id` returned 200 for a **filled** id
(`en-20260928-MPC`), a **canceled** auto-id from 2026-08-11, a **canceled**
`rs-…` replacement from 2026-09-30, and a **filled** order created 2026-06-29.
So the server keeps the id → order index for terminal orders; uniqueness is
at minimum **per account across all orders currently retrievable**, i.e. not
"per open-order set" in practice for lookups.

**[INF]** Duplicate check scope. Three readings of "another active order":
(a) enforced against all stored orders (per account, effectively forever);
(b) enforced only against open orders, so a filled/canceled id can be reused;
(c) enforced for some window. Alpaca does not say which. Third-party 2026
reports conflict (some see reuse accepted after cancel completes, some see
422s during cancel-and-reprice while the old order is `pending_cancel`).
No official answer found. **Confidence: low** on (b) vs (a); treat as (a).

**[DOC]** Duplicate HTTP status: 422 (not 409). Error code `40010001` is a
generic "invalid request" code reused for many 422s (this repo already logged
it for "oto orders require stop_loss.stop_price", see research 0001), so a
recovery loop must match the **message text** "client_order_id must be
unique", not the code alone.

## 2. Lookup: `GET /v2/orders:by_client_order_id`

**[DOC]** "Retrieves a single order specified by the client order ID." One
required query param `client_order_id`. Only a 200 is documented; no 4xx body,
no retention period, no status filter. Response is a full Order with any
`OrderStatus` (new, filled, canceled, expired, replaced, …).
— https://docs.alpaca.markets/reference/getorderbyclientorderid

**[OBS]** Statuses returned today: `filled` and `canceled` (200 each). No
`expired` order exists on this account to test; **[INF]** since the endpoint
is a plain id lookup with no status filter, expired orders will return too.

**[OBS]** Retention: oldest order on the account (created 2026-04-28, account
created 2026-04-17) is still returned by `GET /v2/orders?status=closed`
and a 2026-06-29 order is still returned by id lookup. **No cutoff observed in
~5.5 months.** Alpaca publishes no retention figure. **[DOC]** The only
time-based rule is unrelated: "Alpaca implements an aged order policy that
will automatically cancel GTC orders 90 days after creation"
(https://docs.alpaca.markets/docs/orders-at-alpaca).

**[OBS]** Error bodies (paper, 2026-10-12):
| Request | HTTP | Body |
|---|---|---|
| unknown id `cl-20261012-ZZZZ-r999` | 404 | `{"code":40410000,"message":"order not found for cl-20261012-ZZZZ-r999"}` |
| param missing | 422 | `{"code":40010001,"message":"client_order_id is missing"}` |
| 129-char id | 422 | `{"code":40010001,"message":"invalid client_order_id"}` |
| `cl_2026.10.12:AMD/r3` (URL-encoded) | 404 | `order not found for cl_2026.10.12:AMD/r3` |
| unknown UUID via `/v2/orders/{id}` | 404 | `{"code":40410000,"message":"order not found for 0000…"}` |

So **404 = never existed (or outside retention)**, 422 = malformed request.
`scripts/alpaca.sh order-by-client` already maps 404 → `null`; that is the
documented-by-observation contract.

**Length / characters.** **[DOC]** Current reference: `<= 128 characters`,
type string, no character set stated
(https://docs.alpaca.markets/reference/postorder). **[DOC]** Older
Broker-API copy in the official repo says `<= 48 characters`
(https://github.com/alpacahq/alpaca-docs/blob/master/content/api-references/broker-api/trading/orders.md);
the C# SDK changelog records the raise to 128
(https://github.com/alpacahq/alpaca-trade-api-csharp/commit/b4de59f1c7af64e39f4d516520241855ee5281d8).
**[OBS]** 129 chars is rejected on lookup as "invalid client_order_id";
`_ . : /` are accepted by the lookup validator (404, not 422). **[INF]**
POST applies the same 128 limit (not tested, no POST allowed). The repo's
`cl-20261012-AMD-r3` style (18 chars, `[A-Za-z0-9-]`) is well inside both
limits; `scripts/alpaca.sh` caps at 48 and `[A-Za-z0-9-]`, which is the
stricter of the two published limits and is fine to keep.

## 3. Lost response: is a timed-out POST guaranteed visible, and how soon?

**[DOC]** Nothing. No Alpaca page documents read-after-write consistency,
an eventual-consistency window, or a visibility SLA for `GET /v2/orders` or
the by-client-id lookup. Searched: Create Order, Get Order by Client Order
ID, Get All Orders, Placing Orders, Working with /orders, Paper Trading,
Trading API `_index.md`, `llms.txt` index. The closest statements:

- **[DOC]** Error guide, 504: "check order status in Alpaca's dashboard first
  and do not blindly resend the order."
  — https://alpaca.markets/learn/how-to-fix-common-trading-api-errors-at-alpaca
- **[DOC]** Orders docs: updates "will also be sent over the streaming
  interface, which is the recommended method of maintaining order state."
  — https://docs.alpaca.markets/reference/getallorders-1
- **[DOC]** Paper trading: "your network may get disconnected and retry may be
  needed." — https://docs.alpaca.markets/docs/paper-trading

**[DOC]** Hazard in the official SDK: `alpaca-py` retries on
`DEFAULT_RETRY_EXCEPTION_CODES = [429, 504]`, 3 attempts, 3 s wait, and
`_request` does not exclude POST, so an accepted-but-504'd order is re-POSTed
with the same `client_order_id` and the second attempt surfaces as a 422
duplicate. — https://github.com/alpacahq/alpaca-py (alpaca/common/constants.py,
alpaca/common/rest.py). This repo uses curl via `scripts/alpaca.sh` (no
automatic retry), which avoids this.

**[OBS]** Community reports of lag exist (paper "new" updates taking minutes
at the open; orders vs positions endpoints briefly out of sync:
https://forum.alpaca.markets/t/slow-order-updates/6782,
https://github.com/alpacahq/Alpaca-API/issues/276) and Alpaca's status page
logged "Order processing delays" on 2026-09-30 and 5xx timeouts on 2026-10-07
(https://status.alpaca.markets/). These are not SLAs.

**[INF]** Conclusion: visibility after a lost response is **not bounded by
any published guarantee**. A recovery loop must (1) look up by
`client_order_id`; (2) on 404 treat the outcome as *unknown*, not *absent*,
until a wait budget elapses; (3) prefer re-POSTing with the **same** id over a
fresh one, because the server will answer 422 "must be unique" if the first
POST landed, which converts ambiguity into proof. The order of operations is
the same one `scripts/submit_entry.py` and `scripts/replace_stop.py` already
use; what is new is that the wait budget is a repo policy, not an Alpaca fact.

**[OBS, side finding]** `GET /v2/orders?status=all&after=2026-08-01T00:00:00Z`
returned an XLI order with `created_at` 2026-06-29 (filled 2026-09-14), while
the docs say `after` filters on "submitted after this timestamp". **[INF]**
`after` may key on `updated_at`/fill time rather than `created_at`. Low
confidence; one data point. Do not rely on `after` as a strict `created_at`
bound.

## 4. Does a cancelled order's `client_order_id` become reusable?

**[DOC]** Not documented either way. The only official text is the "another
*active* order" phrasing in the error guide (§1), which **suggests** reuse
after cancel/fill but does not state it.

**[OBS]** Cannot be tested without a POST, which this ticket forbids. What is
observable: canceled orders remain retrievable by their id indefinitely (§2),
so even if the POST validator permits reuse, the lookup endpoint would then
have two orders per id and its "single order" contract would be ambiguous.

**[INF]** Decision for the repo: **treat ids as single-use forever.** This is
safe under every reading in §1, costs nothing (ids are cheap), and keeps
`by_client_order_id` a one-to-one index. Our `rs-<old broker id>` and
`en-<date>-<sym>` schemes already satisfy this except for the same-day
re-entry case flagged in the ticket (`…-r3` retry suffix fixes that).

## 5. Rate limits a polling recovery loop would hit

**[OBS]** Every Trading API response today carried
`X-Ratelimit-Limit: 200`, `X-Ratelimit-Remaining: 199`,
`X-Ratelimit-Reset: <epoch seconds>` (paper endpoint).

**[DOC]** Official support: "the API is throttled, currently 200 requests per
minute, per account … a '429- Too Many Requests' status will be returned."
— https://alpaca.markets/support/usage-limit-api-calls
**[DOC]** Official docs repo, Trading API index: "The rate limit is 200
requests every minute per API key." 429 on exceed.
— https://github.com/alpacahq/alpaca-docs/blob/master/content/api-references/trading-api/_index.md
**[DOC]** Alpaca staff (Dan Whitnable, 2023-03-21): "All Trading API responses
include 3 rate related pieces of data in their header … `X-Ratelimit-Reset` is
the next time (in seconds epoch time) when the rate counter will reset."
— https://forum.alpaca.markets/t/executing-orders/12029
**[DOC]** Forum (2025-11-13): "default API rate limit of 200/min per account
(ie each paper and live account is separate) … Elite account … 1000/min."
Market-data subscriptions do not raise it.
— https://forum.alpaca.markets/t/is-there-a-way-to-increase-the-200-min-api-call-limit-for-the-trading-endpoint/18110
**[DOC]** 429 body reported by users: `{"code":"42910000","message":"rate
limit exceeded"}` (https://forum.alpaca.markets/t/429-rate-limit-exceeded-when-creating-orders/14120).
Note: docs.alpaca.markets currently publishes a Rate Limits page only for
Broker API (no fixed numbers, same three headers):
https://docs.alpaca.markets/us/docs/broker-api-rate-limits.

**[INF]** Budget: 200/min shared by *everything* on the paper account
(routines, dashboard, validators). A recovery loop polling one id every 2 s
uses 30/min; every 1 s uses 60/min. Recommend: poll ≤ 1/2s, read
`X-Ratelimit-Remaining` and back off when < 20, honour `X-Ratelimit-Reset` on
429, and never retry a POST on 429 without a lookup first.

---

## Repo implications (for #99)

1. Keep `order-by-client` 404 → `null` semantics; add "404 is *unknown* until
   wait budget T elapses" to the recovery policy, since Alpaca gives no
   visibility bound.
2. Match duplicate rejections on message text `client_order_id must be
   unique` (422); treat it as **proof the order exists** and resolve via
   lookup, never mint a new id in response.
3. Never reuse an id; one id per attempt (`…-r<n>`), recorded in the ledger
   before POST.
4. Keep the 48-char `[A-Za-z0-9-]` cap in `scripts/alpaca.sh` (stricter than
   the current 128 limit; `_ . : /` pass the server validator but there is
   no reason to widen).
5. Rate budget 200/min per account; recovery polling must read the
   `X-Ratelimit-*` headers.

## Open questions (not answerable read-only)

- Whether POST accepts an id equal to a *canceled* or *filled* order's id
  (§1/§4). Testable later with two paper orders on a throwaway symbol;
  out of scope here.
- Actual visibility latency after an accepted POST (§3); measurable only by
  POSTing and polling.
