/* Shared closed DTO validation only. No account, order or admission capability. */
(function (root) {
  'use strict';
  const engines = ['SPOT', 'FUTURES', 'AI_MARKET_PULSE', 'QUANT_ARBITRAGE'];
  const flags = ['controls_enabled', 'can_veto', 'execution_enabled', 'reservations_enabled', 'promotion_allowed'];
  const topKeys = ['schema', 'engine', 'mode', 'autonomy_level', ...flags, 'state', 'at', 'updated_at', 'freshness', 'health', 'coverage', 'scopes', 'recent_records'];
  const healthKeys = ['records', 'errors', 'dropped', 'queue_depth', 'queue_capacity', 'worker_alive', 'capacity_state', 'last_error', 'heartbeat_at'];
  const recentKeys = ['id', 'origin_digest', 'revision', 'kind', 'engine', 'environment', 'at', 'recorded_at', 'state', 'stage', 'legs', 'payload_digest', 'evidence', 'assessment'];
  const assessmentKeys = ['state', 'reason', 'real_admission', 'hypothetical_state', 'gross_notional', 'committed_capital', 'estimated_costs', 'nominal_stop_risk', 'stop_risk', 'account_identity'];
  const checks = ['NATIVE_QUANTITATIVE_CHECKS_PASSED', 'INDIVIDUAL_AI_REVIEW_ACCEPTED', 'INDIVIDUAL_AI_REVIEW_ALLOW', 'INDIVIDUAL_AI_REVIEW_REDUCE', 'NATIVE_FORWARD_CONFIGURATION_PASSED', 'SHADOW_COST_RISK_GATES_PASSED', 'SHADOW_LIQUIDITY_GATES_PASSED'];
  const rejectionReasons = ['OBSERVED_ASSET_CONFLICT', 'POSITION_LIMIT_EXCEEDED', 'GROSS_LIMIT_EXCEEDED', 'STOP_RISK_LIMIT_EXCEEDED', 'CAPITAL_LIMIT_EXCEEDED', 'AVAILABLE_CAPITAL_EXCEEDED'];
  const unknownReasons = ['INVALID_INTENT', 'INVALID_LEGS', 'INVALID_RESERVATIONS', 'INVALID_LEG', 'QUANTITY_OR_PRICE_UNKNOWN', 'GROSS_EVIDENCE_INCONSISTENT', 'MARGIN_UNKNOWN', 'COST_EVIDENCE_UNKNOWN', 'STOP_EVIDENCE_UNKNOWN', 'TARGET_EVIDENCE_INCONSISTENT', 'RESERVATION_EVIDENCE_UNKNOWN', 'RESERVATION_SYMBOLS_UNKNOWN', 'LIMIT_EVIDENCE_UNKNOWN', 'AVAILABLE_CAPITAL_UNKNOWN', 'CAPITAL_TIMESTAMP_UNKNOWN', 'CAPITAL_EVIDENCE_UNKNOWN', 'CAPITAL_EVIDENCE_FUTURE', 'CAPITAL_EVIDENCE_STALE', 'EVIDENCE_TIMESTAMP_UNKNOWN', 'EVIDENCE_AFTER_CAPTURE', 'EVIDENCE_AFTER_DECISION', 'MARKET_RECEIPT_CLOCK_DIVERGENCE', 'CAPITAL_EVIDENCE_AFTER_DECISION', 'MISSING_INTENT', 'ORIGIN_REVISION_CONFLICT', 'OUTCOME_BEFORE_INTENT', 'LATE_TERMINAL_DIVERGENCE'];
  const recordStates = ['UNKNOWN', 'INTENT_OBSERVED', 'ORIGIN_CONFLICT', 'UNCERTAIN', 'TERMINAL_CONFLICT', 'CLOSED_OBSERVED', 'CANCELLED_OBSERVED', 'EXCHANGE_FILLED_UNCOMMITTED', 'COMMITTED_PROTECTION_UNVERIFIED'];
  const errorCodes = ['SNAPSHOT_UNAVAILABLE', 'RETENTION_FULL', 'JOURNAL_FULL', 'INITIALIZATION_FAILED', 'OBSERVATION_FAILED', 'CLOCK_REGRESSION'];
  const venues = ['SPOT_TESTNET', 'FUTURES_DEMO', 'SPOT_REFERENCE', 'FUTURES_REFERENCE', 'SPOT', 'FUTURES', 'PAPER'];
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
  const integer = (value, maximum = 1000000000) => Number.isSafeInteger(value) && value >= 0 && value <= maximum;
  const nullableInteger = (value, maximum) => value === null || integer(value, maximum);
  const full = (pattern, value) => pattern.exec(value)?.[0] === value;
  const hash = value => typeof value === 'string' && full(/^[a-f0-9]{64}$/, value);
  const nullableHash = value => value === null || hash(value);
  const epoch = value => value === null || typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 253402300799;
  const decimal = value => value === null || typeof value === 'string' && value.length <= 160 && full(/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/, value);
  function inputDecimal(value) {
    if (value === null) return true;
    if (!decimal(value) || value.length > 64) return false;
    const [whole, fraction = ''] = value.split('.');
    return fraction.length <= 30 && whole.length <= 19 && (whole.length < 19 || whole < '1000000000000000000'
      || whole === '1000000000000000000' && !/[1-9]/.test(fraction));
  }
  function timestamp(value) {
    if (typeof value !== 'string' || value.length > 40 || !full(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/, value)) return false;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) && parsed > 0 && new Date(parsed).toISOString().slice(0, 19) === value.slice(0, 19);
  }
  const nullableTimestamp = value => value === null || timestamp(value);
  function scopeIdentity(engine, environment) {
    return engines.includes(engine) && (engine === 'SPOT' ? ['SPOT_TESTNET', 'PAPER'].includes(environment)
      : engine === 'FUTURES' ? environment === 'FUTURES_DEMO' : environment === 'SHADOW');
  }
  function validAssessment(value) {
    if (!exact(value, assessmentKeys) || value.state !== 'UNKNOWN' || value.account_identity !== 'UNKNOWN'
      || value.real_admission !== 'NOT_EVALUABLE' || !['gross_notional', 'committed_capital', 'estimated_costs', 'nominal_stop_risk', 'stop_risk'].every(key => decimal(value[key]))) return false;
    if (value.hypothetical_state === 'RESERVED_UNVERIFIED') return value.reason === 'ACCOUNT_IDENTITY_UNVERIFIED';
    if (value.hypothetical_state === 'REJECTED_UNVERIFIED') return rejectionReasons.includes(value.reason);
    return value.hypothetical_state === 'UNKNOWN' && unknownReasons.includes(value.reason);
  }
  function validEvidence(value, intent) {
    if (!intent) return exact(value, ['quantity', 'fees', 'response_digest', 'decision_digest'])
      && inputDecimal(value.quantity) && inputDecimal(value.fees) && nullableHash(value.response_digest) && nullableHash(value.decision_digest);
    return exact(value, ['market_at', 'received_at', 'known_at', 'decision_at', 'source_digest', 'review_digest', 'policy_digest', 'checks'])
      && ['market_at', 'received_at', 'known_at', 'decision_at'].every(key => epoch(value[key]))
      && ['source_digest', 'review_digest', 'policy_digest'].every(key => nullableHash(value[key]))
      && Array.isArray(value.checks) && value.checks.length <= checks.length && new Set(value.checks).size === value.checks.length
      && value.checks.every(code => checks.includes(code));
  }
  function validRecord(value) {
    if (!exact(value, recentKeys) || !hash(value.id) || value.payload_digest !== value.id || !hash(value.origin_digest)
      || !integer(value.revision, 100000) || value.revision < 1 || !scopeIdentity(value.engine, value.environment)
      || !timestamp(value.at) || !timestamp(value.recorded_at) || Date.parse(value.at) > Date.parse(value.recorded_at)
      || !recordStates.includes(value.state) || !validAssessment(value.assessment) || !Array.isArray(value.legs)) return false;
    const intent = value.kind === 'ENTRY_INTENT';
    if (intent ? value.stage !== (value.environment === 'SHADOW' ? 'HYPOTHETICAL_ENTRY_INTENT' : 'FINAL_ENTRY_INTENT') || value.legs.length < 1 || value.legs.length > 4
      : value.kind !== 'ENTRY_OUTCOME' || !['EXCHANGE_RESPONSE', 'LEDGER_COMMIT'].includes(value.stage) || value.legs.length !== 0) return false;
    return validEvidence(value.evidence, intent) && value.legs.every(leg => exact(leg, ['symbol', 'venue', 'direction', 'quantity', 'reference_price', 'stop_price', 'take_profit'])
      && typeof leg.symbol === 'string' && full(/^[A-Z0-9]{2,24}USDT$/, leg.symbol) && venues.includes(leg.venue) && ['LONG', 'SHORT'].includes(leg.direction)
      && ['quantity', 'reference_price', 'stop_price', 'take_profit'].every(key => inputDecimal(leg[key])));
  }
  function validOpportunityShadow(value) {
    try {
      if (!exact(value, topKeys) || value.schema !== 1 || value.engine !== 'OPPORTUNITY_SHADOW' || value.mode !== 'SHADOW'
        || value.autonomy_level !== 0 || flags.some(key => value[key] !== false)
        || !['NOT_STARTED', 'IDLE', 'OBSERVING', 'STALE', 'PARTIAL', 'UNAVAILABLE'].includes(value.state)
        || !timestamp(value.at) || !nullableTimestamp(value.updated_at)
        || JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0')).length > 12000) return false;
      const freshness = value.freshness, health = value.health;
      if (!exact(freshness, ['state', 'age_seconds']) || !['FRESH', 'STALE', 'UNAVAILABLE'].includes(freshness.state)
        || !(freshness.age_seconds === null || typeof freshness.age_seconds === 'number' && Number.isFinite(freshness.age_seconds) && freshness.age_seconds >= 0 && freshness.age_seconds <= 253402300799)
        || (freshness.state === 'UNAVAILABLE') !== (freshness.age_seconds === null)
        || freshness.state === 'FRESH' && freshness.age_seconds > 15
        || !exact(health, healthKeys) || !nullableInteger(health.records, 100000) || !nullableInteger(health.errors)
        || !nullableInteger(health.dropped) || !nullableInteger(health.queue_depth, 64) || health.queue_capacity !== 64
        || ![null, true, false].includes(health.worker_alive) || !['AVAILABLE', 'FULL', 'UNKNOWN'].includes(health.capacity_state)
        || !(health.last_error === null || errorCodes.includes(health.last_error)) || !nullableTimestamp(health.heartbeat_at)) return false;
      if (freshness.state !== 'UNAVAILABLE' && (health.heartbeat_at === null || Date.parse(health.heartbeat_at) > Date.parse(value.at))) return false;
      if (health.last_error === 'CLOCK_REGRESSION' && freshness.state !== 'UNAVAILABLE') return false;
      if (!Array.isArray(value.coverage) || value.coverage.length !== engines.length || !value.coverage.every((row, index) =>
        exact(row, ['engine', 'environment', 'state', 'intents', 'outcomes', 'last_at']) && row.engine === engines[index]
        && (scopeIdentity(row.engine, row.environment) || row.engine === 'SPOT' && row.environment === 'UNKNOWN')
        && integer(row.intents, 100000) && integer(row.outcomes, 100000)
        && (row.state === 'NOT_CAPTURED' ? row.intents === 0 && row.outcomes === 0 && row.last_at === null
          : row.state === 'OBSERVED' && row.intents + row.outcomes > 0 && timestamp(row.last_at)))) return false;
      if (!Array.isArray(value.scopes) || value.scopes.length > 5 || !value.scopes.every(row =>
        exact(row, ['engine', 'environment', 'account_identity', 'hypothetical_reserved', 'hypothetical_gross', 'hypothetical_stop_risk', 'uncertain_intents'])
        && scopeIdentity(row.engine, row.environment) && row.account_identity === 'UNKNOWN'
        && ['hypothetical_reserved', 'hypothetical_gross', 'hypothetical_stop_risk'].every(key => decimal(row[key]))
        && integer(row.uncertain_intents, 100000))
        || new Set(value.scopes.map(row => row.engine + ':' + row.environment)).size !== value.scopes.length) return false;
      if (!Array.isArray(value.recent_records) || value.recent_records.length > 6 || !value.recent_records.every(validRecord)
        || new Set(value.recent_records.map(row => row.id)).size !== value.recent_records.length) return false;
      if (value.state === 'NOT_STARTED') return value.updated_at === null && freshness.state === 'UNAVAILABLE'
        && ['records', 'errors', 'dropped', 'queue_depth', 'worker_alive', 'heartbeat_at', 'last_error'].every(key => health[key] === null)
        && health.capacity_state === 'UNKNOWN' && value.coverage.every(row => row.state === 'NOT_CAPTURED') && !value.scopes.length && !value.recent_records.length;
      if (value.state === 'IDLE' && (health.records !== 0 || value.updated_at !== null || value.coverage.some(row => row.state !== 'NOT_CAPTURED') || value.scopes.length || value.recent_records.length)) return false;
      if (value.state === 'OBSERVING' && (health.records === null || health.records < 1 || value.updated_at === null || freshness.state !== 'FRESH')) return false;
      if (value.state === 'STALE' && freshness.state === 'FRESH') return false;
      return true;
    } catch (_) { return false; }
  }
  root.CryptoOpportunityContract = Object.freeze({validOpportunityShadow});
})(globalThis);
