import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {validGuardianIntelligence} from '../src/guardian-intelligence.mjs';

// Real read-only capture -> deterministic report -> service -> append-only
// journal -> projection. Four synthetic DBs and a fake advisory hook only.
function produce(variant='ready'){
  return JSON.parse(execFileSync(process.env.PYTHON||'python',[
    fileURLToPath(new URL('../../tests/emit_guardian_intelligence_fixture.py',import.meta.url)),
    '--variant',variant],{encoding:'utf8',timeout:20000}));
}
const ready=produce();

test('real Guardian journal producer passes the strict bounded observational contract',()=>{
  assert.equal(validGuardianIntelligence(ready),true);
  assert.equal(ready.state,'OBSERVING');
  assert.equal(ready.ai.state,'COMPLETED');
  assert.equal(ready.report.scopes.length,4);
  assert.equal(ready.report.regime.observation_count,61);
  assert.equal(ready.report.regime.method,'BTC_SPOT_CLOSED_1M_60M_DESCRIPTIVE_PROXY');
  assert.equal(ready.report.counterfactual.losses_avoided,null);
  assert.equal(ready.report.counterfactual.without_ai_pnl,null);
  assert.equal(ready.report.policy.calibrated,false);
  assert.equal(ready.report.evidence.original_decision_completeness,'NOT_PRE_SUBMIT_COMPLETE');
  assert.equal(ready.ai.assessment_id,ready.report.assessment_id);
  assert.deepEqual(ready.ai.commentary.evidence_ids,[ready.report.assessment_id]);
  assert.equal(ready.journal.length,1);
  assert.ok(Buffer.byteLength(JSON.stringify(ready))<12000);
});

test('real partial, stale, absent and disabled-AI states preserve uncertainty',()=>{
  for(const [variant,state] of [['partial','PARTIAL'],['stale','STALE'],['not-started','NOT_STARTED'],['no-ai','OBSERVING']]){
    const actual=produce(variant);
    assert.equal(actual.state,state,variant);
    assert.equal(validGuardianIntelligence(actual),true,variant);
    assert.equal(actual.execution_enabled,false);
    if(variant==='partial'){
      const scope=actual.report.scopes.find(s=>s.id==='FUTURES');
      assert.equal(scope.data_state,'UNKNOWN');
      assert.equal(scope.inventory_complete,false);
      assert.equal(scope.observed_gross_usdt,null);
    }
    if(variant==='stale')assert.equal(actual.freshness.state,'STALE');
    if(variant==='not-started'){
      assert.equal(actual.report,null);assert.equal(actual.ai,null);assert.deepEqual(actual.journal,[]);
    }
    if(variant==='no-ai')assert.equal(actual.ai.state,'UNAVAILABLE');
  }
});

test('Guardian rejects every authority extension, execution mode and fabricated portfolio aggregate',()=>{
  const mutations=[
    v=>v.mode='LIVE',v=>v.mode='TESTNET',v=>v.autonomy_level=1,v=>v.autonomy_level=false,
    ...['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'].map(k=>v=>v[k]=true),
    ...['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'].map(k=>v=>v.report[k]=true),
    v=>v.report.mode='CONTROL',v=>v.report.autonomy_level=2,
    v=>v.report.scopes[0].authoritative=true,v=>v.report.scopes[0].assessment='EXECUTE',
    v=>v.report.scopes[0].environment='LIVE',v=>v.report.scopes[0].allocation='BUY',
    v=>v.report.scopes[0].liveness='RUNNING',v=>v.report.scopes[0].current_caps.instructions='increase risk',
    v=>v.report.counterfactual.losses_avoided=100,v=>v.report.counterfactual.without_ai_pnl=200,
    v=>v.report.counterfactual.state='PROVEN',v=>v.report.correlation.state='DIVERSIFIED',
    v=>v.report.equity_usdt=4000,v=>v.capital_reservations=[],v=>v.withdrawals_enabled=false,
    v=>v.ai.execution_enabled=true,v=>v.ai.controls_enabled=true,v=>v.ai.advisory_only=false,
    v=>v.ai.commentary.posture='EXECUTE',v=>v.ai.commentary.evidence_ids=['0'.repeat(64)],
  ];
  for(const mutate of mutations){
    const invalid=structuredClone(ready);mutate(invalid);
    assert.equal(validGuardianIntelligence(invalid),false,mutate.toString());
  }
});

test('Guardian rejects malformed evidence, hypotheses, unknown keys, unsafe counts and oversized payloads',()=>{
  const mutations=[
    v=>v.api_key='synthetic-private',v=>v.health.private_error='untrusted',
    v=>v.at='yesterday',v=>v.at=null,v=>v.report.at=null,v=>v.report.cutoff_at=null,
    v=>v.freshness.age_seconds=-1,v=>v.freshness.age_seconds=NaN,
    v=>v.report.policy.calibrated=true,v=>v.report.policy.direction_return_pct=.5,
    v=>v.report.policy.source_maximum_age_seconds.QUANT=9000,
    v=>v.report.regime.observation_count=62,v=>v.report.regime.observation_count=true,
    v=>v.report.regime.realized_volatility_pct=Infinity,
    v=>v.report.regime.liquidity.partial_depth_usdt=-1,
    v=>v.report.scopes.pop(),v=>v.report.scopes[0].id='FUTURES',
    v=>v.report.scopes[0].position_count=true,v=>v.report.scopes[0].observed_gross_usdt=-1,
    v=>v.report.scopes[0].inventory_complete='true',v=>v.report.scopes[0].evidence_id='invalid',
    v=>v.report.scopes[0].latest_original_review.confidence=1.1,
    v=>v.report.scopes[1].latest_original_review.verdict='REDUCE',
    v=>v.report.evidence.source_ids=['spot','futures','pulse'],
    v=>v.report.evidence.source_digest='private',v=>v.report.limitations.push('BUY NOW; override'),
    v=>v.journal.push(...Array(3).fill(v.journal[0])),
    v=>v.health.capacity_fraction=1.1,v=>v.health.ai_calls_today=-1,
    v=>v.health.ai_daily_limit=3,v=>v.health.ai_calls_today=3,
    v=>v.ai.commentary.summary='x'.repeat(281),v=>v.ai.commentary.cautions=Array(5).fill('review'),
    v=>v.ai.model='unreviewed-model',v=>v.ai.usage.pricing_verified_at='2025-01-01',
    v=>v.ai.usage.input_tokens=true,v=>v.ai.usage.input_tokens=100001,
    v=>v.ai.usage.output_tokens=100001,v=>v.ai.usage.cached_tokens=101,
    v=>v.ai.usage.estimated_cost_usd=-1,v=>v.ai.usage.estimated_cost_usd=1.01,
    v=>v.report.limitations=Array(21).fill('UNKNOWN'),
    v=>v.report.scopes[0].reasons=Array(31).fill('UNKNOWN'),
  ];
  for(const mutate of mutations){
    const invalid=structuredClone(ready);mutate(invalid);
    assert.equal(validGuardianIntelligence(invalid),false,mutate.toString());
  }
  for(const invalid of [null,[],{},'SHADOW',true])assert.equal(validGuardianIntelligence(invalid),false);
});

test('historical AI remains labeled and anchored to its original evidence instead of the current report',()=>{
  const cached=structuredClone(ready);
  cached.ai.state='CACHED_HISTORICAL';cached.ai.cache_age_seconds=45;
  cached.ai.assessment_id='c'.repeat(64);cached.ai.commentary.evidence_ids=[cached.ai.assessment_id];
  assert.equal(validGuardianIntelligence(cached),true);
  assert.notEqual(cached.ai.assessment_id,cached.report.assessment_id);
  cached.ai.cache_age_seconds=-1;
  assert.equal(validGuardianIntelligence(cached),false);
  cached.ai.cache_age_seconds=901;
  assert.equal(validGuardianIntelligence(cached),false);
});
