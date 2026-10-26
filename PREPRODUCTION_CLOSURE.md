# Spot + Futures preproduction: fixed closure scope

Updated 25 October 2026. Baseline: main `7b64fd6407432f3cccec4edb1be99e41fa55133b`,
0.10.53. This document describes the 0.10.54 candidate, not installed proof.

The owner authorized developing segregated LIVE support and preparing a real
account connection. The owner reports having no dedicated LIVE API keys.
100 USD is a proposed total starting budget, not a USDT allocation or approval
of losses, leverage, wallet splits or production activation. Earlier percentage
profiles remain proposals. No authorization or readiness record is provisioned.

## Finite acceptance matrix

| Package | Implemented in this candidate | Outstanding acceptance |
| --- | --- | --- |
| 1. Evidence | One supervised, bounded cohort collector; read-only source snapshots; durable contemporaneous proposal receipts; legacy audit; material fingerprints | Financially qualified evidence must prove reconciliation, costs, cashflows and protections. Local uptime alone cannot certify 30 days. Legacy evidence is not erased or automatically restarted. |
| 2. Account | Fixed-host signed GET-only LIVE auditor, bounded pagination/resumption, encrypted raw retention; dedicated Windows-user credential vault | Dedicated keys, identity/permissions verification and complete baseline/history reconciliation. No account was connected during development. |
| 3. Common execution | Exact proposal/reservation/claim/transport grant; one submission, then GET reconciliation; UNKNOWN retains reserves | Commissioned adapters from actual strategy proposals and complete account facts into this protocol. Current operating Testnet brokers remain unchanged. |
| 4. Risk/capital | Integer-unit transactional capital, stop risk, persistent day/week/drawdown state, idempotence, concurrency and segregated wallet envelopes | Owner-approved numeric policy and operational admission integration. AI cannot issue an authority or change limits. |
| 5. LIVE commissioning | Separate fixed hosts, ledgers, kill paths, native-protection workflow, partial/unknown recovery, prepared signed-update capability | Complete supervised strategy adapters, end-to-end commissioning/recovery evidence and separate owner activation. TradingEngine explicitly refuses uncommissioned LIVE before creating a wallet. |

New sources, cosmetic improvements and additional engines do not add conditions
to this initial Spot/Futures acceptance scope. Pulse/Quant remain SHADOW. Passing
30 calendar days does not itself issue permission; valid historical evidence
must be assessed using its actual coverage and retained methodology.

## Authority and durable recovery

Dedicated credentials are protected by Windows DPAPI for the current user;
configuration accepts hidden local input, never secret command-line arguments
or a portal form. Keys are not reused from Testnet. Vault possession grants no
trading permission. `configure_live_connection.py` performs no network call.
`audit_live_account.py --ack-read-only --vault ...` can subsequently read an
explicit production scope. Neither command writes an activation record.

Local authorization consumes separate purpose-bound DPAPI records, exact reviewed
policies, bounded HMAC permits, retained evidence and a commissioned adapter
capability. This release contains no approval/activation issuer. LIVE mode cannot
fall through to PaperBroker. Real exits are not dependent on an IA/Guardian
request; native protection remains at the exchange. No transfer or withdrawal
endpoint, leverage-setting endpoint or automatic capital redistribution exists.

Wallet budgets are statically segregated under a common approved envelope;
Spot/Futures balances are not added or netted. The same wallet must use the same
transactional admission ledger. Unknown submission state never releases capital
on timeout or permits a blind resend. Code rollback in a future LIVE scope must
not restore an older financial database over fills that occurred at Binance.
Existing Testnet rollback semantics are preserved.

The installation-wide engine lock stays shared across modes while financial
ledgers are separate. The prepared manifest capability is not a LIVE mode or
activation flag. Publication still follows PR, Windows/Linux CI, current-main
OIDC signing, Ed25519 verification, antirollback and supervised installation.

## Institutional context for Market Pulse

The five existing RSS providers remain separate. Two additional institutional
connectors do not consume new model calls or change quantitative score weights:

* **CFTC TFF futures-only**: public CME BTC/ETH positioning, open interest and
  reported changes by dealer, asset manager and leveraged-fund groups. One GET
  every six hours, no token. A public BTC response was actually checked on
  25 October 2026. Units are contracts, never USD inflows. Shorts may hedge
  another position; aggregate categories do not disclose individual intentions.
* **SEC EDGAR submissions**: public filing metadata for IBIT, GBTC, BITB,
  Strategy and Coinbase. ETF filings and public insider Forms 3/4/5 are labelled
  separately. The owner authorized a contact, stored only in the local
  data/market-pulse-public-sources.json configuration for SEC Fair Access. One GET per fifteen minutes when configured;
  no bulk download, subscription, arbitrary URL or redirect is introduced.

The EDGAR adapter does **not** parse transaction purchases/sales or 13F security
holdings from filing contents. It must not infer direction from a Form 4's
existence, describe equity trades as direct crypto trades, or promise an
institutional flow feed. Daily ETF net flows are **unavailable**. Fund AUM changes
or secondary-market volume cannot substitute for verified creations/redemptions.
An issuer holdings/flow provider needs its own documented access/usage review.

Each normalized record retains its as-of date, public availability, first local
receipt, source URL and content digest. CFTC availability is conservatively
FIRST_OBSERVED, not a guessed original Friday publication time. Repeated reports
are deduplicated; later revisions retain distinct evidence. Historical replay
cannot use a receipt obtained after the decision. Optional corrupt or stale
context cannot stop protective calculations. External text never executes code.

Institutional data is context only, not another independent directional vote.
At most one current context item accompanies an already-qualified AI review;
the existing daily/model limits remain in force. Source credibility is not proof
of predictive value. Forward and out-of-sample evaluation remain necessary.

Primary documentation checked for this implementation:

* [CFTC public datasets and API](https://publicreporting.cftc.gov/stories/s/r4w3-av2u)
* [CFTC release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm)
* [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
* [SEC developer access](https://www.sec.gov/about/developer-resources)
* [SEC Form 13F limitations](https://www.sec.gov/rules-regulations/staff-guidance/frequently-asked-questions-about-form-13f)
* [Public insider reporting](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-69)

## Evidence and release states

`scripts/test_offline.py` records source hashes and rejects changes during its
run. `scripts/preproduction_preflight.py` may publish an explicit local technical
test cache only when those sources still match. The cache never creates
`authorization.dpapi` or `readiness.dpapi`, certifies an account or approves
capital. Execution remains marked uncommissioned even if its library tests pass.

Prepared, tested, merged, signed, installed and operationally verified are
separate states. Final PR/workflow and installation evidence must be reported
after those actions actually occur. Do not use this candidate document as
installation or real-account evidence.
