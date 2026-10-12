# 0010 — Can one Alpaca login hold an isolated second paper account for drills?

Date: 2026-10-12. Wayfinder research ticket #110 (parent map #93, blocks #111).
Read-only. Sources: Alpaca primary docs (docs.alpaca.markets), first-party
Learn articles (alpaca.markets/learn), Alpaca staff forum posts (secondary,
labelled), the repo, and one read-only `GET /v2/account` call through
`scripts/alpaca.sh` to inspect the payload shape (identifiers redacted).

Legend: **[DOC]** official docs.alpaca.markets · **[LEARN]** first-party
alpaca.markets/learn · **[FORUM]** Alpaca staff on forum.alpaca.markets ·
**[OBS]** observed in this repo / live payload · **[INF]** my inference.

## Short answer

Yes. One Alpaca login can hold up to three paper accounts, each with its own
key pair, all served from the same `paper-api.alpaca.markets` host. Nothing in
any Trading API payload says "paper" or names which paper account answered;
isolation is by key only. A drill profile is therefore a secrets-and-wrapper
problem, not an Alpaca-features problem. The three Active "E2BOT" routines of
unknown account are a real risk to this plan and must be identified before a
drill account is created.

## Findings

### 1. Multiple paper accounts per login

- **[DOC]** "We've updated the dashboard to allow you to create and delete
  paper accounts, rather than resetting them." Create: "click the paper account
  number in the upper left corner of the dashboard and select 'Open New Paper
  Account.'" Delete: paper account number → "Account Settings" → "Delete
  Account". — https://docs.alpaca.markets/us/docs/paper-trading
- **[DOC]** OAuth page corroborates multi-account: "For users with multiple
  paper accounts, the user must go through the authorization flow separately
  for each account they want to connect." —
  https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api
- **[LEARN]** Limit: "Paper Trading allows up to 3 distinct simulated accounts
  with separate balances and positions." —
  https://alpaca.markets/learn/start-paper-trading
- **[FORUM]** Staff (Dan_Whitnable_Alpaca, 2025-11-07): "Each owner is
  currently allowed 3 paper accounts and 1 live account." —
  https://forum.alpaca.markets/t/feature-request-more-paper-trading-accounts/18125
- **[FORUM]** Staff (2025-03-24): at least one paper account must remain. —
  https://forum.alpaca.markets/t/disappearance-of-paper-trading-account/16522
- Not found: a numeric cap on docs.alpaca.markets itself. The "3" comes from
  Learn + staff posts only.
- Not found: any Trading API endpoint to create, delete, or reset a paper
  account. Dashboard only (HITL step in #111).

### 2. Key scoping

- **[DOC]** "If you have more than one account … each of those have separate
  credentials." and "you cannot use your live account's credentials with the
  paper API, or vice versa." — https://docs.alpaca.markets/us/docs/authentication
- **[DOC]** "Don't forget to generate new API keys for any newly created
  account." — https://docs.alpaca.markets/us/docs/paper-trading
- **[LEARN]** "Generating new keys invalidates the existing key pair." Paper
  keys "often begin with a `PK...` prefix" — described as a visual hint, not a
  security boundary. —
  https://alpaca.markets/learn/api-key-security-best-practices-for-alpaca-builders
- Not found: named keys, per-key permissions, or read-only keys for the retail
  Trading API. Access controls (Read only / Full / Custom) are documented for
  **Broker API** credentials only —
  https://docs.alpaca.markets/us/docs/credential-management
- **[INF]** A key pair is therefore the only handle on a specific paper
  account. Whichever pair is in `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` decides
  which account every call hits.

### 3. Paper account reset

- **[DOC]** The reset button is gone; the flow is now delete + create
  ("rather than resetting them"). The same page still carries the stale line
  "You can reset the paper trading account at any time later with arbitrary
  amount as you configure." — internally contradictory; treat the
  create/delete text as current. — https://docs.alpaca.markets/us/docs/paper-trading
- **[DOC, legacy]** Old reset semantics in Alpaca's docs repo: "the trading
  history of the paper trading account is wiped out, and a new paper trading
  account is created … Please make sure to re-generate the API key as the old
  key is associated with your old paper trading account" —
  https://github.com/alpacahq/alpaca-docs/blob/master/content/trading/paper-trading.md
- **[FORUM]** Staff: creating "will create a new account with new API keys and
  no transactions, positions, or orders"; deleted accounts stay inactive and
  "if you still have the keys you can access them." — forum thread 16522 above.
- **[INF]** A "reset" is a new account: new `id`, new `account_number`, new
  keys, empty history. Any stored identifying fields and secrets go stale on
  every reset. Not stated explicitly in current docs.

### 4. Starting equity

- **[DOC]** "Your initial paper trading account is created with $100k balance
  as a default setting." "You cannot change the account balance after it is
  created, unless you reset it." — https://docs.alpaca.markets/us/docs/paper-trading
- **[FORUM]** Staff (2025-10-14): "The paper account equity cannot be changed.
  You will need to create a new paper account each day with a starting equity
  of $100k." — https://forum.alpaca.markets/t/paper-trading-balance/17970
- Not found: a documented range or option list for "Open New Paper Account".
  **[INF]** Expect $100,000 fixed; the "arbitrary amount" line is legacy.
- **[OBS]** Production paper account was created 2026-04-17 with one $100,000
  JNLC deposit (research 0006), consistent with the default.

### 5. Does any Trading API payload identify the account or paper vs live?

- **[DOC]** `GET /v2/account` schema fields: `id` ("Account Id."),
  `account_number` ("Account number."), `status`, `currency`, `cash`,
  `equity`, `buying_power`, `created_at`, … No field marks paper vs live or
  which paper account. The only paper/live distinction on the page is the
  servers list: Paper `https://paper-api.alpaca.markets`, Live
  `https://api.alpaca.markets`. — https://docs.alpaca.markets/us/reference/getaccount-1
- **[DOC]** "The API spec is the same between the paper trading and live
  accounts." — https://docs.alpaca.markets/us/docs/paper-trading
- **[OBS]** Read-only `bash scripts/alpaca.sh account` on 2026-10-12 returned
  40 fields; the only identifying ones are `id` (36-char UUID) and
  `account_number` (12 chars). No `paper`, `env`, or `account_name` field.
  `status` was `ACTIVE`, not `PAPER_ONLY`. Values redacted here.
- **[INF]** Caveats, not documented facts: the docs' `AccountStatus` enum lists
  `PAPER_ONLY` but never defines it; example `account_number`s like
  `PALPACA_123` suggest a `PA` prefix convention. Neither is a reliable guard.
- **Conclusion:** the only in-payload discriminator between the production
  paper account and a drill paper account is `id`/`account_number`. The
  wrapper must compare against a pinned expected value; nothing in the
  response will otherwise reveal a key mix-up.

### 6. Endpoint and headers

- **[DOC]** Both environments use `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`
  headers; only the host differs. — https://docs.alpaca.markets/us/docs/authentication
- **[OBS]** `scripts/alpaca.sh:17-25` hard-pins `ALPACA_ENDPOINT` to
  `https://paper-api.alpaca.markets/v2` and `scripts/heartbeat.py:91-93`
  checks the same prefix. A drill account changes neither; the paper guard
  stays exactly as is and provides zero isolation between paper accounts.

## What a drill-account profile would need (repo)

Observed credential surface:

- `env.template` — one pair: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, plus the
  two endpoints.
- `scripts/_env.sh` — fills unset vars from `.env`; process env wins.
- `scripts/alpaca.sh:27-31` — reads the pair into headers; every other script
  (`validate_order.py`, `validate_mutation.py`, `replace_stop.py`,
  `close_position.py`, `deployment_status.py`, `build_oto_order.py`) shells
  out to `alpaca.sh`, so one choke point.
- `scripts/heartbeat.py:94` — reads the pair directly (second surface).
- `.github/workflows/heartbeat.yml:27-29`, `protection-monitor.yml:30-33` —
  `secrets.ALPACA_API_KEY` / `secrets.ALPACA_SECRET_KEY`.
- `routines/*.md:7-8` — cloud routines are told the pair is already in process
  env under the same names.

Needed for #111 (**[INF]**, design sketch, not implemented):

1. Separately named secrets: `DRILL_ALPACA_API_KEY`, `DRILL_ALPACA_SECRET_KEY`.
   Never reuse the `ALPACA_*` names for the drill pair.
2. A selector in `alpaca.sh` (`ALPACA_PROFILE=drill` or `--account drill`)
   that maps profile → key pair and **hard-fails** if both `ALPACA_API_KEY`
   and `DRILL_ALPACA_API_KEY` are set in one invocation, or if the profile is
   unrecognised. Default profile stays production so existing routines are
   unchanged.
3. Account pinning: store the drill account's `account_number` (and
   production's) in `docs/` or a small `scripts/accounts.json`; on every
   invocation, or at least before any mutating subcommand, `GET /v2/account`
   and refuse if `account_number` does not match the selected profile. This
   is the only in-band check Alpaca gives us (finding 5).
4. Mirror the same selector in `heartbeat.py` or restrict it to production
   explicitly.
5. Cloud: drill runs must receive only `DRILL_*` secrets; production routines
   must not have `DRILL_*` in their environment. Document in `routines/README.md`.
6. Drill resets are delete+create, which rotates keys and `account_number`
   (finding 3). The pinned value and secrets must be updated together; a
   stale pin should fail loudly, which item 3 provides.

## Risk flag: the E2BOT routines

`docs/ROUTINE-VERIFICATION.md:27-30`: "The three E2BOT routines are also marked
Active, but no E2BOT reference exists in this repository's current tracked
contents. Their attached repository, account and relationship to Trading
Routine remain unknown. Do not assume they share a broker account or
execution engine based on this screenshot."

Consequences for an isolated drill account:

- **[INF]** If E2BOT holds a copy of the production paper keys, it can trade
  the production account regardless of this repo's drill isolation.
- **[INF]** If a drill account is created and its keys are pasted into the
  same secret store or Claude cloud environment the E2BOT routines read, the
  drill account would also be driven by an unknown agent, and drill results
  would be contaminated. Conversely, if E2BOT is given the drill keys, a drill
  "account" is not isolated at all.
- **[INF]** Because no payload identifies the account (finding 5), E2BOT fills
  would be indistinguishable from drill fills except by reconciling against
  this repo's ledger/logs.
- Mitigation before #111: identify the E2BOT routines' repo and env (owner
  action in the cloud dashboard), confirm which key pair they carry, and
  either retire them or document them. Keep the 3-account cap in mind: if
  E2BOT uses a second paper account, only one slot remains for a drill.

## Open questions

- Exact current UI for "Open New Paper Account": whether any starting-cash
  input remains (docs say no; one stale line says yes). Resolve in #111 by
  looking at the dashboard.
- Whether `status: PAPER_ONLY` is ever returned for retail paper accounts.
- What the E2BOT routines are attached to.
