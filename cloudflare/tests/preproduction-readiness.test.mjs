import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {validPreproductionReadiness} from '../src/preproduction-readiness.mjs';
import {portal} from './helpers/portal-dom.mjs';

const code=fs.readFileSync(new URL('../../web/preproduction-readiness.js',import.meta.url),'utf8');
const produced=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8',fileURLToPath(new URL('../../tests/emit_preproduction_fixture.py',import.meta.url))],{encoding:'utf8'}));
const fixture=()=>structuredClone(produced);
const view=()=>{const p=portal();vm.runInContext(code,p.context);return {...p,preproduction:p.context.CryptoPreproduction};};

test('Python projection has closed shared contract with five packages and no authority',()=>{
  const value=fixture();assert.equal(validPreproductionReadiness(value),true);assert.equal(value.packages.length,5);
  assert.equal(value.owner_authorization,false);assert.equal(value.execution_enabled,false);
  assert.equal(Buffer.byteLength(JSON.stringify(value))<8000,true);
});

test('Python and JS validators agree on authority, time, unknown, counts and closed nested fields',()=>{
  const cases=[fixture()];
  for(const mutate of [x=>x.execution_enabled=true,x=>x.owner_authorization=true,x=>x.schema=true,x=>x.mode='LIVE',x=>x.ready_for_live=true,x=>x.connection.scopes[0].api_key='secret',x=>x.connection.scopes[0].permissions='VERIFIED',x=>x.connection.state='READ_ONLY_VERIFIED',x=>x.connection.scopes.reverse(),x=>x.packages[0].state='LIVE_READY',x=>x.packages.pop(),x=>x.blockers=[],x=>x.at='2026-02-30T00:00:00.000Z',x=>x.source_version='01.10.54',x=>x.blockers=['OWNER_ACTIVATION_REQUIRED','OWNER_ACTIVATION_REQUIRED']]){const value=fixture();mutate(value);cases.push(value);}
  const repo=fileURLToPath(new URL('../../',import.meta.url));
  const script='import json,sys;sys.path.insert(0,sys.argv[1]);from trader.preproduction_status import valid_preproduction_status;print(json.dumps([valid_preproduction_status(x) for x in json.load(sys.stdin)]))';
  const expected=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',script,repo],{encoding:'utf8',input:JSON.stringify(cases)}));
  assert.deepEqual(cases.map(validPreproductionReadiness),expected);
});

test('invalid or absent evidence clears previous display and never sends an action',()=>{
  const p=view();p.preproduction.render(fixture());assert.match(p.get('preproductionPackages').textContent,/Evidencia y continuidad/);
  p.preproduction.render({...fixture(),owner_authorization:true});assert.equal(p.get('preproductionPackages').textContent,'');
  assert.match(p.get('preproductionNote').textContent,/incompatible/);p.preproduction.render(null);assert.match(p.get('preproductionNote').textContent,/Sin informe/);
  assert.equal(p.calls.length,0);assert.equal(p.get('preproduction-readiness').querySelectorAll('button,input,select,form').length,0);
});

test('local coverage and financial receipt days remain distinct without certification',()=>{
  const value=fixture();value.cohort={state:'OBSERVING',scopes:[{engine:'SPOT',environment:'SPOT_TESTNET',state:'OBSERVING_LOCAL',registered_at:value.at,starts_at:value.at,last_capture_at:value.at,source_at:value.at,source_complete:true,stale:false,operational_days:30,qualified_days:null,missing_windows:0}]};
  assert.equal(validPreproductionReadiness(value),true);const p=view();p.preproduction.render(value);
  assert.match(p.get('preproductionCohorts').textContent,/operativa local30/);assert.match(p.get('preproductionCohorts').textContent,/financieros completosDesconocidos/);
  assert.match(p.get('preproductionState').textContent,/LIVE BLOQUEADO/);assert.equal(p.calls.length,0);
  value.cohort.scopes[0].qualified_days=31;assert.equal(validPreproductionReadiness(value),false);
});

test('historical account cut is visible and remote freshness is separate',()=>{
  const value=fixture();value.connection.state='READ_ONLY_VERIFIED';value.connection.at=value.at;
  for(const row of value.connection.scopes){row.identity='REPORTED';row.at=value.at;}
  const p=view();p.preproduction.render(value,true);assert.match(p.get('preproductionConnection').textContent,/corte histórico/);
  assert.match(p.get('preproductionConnection').textContent,/sin autorización de órdenes/);assert.match(p.get('preproductionNote').textContent,/Sincronización remota atrasada/);
  p.preproduction.disconnected();assert.equal(p.get('preproductionPackages').textContent,'');assert.match(p.get('preproductionNote').textContent,/no demuestra una caída/);
});

test('hash navigation reaches one collapsed shared panel and mobile layout uses one column',()=>{
  const p=portal({hash:'#preproduction-readiness'});assert.equal(p.get('system-settings').hidden,false);assert.equal(p.get('preproduction-readiness').open,true);
  const css=fs.readFileSync(new URL('../../web/portal.css',import.meta.url),'utf8');assert.match(css,/@media\(max-width:640px\)\{\.preproduction-packages,\.preproduction-grid\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/\.preproduction-card\{min-width:0;overflow-wrap:anywhere/);
  const markup=fs.readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
  assert.equal([...markup.matchAll(/src="\/preproduction-readiness\.js"/g)].length,1);
});
