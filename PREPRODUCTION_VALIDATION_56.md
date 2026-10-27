# Preproduction validation — candidate 0.10.56

The verified predecessor is main `d78b7ee882236bfbdac14047662abe9ad7154e03`,
[PR132](https://github.com/jlboper/Crypto-BOT/pull/132). Its main
[publication40400621712](https://github.com/jlboper/Crypto-BOT/actions/runs/40400621712)
and security40400621700 passed Linux/Windows. Version0.10.55 was independently
observed signed and installed with294/294 hashes. Those results do not validate
this candidate. Prepared, tested, published, installed and operationally verified
remain separate states.

## Account observations and freshness

The existing read-only auditor can optionally compare the two dedicated API
origins using Binance global UID/key-rights metadata. Product observations remain
separate: matching UID does not merge wallets, prove human ownership, certify a
complete history or allocate capital. The Futures key signs its own metadata
requests; it cannot fall back to the Spot key. UID values stay in memory or
encrypted raw retention, never the report, stdout or portal.

Installed command, invoked explicitly by the local owner/operator:

```text
python scripts/audit_live_account.py --ack-read-only --vault <existing-vault> --output-dir <private-reports> --verify-account-link --publish-connection-status
```

This adds bounded GETs only. It requires both distinct configured scopes and a
vault for cache publication. Under the vault lock it compares both complete
key/secret pairs with the ones used by the audit. A replacement during network
requests rejects publication. The native credential-entry path invalidates the
old observation before committing a new key under the same lock. Neither path
holds that lock while the owner types or during network requests.

The portal retains actual observation timestamps. After fifteen minutes any
verified connection cut becomes unverified in the read-only projection; reading
the portal does not refresh evidence. This is an age limit on a private-account
observation, not a diagnosis that the trading engine stopped. Key rights outside
the configured REST markets remain explicitly unknown where Binance omits them.
Any returned trading/withdrawal/transfer privilege blocks a read-only claim.

Primary protocols checked:
[Wallet account/key rights](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/account),
[Spot account](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account).

## Financial evidence

`financial_evidence.py` reconciles retained account windows with integer units:
opening/closing balances and positions, fills, commissions, cashflows/funding,
exposure intervals and native stop coverage. Scope, units, timestamps, pagination
completeness and source digests must match. Missing or contradictory observations
remain incomplete. A current balance or an ARMED stop at one instant cannot prove
the preceding month.

Explicit retained-package ingestion:

```text
python scripts/ingest_financial_evidence.py --registration REG.json --original ORIGINAL.json --bundle BUNDLE.json --journal financial-evidence.sqlite3 --anchor financial-anchor.json
```

The append-only journal is separate from operating ledgers. An independent,
atomically written anchor detects truncation or an interrupted append. A crash
after commit but before the anchor blocks coverage and further ingestion.
`--reconcile-anchor` only revalidates that exact pending packet; it cannot change
its original availability time. `--coverage` and `read_financial_overlay` are
read-only, separately dated outcome overlays. They never rewrite old decisions,
receipts or the portal's original cohort statistics.

The validator verifies consistency of supplied retained sources; a local hash is
not an exchange attestation. Automatic capture of complete original exchange
windows remains an acceptance item. Bounded LIVE account audits are not silently
converted into ALL_ACCOUNT financial evidence. No thirty-day certificate,
activation record or retroactive strategy knowledge is produced.

## Strategy-to-execution preparation

`live_proposal_source.py` uses the actual `SwingStrategy` and pure Futures signal
algorithm on explicitly LIVE public candle cuts. Fixed api/fapi hosts, unsigned
GETs, closed consecutive candles, source times and bounded call budgets are
required. Testnet/PAPER/SHADOW observations cannot be relabelled LIVE. Account
facts, venue filters, costs and policy inputs must be explicit and current.

Individual `AIAdvisor` review is retained and injected. A durable per-candle
claim limits duplicate reviews across restart. Invalid, failed, old or rejected
reviews cannot produce a usable entry. Neither this producer nor the advisor is
on a protective-exit path.

`live_strategy_adapter.py` converts a constrained reviewed native signal into an
exact integer-unit proposal, transport intent and protection plan. The immutable
plan must be retained before reservation/submission. It then uses the existing
central admission/coordinator: absent owner authority blocks, an uncertain POST
retains reserves, and restart reconciles by client ID rather than resending.
Spot base-asset commission producing an off-grid net quantity requires recovery;
there is no silent rounding, dust write-off, transfer or leverage setter.

These components have end-to-end tests against fake HTTPS, including actual
strategy calculation and the real admission/coordinator. They are not yet the
commissioned operating LIVE kernel. `TradingEngine` keeps its explicit refusal
before wallet creation. No commissioning marker or readiness permit is added to
make library tests appear to be operational acceptance.

## Inactive policy review

The owner separately reviewed the initial numeric LIVE MICRO draft. That approval
is recorded privately as approval of an inactive proposal, not financial
activation. `prepare_live_policy.py` builds a review document only from explicit
inputs. Unknown execution costs, universe and policy details remain unknown;
the tool cannot manufacture an `AdmissionPolicy`, DPAPI authorization, funds or
an enabled configuration. Current Testnet settings are unchanged.

## Fixed remaining acceptance

The five packages in PREPRODUCTION_CLOSURE.md remain the scope. To commission
initial Spot/Futures, complete the original financial source capture/reconciliation
and the single-supervisor runtime integration/recovery drills, review the actual
retained forward evidence and account permissions, then obtain separate owner
activation. Existing valid historical evidence must be audited rather than erased
or automatically restarted. Pulse/Quant promotion and additional features do not
become extra prerequisites for initial Spot/Futures.

No LIVE order, withdrawal, transfer, leverage change, new trading process, wallet
reset or strategy promotion is performed by this delivery. Guardian remains L0;
Pulse and Quant remain SHADOW. The next release follows the existing PR, dual-OS
CI, protected publication, Ed25519 signature and supervised installation flow.
