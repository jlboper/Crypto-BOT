import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {validCapitalLab} from '../src/capital-lab.mjs';
function produce(variant='ready'){
 return JSON.parse(execFileSync(process.env.PYTHON||'python',[
  fileURLToPath(new URL('../../tests/emit_capital_lab_fixture.py',import.meta.url)),'--variant',variant],{encoding:'utf8',timeout:20000}));
}
const ready=produce();
test('real integrated protocol Lab is bounded, exact and exclusively synthetic',()=>{
 assert.equal(validCapitalLab(ready),true);
 assert.equal(ready.state,'PASSED');assert.equal(ready.mode,'RESEARCH_ONLY');
 assert.equal(ready.scenarios.length,7);assert.ok(Buffer.byteLength(JSON.stringify(ready))<8000);
 assert.equal(ready.scenarios[6].book.book_equity_units,-204000000);
 assert.equal(ready.scenarios[4].book.reserved_units,1600000);
 assert.equal(ready.execution_enabled,false);assert.equal(ready.real_account_adapter,false);
 assert.equal(ready.equity,undefined);
 for(const row of ready.scenarios){assert.equal(row.scope.scenario_environment,'SHADOW');assert.equal(row.scope.currency,'USDT');assert.equal(row.matches,true);}
});
test('actual failed, absent and corrupt producer states have strict honest schemas',()=>{
 for(const [variant,state] of [['failed','FAILED'],['not-run','NOT_RUN'],['corrupt','UNAVAILABLE']]){
  const actual=produce(variant);assert.equal(actual.state,state);assert.equal(validCapitalLab(actual),true,variant);
  if(variant==='failed')for(const row of actual.scenarios){assert.equal(row.book,null);assert.ok(row.checks.every(c=>c.actual==='NOT_EVALUATED'&&!c.matches));}
  else{assert.equal(actual.policy,null);assert.equal(actual.report_id,null);assert.deepEqual(actual.scenarios,[]);}
 }
});
test('Lab rejects execution authority, account ambiguity and unknown policy fields',()=>{
 const changes=[v=>v.mode='SHADOW',v=>v.mode='LIVE',v=>v.synthetic=false,v=>v.execution_enabled=true,
  v=>v.real_account_adapter=true,v=>v.autonomy_level=false,v=>v.autonomy_level=1,v=>v.schema=true,
  v=>v.controls_enabled=false,v=>v.equity=7000,v=>v.reservations_enabled=true,
  v=>v.policy.initial_balance_units=2000000000,v=>v.policy.approved_actor='OWNER',v=>v.policy.risk=1,
  v=>v.scenarios[0].scope.scenario_environment='SPOT_TESTNET',v=>v.scenarios[0].scope.simulated_account_id='REAL_ACCOUNT',
  v=>v.scenarios[0].scope.currency='USDC',v=>v.scenarios[0].controls_enabled=false];
 for(const change of changes){const value=structuredClone(ready);change(value);assert.equal(validCapitalLab(value),false,change.toString());}
});
test('strict Lab checks reject cardinality, order, arbitrary fields and financial corruption even in FAILED reports',()=>{
 const changes=[v=>v.scenarios[0].checks.push({unexpected:'synthetic-private'}),v=>v.scenarios[0].checks.pop(),
  v=>v.scenarios[0].checks.reverse(),v=>v.scenarios[0].checks[0].private='synthetic-private',
  v=>v.scenarios.pop(),v=>v.scenarios.push(v.scenarios[0]),v=>v.scenarios[0].id='SIM_OTHER',
  v=>v.scenarios[0].book.reserved_units=true,v=>v.scenarios[0].book.reserved_units=0,
  v=>v.scenarios[0].book.free_units_signed=.1,v=>v.scenarios[0].book.book_equity_units=9007199254740992,
  v=>v.scenarios[0].book.fees_paid_units=-1,v=>v.scenarios[0].book.secret='private',
  v=>v.scenarios[0].checks[0].actual='x'.repeat(101),v=>v.scenarios[0].record_id='exchange-order',
  v=>v.source_version.recipe_sha256='0'.repeat(64),v=>v.source_version.secret='private',
  v=>v.at=null,v=>v.report_id='../../financial.db',v=>v.report_digest='bad',v=>v.limitations.pop()];
 for(const change of changes){
  const value=structuredClone(ready);value.state=value.scenarios[0].state='FAILED';value.scenarios[0].matches=false;
  change(value);assert.equal(validCapitalLab(value),false,change.toString());
 }
 for(const value of [null,{},[],true,'PASSED'])assert.equal(validCapitalLab(value),false);
});
