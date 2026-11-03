# Candidate 0.10.57: financial capture, recovery and evidence review

Base: main `51532ac5956b147c233851891f00b4aff8817411`, version0.10.56,
[PR133](https://github.com/jlboper/Crypto-BOT/pull/133). The base publication
[40512063414](https://github.com/jlboper/Crypto-BOT/actions/runs/40512063414)
and safety40512063383 passed Linux and Windows. Those results do not validate
this candidate. Preparation, tests, publication and installation are separate.

## Evidence review

`python scripts/review_preproduction_evidence.py --data-dir <retained-data>`
opens Spot Testnet, Futures Demo and the prospective cohort journal read only.
The output contains private aggregate results and should be stored locally.
It preserves historical activity and reports bounded local spans, gaps, recorded
results and sampled drawdown. Gross Futures PnL remains gross; recorded Spot fees
are not subtracted again from a result whose historical accounting may differ.
Neither account returns adjusted for cashflows nor complete net PnL is inferred.

The local chain is checked and derived receipts are rebuilt from the original
chained captures before presenting prospective coverage; cached qualification
bits cannot substitute for that replay. A local chain
does not attest Binance origin or externally prove that a retained history was
not replaced. Missing sources, invalid financial values, future timestamps,
corrupt chains and truncated histories remain explicit. No ledger constructor,
cash initialization, retroactive registration or source migration is used.

Existing history is retained. Descriptive legacy evidence, contemporaneous
operational coverage and financially qualified forward coverage have different
uses. More than30 calendar days does not satisfy missing reconciliation,
costs, cashflows, methodology, independent OOS or execution-recovery evidence.
Even30 qualified days cannot grant owner authorization.

## Financial authority

The reviewed nominal100USDT draft remains `OWNER_REVIEWED_INACTIVE`. This work
does not create an operating AdmissionPolicy, protected activation/readiness
record, fund allocation, permission change or automatic promotion. The initial
scope is Spot/Futures; Pulse/Quant remain separately promoted SHADOW engines.
Pulse diagnostics are a separate maintenance task and do not add a Spot/Futures
activation gate. Financial activation needs the owner's separate final decision.

## Validation commands

* `python -m unittest discover -s tests -p test_evidence_review.py -v`
* `python scripts/test_offline.py`
* `python scripts/build_unified_portal.py`
* `node --test tests/*.test.mjs` from `cloudflare/`

Full-suite source hashes, synthetic recovery cases, provider observations and
signed installed evidence must be retained separately. Passing fixtures does
not certify the behavior of real partially filled LIVE orders.

## 2 November closure work

The existing local Testnet resume command was used only after fresh account,
price and all-open-orders GETs confirmed the exact old automatic latch could be
released. No strategy, allocation, leverage or LIVE permission was changed.
Spot error events now retain bounded provider codes and allowlisted causes so
that another execution failure does not erase its useful diagnostic evidence.

The financial producer retains original responses encrypted and keeps current
prospective cut reconciliation separate from historical completeness. Simple
Earn history is an explicit bounded GET task, with distinct pagination and
rate-limit backoff; it is not another background worker or a trading capability.
Observed Unicode asset names are accepted only in retained financial data, not
in order symbols or URLs. LD-prefixed assets are never silently valued or
converted as their unprefixed counterparts. The supervised capture worker does
not call the high-weight account-snapshot or Earn endpoints.

The submission journal now persists the exact original intent and reservation
before the only POST. Recovery queries retained identifiers and terms even
after expiry. Explicit residual reduction requires terminal owned entry fills,
linked own exits and fees, exact native coverage, current inventory, current
venue validation and another state read after validation. Ambiguous or partial
reductions are queried without resubmission. Terminal release requires own
entry/exit quantities and retained costs, a fresh flat account observation and
confirmed sibling cleanup; an unrelated flat account cannot release a ticket.
Global recovery latches remain independent of individual ticket reconciliation.

Spot MARKET reductions check whether an enabled discount could charge the base
asset, including BNBUSDT. Such an uncertain base debit blocks the reduction.
Futures reductions require an exact signed one-way isolated position and
reduceOnly. Unknown filters, minimum-size dust, unconfirmed ownership or fees
retain recovery and reservations. Venue tier ceilings above the historical125
are parsed as metadata; configured and owner-policy leverage caps still apply.

The installed Research report and registered forward observations were reviewed
without reselecting a strategy on holdout results. The retained decision is
not eligible for real capital: completing a review does not turn a failed or
unproven criterion into a pass. Historical captures, costs and operational
cohorts remain retained; neither a release nor this review resets their dates.
Financial activation/readiness records are not provisioned by this release.

## Financial coverage integration

The single financial observation worker now shares a fixed logical GET budget
between the existing LIVE read-only sources and a segregated Testnet/Demo source
producer. It starts after current cohort registration, never on a protection
thread. Source errors and cooperative cancellation cannot start another engine
or suppress existing financial protections.

Status and the evidence review rebuild current cohort originals and join the
matching retained financial journal, external local anchor and reported account
binding. Cached completeness flags or an operational capture with all flags set
cannot replace this reconstruction. Original operational metrics remain visible;
financial qualification uses only verified financial coverage. A later continuous
qualified interval can satisfy its own duration without erasing an earlier gap.
The existing thirty-day minimum and separate owner activation are unchanged.

The installed default Testnet/Demo producer retains encrypted original GETs and
local ledger cuts as RAW_CAPTURED_QUALIFICATION_BLOCKED. It does not include an
automatic full-account materializer: exact cadence boundaries, complete account
flows, owned fill identities/costs and continuous native protection are not
certified by those observations. Explicitly reviewed packets can enter the
existing journal/anchor path; bounded sources cannot be relabelled ALL_ACCOUNT.
This closes the missing coverage-reader connection, not the outstanding source
qualification or the negative/unproven statistical eligibility decision.
