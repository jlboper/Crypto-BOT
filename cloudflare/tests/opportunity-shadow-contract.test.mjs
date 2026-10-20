import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import {DatabaseSync} from 'node:sqlite';
import worker, {sha256} from '../src/worker.mjs';
import {validOpportunityShadow} from '../src/opportunity-shadow.mjs';

const emitted = new Map();
function produce(variant = 'ready') {
  if (!emitted.has(variant)) emitted.set(variant, JSON.parse(execFileSync(process.env.PYTHON || 'python', [
    '-B', fileURLToPath(new URL('../../tests/emit_opportunity_fixture.py', import.meta.url)), '--variant', variant,
  ], {encoding: 'utf8', timeout: 15000})));
  return structuredClone(emitted.get(variant));
}
const classic = vm.createContext({});
const sharedSource = readFileSync(new URL('../../web/opportunity-contract.js', import.meta.url), 'utf8');
vm.runInContext(sharedSource, classic);
const browserValidate = classic.CryptoOpportunityContract.validOpportunityShadow;
const both = (value, expected, message) => {
  assert.equal(validOpportunityShadow(value), expected, message);
  assert.equal(browserValidate(value), expected, message);
};
const intent = value => value.recent_records.find(row => row.kind === 'ENTRY_INTENT');
const outcome = value => value.recent_records.find(row => row.kind === 'ENTRY_OUTCOME');

test('Worker and classic browser consume the same immutable standalone validator', () => {
  assert.equal(validOpportunityShadow, globalThis.CryptoOpportunityContract.validOpportunityShadow);
  assert.equal(Object.isFrozen(globalThis.CryptoOpportunityContract), true);
  assert.equal(Object.isFrozen(classic.CryptoOpportunityContract), true);
  assert.deepEqual(Object.keys(classic.CryptoOpportunityContract), ['validOpportunityShadow']);
  assert.doesNotMatch(sharedSource, /\bimport\s|\bexport\s|fetch\s*\(|setInterval\s*\(|localStorage|document\./);
});

test('real four-engine observer exposes bounded frozen evidence without financial authority', () => {
  const value = produce();
  both(value, true);
  assert.equal(value.state, 'OBSERVING');
  assert.equal(value.recent_records.length, 6);
  assert.ok(Buffer.byteLength(JSON.stringify(value)) <= 12000);
  assert.equal(value.scopes.length, 4);
  assert.ok(value.coverage.every(row => row.state === 'OBSERVED'));
  assert.equal(value.scopes.find(row => row.engine === 'SPOT').uncertain_intents, 1);
  const pair = value.recent_records.find(row => row.engine === 'QUANT_ARBITRAGE' && row.kind === 'ENTRY_INTENT');
  assert.equal(pair.legs.length, 2);
  assert.equal(pair.assessment.gross_notional, '200');
  assert.equal(pair.assessment.real_admission, 'NOT_EVALUABLE');
  assert.equal(pair.assessment.state, 'UNKNOWN');
  assert.equal(pair.stage, 'HYPOTHETICAL_ENTRY_INTENT');
  assert.equal(value.scopes.find(row => row.engine === 'SPOT').hypothetical_reserved, '100.3');
  assert.equal(value.equity, undefined);
});

test('actual empty, stale, partial, full and unavailable producer states remain honest', () => {
  for (const [variant, state] of [['not-started', 'NOT_STARTED'], ['idle', 'IDLE'], ['stale', 'STALE'],
    ['partial', 'PARTIAL'], ['full', 'PARTIAL'], ['unavailable', 'UNAVAILABLE']]) {
    const value = produce(variant);
    both(value, true, variant);
    assert.equal(value.state, state);
  }
  assert.deepEqual(produce('not-started').scopes, []);
  assert.equal(produce('not-started').health.records, null);
  assert.equal(produce('idle').health.records, 0);
  assert.equal(produce('idle').freshness.state, 'FRESH');
  assert.equal(produce('stale').freshness.age_seconds, 16);
  assert.equal(produce('full').health.capacity_state, 'FULL');
  assert.equal(produce('unavailable').health.last_error, 'SNAPSHOT_UNAVAILABLE');
});

test('mixed Spot PAPER and Testnet history keeps five unique scopes without a portfolio total', () => {
  const value = produce('mixed');
  both(value, true);
  assert.equal(value.scopes.length, 5);
  assert.equal(value.coverage[0].environment, 'UNKNOWN');
  assert.deepEqual(value.scopes.filter(row => row.engine === 'SPOT').map(row => row.environment).sort(), ['PAPER', 'SPOT_TESTNET']);
  assert.equal(value.total_reserved, undefined);
  const duplicate = structuredClone(value); duplicate.scopes[4] = duplicate.scopes[0];
  both(duplicate, false);
});

test('real observer preserves both accepted Spot ALLOW and REDUCE review evidence', () => {
  for (const [variant, verdict] of [['ai-allow', 'ALLOW'], ['ai-reduce', 'REDUCE']]) {
    const value = produce(variant);
    both(value, true, variant);
    const record = value.recent_records.find(row => row.engine === 'SPOT' && row.kind === 'ENTRY_INTENT');
    assert.ok(record.evidence.checks.includes('INDIVIDUAL_AI_REVIEW_ACCEPTED'));
    assert.ok(record.evidence.checks.includes('INDIVIDUAL_AI_REVIEW_' + verdict));
    assert.equal(record.legs[0].quantity, '1');
    assert.equal(record.assessment.state, 'UNKNOWN');
    assert.equal(record.assessment.real_admission, 'NOT_EVALUABLE');
  }
});

test('all fixed Python producer checks and model reasons remain compatible with the shared validator', () => {
  const codes = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
    '-B', fileURLToPath(new URL('../../tests/emit_opportunity_fixture.py', import.meta.url)), '--contract-codes',
  ], {encoding: 'utf8', timeout: 15000}));
  const value = produce(); intent(value).evidence.checks = codes.checks; both(value, true);
  const rejection = ['OBSERVED_ASSET_CONFLICT', 'POSITION_LIMIT_EXCEEDED', 'GROSS_LIMIT_EXCEEDED', 'STOP_RISK_LIMIT_EXCEEDED', 'CAPITAL_LIMIT_EXCEEDED', 'AVAILABLE_CAPITAL_EXCEEDED'];
  for (const reason of codes.reasons) {
    const v = produce(), assessment = intent(v).assessment;
    assessment.reason = reason;
    assessment.hypothetical_state = reason === 'ACCOUNT_IDENTITY_UNVERIFIED' ? 'RESERVED_UNVERIFIED' : rejection.includes(reason) ? 'REJECTED_UNVERIFIED' : 'UNKNOWN';
    both(v, true, reason);
  }
});

test('defensive capital evidence and regressed clock use real producer UNKNOWN states without hiding history', () => {
  const capital = produce('capital-unknown'); both(capital, true);
  assert.equal(capital.recent_records[0].assessment.reason, 'CAPITAL_EVIDENCE_UNKNOWN');
  assert.equal(capital.recent_records[0].assessment.hypothetical_state, 'UNKNOWN');
  assert.equal(capital.recent_records[0].assessment.real_admission, 'NOT_EVALUABLE');
  const clock = produce('clock-regression'); both(clock, true);
  assert.equal(clock.state, 'PARTIAL');
  assert.deepEqual(clock.freshness, {state: 'UNAVAILABLE', age_seconds: null});
  assert.equal(clock.health.last_error, 'CLOCK_REGRESSION');
  assert.equal(clock.recent_records.length, 6);
  assert.ok(Date.parse(clock.updated_at) > Date.parse(clock.at));
});

test('identity, authority and account mutations are rejected at every relevant level', () => {
  const changes = [v => v.schema = true, v => v.mode = 'LIVE', v => v.autonomy_level = false, v => v.autonomy_level = 1,
    ...['controls_enabled', 'can_veto', 'execution_enabled', 'reservations_enabled', 'promotion_allowed'].map(key => v => v[key] = true),
    v => v.engine = 'CAPITAL_MANAGER', v => v.cash = 1000, v => v.scopes[0].account_identity = 'VERIFIED',
    v => v.scopes[0].environment = 'LIVE', v => v.scopes[0].real_admission = 'ALLOW',
    v => intent(v).assessment.state = 'ALLOW', v => intent(v).assessment.real_admission = 'ALLOW',
    v => intent(v).assessment.account_identity = 'owner-account', v => intent(v).assessment.hypothetical_state = 'RESERVED',
    v => intent(v).assessment.reason = 'BUY_NOW', v => v.coverage[1].environment = 'SPOT_TESTNET'];
  for (const change of changes) { const value = produce(); change(value); both(value, false, change.toString()); }
});

test('closed nested keys reject arbitrary external text, private metadata and malformed cardinality', () => {
  const changes = [v => v.extra = 'synthetic-private', v => v.health.message = 'synthetic-private',
    v => v.freshness.secret = 'synthetic-private', v => v.coverage[0].private = true,
    v => v.scopes[0].wallet = {}, v => intent(v).private = true, v => intent(v).legs[0].api_key = 'synthetic-private',
    v => intent(v).evidence.url = 'https://untrusted.invalid', v => intent(v).assessment.instructions = '<script>run()</script>',
    v => v.coverage.pop(), v => v.coverage.reverse(), v => v.scopes.push(v.scopes[0]),
    v => v.recent_records.push(v.recent_records[0]), v => intent(v).legs = [],
    v => intent(v).legs.push(...Array(4).fill(intent(v).legs[0])), v => outcome(v).legs = intent(v).legs,
    v => intent(v).evidence.checks.push('UNVERIFIED_CHECK'), v => intent(v).evidence.checks.push(intent(v).evidence.checks[0])];
  for (const change of changes) { const value = produce(); change(value); both(value, false, change.toString()); }
  for (const value of [null, {}, [], false, 'OBSERVING']) both(value, false);
});

test('money remains bounded fixed-point text, including one-unit precision and unknown values', () => {
  for (const amount of ['0', '0.000000000000000000000000000001', '999999999999999999.999999999999999999999999999999', '1000000000000000000']) {
    const value = produce(); intent(value).legs[0].quantity = amount; both(value, true, amount);
  }
  for (const amount of [true, 0, 1.25, NaN, Infinity, 'NaN', '-0', '-1', '1e2', '+1', '01', '.1', '1.', '12\n', '1'.repeat(161)]) {
    const value = produce(); value.scopes[0].hypothetical_reserved = amount; both(value, false, String(amount));
  }
  for (const amount of ['1000000000000000000.1', '1000000000000000001', '0.' + '0'.repeat(30) + '1']) {
    const value = produce(); intent(value).legs[0].quantity = amount; both(value, false, amount);
  }
  const unknown = produce(); unknown.scopes[0].hypothetical_reserved = null; both(unknown, true);
  const precise = produce(); precise.scopes[0].hypothetical_reserved = '9007199254740993.000000000001'; both(precise, true);
});

test('timestamps, digests and numeric counters reject nonfinite values and trailing newline disguises', () => {
  const changes = [v => v.at = null, v => v.at += '\n', v => v.at = '2026-02-30T00:00:00Z',
    v => v.freshness.age_seconds = -1, v => v.freshness.age_seconds = Infinity, v => v.health.records = true,
    v => v.health.queue_depth = 65, v => v.health.queue_capacity = 65, v => v.health.errors = -1,
    v => v.health.dropped = Number.MAX_SAFE_INTEGER, v => v.health.last_error = 'provider private response',
    v => v.health.heartbeat_at = null, v => v.health.heartbeat_at = '2999-01-01T00:00:00Z',
    v => intent(v).id += '\n', v => intent(v).payload_digest = 'a'.repeat(64), v => intent(v).legs[0].symbol += '\n',
    v => intent(v).evidence.source_digest += '\n', v => intent(v).evidence.market_at = NaN, v => intent(v).revision = 0];
  for (const change of changes) { const value = produce(); change(value); both(value, false, change.toString()); }
});

test('heartbeat liveness is independent of old activity and clock regression remains explicitly unknown', () => {
  const value = produce(); value.updated_at = '2026-01-01T00:00:00Z'; both(value, true);
  const stopped = produce(); stopped.state = 'STALE'; stopped.freshness.state = 'STALE'; stopped.health.worker_alive = false; both(stopped, true);
  const regressed = produce(); regressed.state = 'PARTIAL'; regressed.freshness = {state: 'UNAVAILABLE', age_seconds: null};
  regressed.health.last_error = 'CLOCK_REGRESSION'; regressed.health.heartbeat_at = '2999-01-01T00:00:00Z'; both(regressed, true);
  const dishonest = produce(); dishonest.health.last_error = 'CLOCK_REGRESSION'; both(dishonest, false);
});

test('the complete projection is capped at twelve thousand ASCII JSON bytes', () => {
  const value = produce();
  for (const record of value.recent_records) for (const key of ['gross_notional', 'committed_capital', 'estimated_costs', 'nominal_stop_risk', 'stop_risk']) record.assessment[key] = '9'.repeat(160);
  assert.ok(JSON.stringify(value).length > 12000);
  both(value, false);
});

class LocalD1 {
  constructor() {
    this.sqlite = new DatabaseSync(':memory:');
    for (const name of ['0001_portal.sql', '0002_jobs.sql', '0003_owner_password.sql', '0004_bot_releases.sql']) this.sqlite.exec(readFileSync(new URL('../migrations/' + name, import.meta.url), 'utf8'));
  }
  prepare(sql) {
    const db = this;
    const make = args => ({bind: (...values) => make(values), _all: () => db.sqlite.prepare(sql).all(...args),
      async all() { return {results: this._all(), success: true}; }, async first() { return this._all()[0] || null; },
      async run() { return {results: this._all(), success: true}; }});
    return make([]);
  }
  async batch(queries) {
    this.sqlite.exec('BEGIN IMMEDIATE');
    try { const result = queries.map(query => ({results: query._all(), success: true})); this.sqlite.exec('COMMIT'); return result; }
    catch (error) { this.sqlite.exec('ROLLBACK'); throw error; }
  }
}

test('optional producer DTO roundtrips authenticated Worker without new permissions or corrupting prior status', async t => {
  const origin = 'https://opportunity.example.workers.dev', owner = 'A'.repeat(43), device = 'B'.repeat(43);
  const env = {DB: new LocalD1(), PORTAL_ORIGIN: origin, OWNER_KEY_HASH: await sha256(owner), DEVICE_KEY_HASH: await sha256(device)};
  t.after(() => env.DB.sqlite.close());
  let cookie = '', csrf = '';
  async function call(path, body, extra = {}) {
    const response = await worker.fetch(new Request(origin + path, {method: body === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json', Origin: origin, Cookie: cookie, 'X-CSRF-Token': csrf, ...extra},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})}), env);
    return {status: response.status, headers: response.headers, body: await response.json()};
  }
  const snapshot = {mode: 'PAPER', equity: 1000, cash: 1000, exposure: 0, positions: [], killed: false,
    last_cycle_at: new Date().toISOString(), ai_model: 'gpt-6-luna', update_state: 'signed_rollout',
    paper_controls: true, operations_controls: true, quant_controls: true,
    dashboard: {status: {mode: 'PAPER'}, positions: [], equity: [], trades: [], reviews: [], events: [], research: {assets: []}, opportunity_shadow: produce()}};
  assert.equal((await call('/v1/device/sync', {snapshot, acks: []})).status, 401);
  const accepted = await call('/v1/device/sync', {snapshot, acks: []}, {Authorization: `Bearer ${device}`});
  assert.equal(accepted.status, 200, JSON.stringify(accepted.body));
  assert.equal((await call('/v1/status')).status, 401);
  const login = await call('/v1/login', {password: owner});
  assert.equal(login.status, 200); cookie = login.headers.get('set-cookie').split(';')[0]; csrf = login.body.csrf;
  assert.deepEqual((await call('/v1/status')).body.snapshot, snapshot);
  const bad = structuredClone(snapshot); bad.dashboard.opportunity_shadow.execution_enabled = true;
  const rejected = await call('/v1/device/sync', {snapshot: bad, acks: []}, {Authorization: `Bearer ${device}`});
  assert.equal(rejected.status, 400); assert.equal(rejected.body.error, 'Invalid Opportunity Shadow status');
  assert.deepEqual((await call('/v1/status')).body.snapshot, snapshot);
  assert.equal((await call('/v1/paper-controls', {action: 'opportunity_shadow_execute', request_id: 'no-opportunity-authority-0001', payload: {}})).status, 400);
  assert.equal((await call('/v1/paper-controls', {action: 'quant_arbitrage_pause', request_id: 'preserve-existing-csrf-0001', payload: {}}, {'X-CSRF-Token': ''})).status, 403);
  delete snapshot.dashboard.opportunity_shadow;
  assert.equal((await call('/v1/device/sync', {snapshot, acks: []}, {Authorization: `Bearer ${device}`})).status, 200);
});
