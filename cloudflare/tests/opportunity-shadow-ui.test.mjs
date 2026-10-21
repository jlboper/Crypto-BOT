import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {portal} from './helpers/portal-dom.mjs';

const contract=readFileSync(new URL('../../web/opportunity-contract.js',import.meta.url),'utf8');
const source=readFileSync(new URL('../../web/opportunity-ui.js',import.meta.url),'utf8');
const cache=new Map();
function produce(variant='ready'){
  if(!cache.has(variant))cache.set(variant,JSON.parse(execFileSync(process.env.PYTHON||'python',
    [fileURLToPath(new URL('../../tests/emit_opportunity_fixture.py',import.meta.url)),'--variant',variant],
    {encoding:'utf8',maxBuffer:30000})));
  return structuredClone(cache.get(variant));
}
function setup(){
  const p=portal({hash:'#opportunity-shadow'});
  vm.runInContext(contract,p.context);
  p.window.CryptoOpportunityContract=p.context.CryptoOpportunityContract;
  vm.runInContext(source,p.context);
  return {...p,observer:p.window.OpportunityShadowPortal};
}
test('same shared validator renders real producer, separates scopes and keeps entry versus outcome explicit',()=>{
  const p=setup(),v=produce();p.observer.render({opportunity_shadow:v});
  assert.equal(p.get('opportunityState').textContent,'OBSERVANDO');
  assert.equal(p.get('opportunityCoverage').querySelectorAll('article').length,4);
  assert.equal(p.get('opportunityScopes').querySelectorAll('article').length,v.scopes.length);
  assert.equal(p.get('opportunityRecords').querySelectorAll('article').length,v.recent_records.length);
  assert.match(p.get('opportunityScopes').textContent,/Identidad sin verificar/);
  assert.match(p.get('opportunityRecords').textContent,/admisión efectiva no evaluable/);
  assert.match(p.get('opportunityHealth').textContent,/capacidad: AVAILABLE/);
  const partial=produce('partial');p.observer.render({opportunity_shadow:partial});
  assert.match(p.get('opportunityHealth').textContent,/OBSERVATION_FAILED/);
  assert.equal(p.calls.length,0);
});
test('new disclosures resolve to Guardian and do not change existing controls or workspaces',()=>{
  const p=setup();
  for(const id of ['opportunity-shadow','opportunity-capital','opportunity-decisions']){
    assert.equal(p.ui.navigate(id,{scroll:false}),true);
    assert.equal(p.get(id).open,true);
    assert.equal(p.get('guardian-ai').hidden,false);
    assert.equal(p.get('trading-engines').hidden,true);
  }
  assert.equal(p.root.querySelectorAll('[data-workspace]').length,7);
  for(const id of ['pauseFuturesForward','killButton','pauseMarketPulse','pauseQuant'])assert.ok(p.get(id));
  assert.equal(p.get('opportunity-shadow').querySelectorAll('button').length,0);
});
test('absence, healthy idleness and unknown money keep distinct honest states',()=>{
  const p=setup();p.observer.render({});
  assert.equal(p.get('opportunityState').textContent,'SIN EVIDENCIA');
  p.observer.render({opportunity_shadow:produce('not-started')});
  assert.equal(p.get('opportunityState').textContent,'NO INICIADO');
  p.observer.render({opportunity_shadow:produce('idle')});
  assert.equal(p.get('opportunityState').textContent,'ESPERANDO PROPUESTAS');
  assert.match(p.get('opportunityStatus').textContent,/no implica un error/);
  assert.match(p.get('opportunityRecords').textContent,/Sin propuestas/);
  assert.match(p.get('opportunityRecords').textContent,/Selección reciente: 0 de 0 registros/);
  assert.equal(p.get('opportunityScopes').querySelectorAll('article').length,0);
});

test('a nonempty journal without recent detail never claims no proposals or changes aggregate counters',()=>{
  const p=setup(),v=produce();
  assert.ok(v.health.records>0);
  v.recent_records=[];
  assert.equal(p.window.CryptoOpportunityContract.validOpportunityShadow(v),true);
  const before=structuredClone(v);
  p.observer.render({opportunity_shadow:v});
  assert.equal(p.get('opportunityState').textContent,'OBSERVANDO');
  assert.match(p.get('opportunityRecords').textContent,new RegExp('Selección reciente: 0 de '+v.health.records+' registros'));
  assert.match(p.get('opportunityRecords').textContent,/esta lectura no incluye detalle reciente/);
  assert.doesNotMatch(p.get('opportunityRecords').textContent,/Sin propuestas recibidas|presupuesto|tamaño|recortado|pérdida del journal/);
  assert.equal(p.get('opportunityRecords').querySelectorAll('article').length,0);
  assert.match(p.get('opportunityMetrics').textContent,new RegExp('Registros'+v.health.records));
  assert.deepEqual(v,before);
  assert.equal(p.calls.length,0);
});

test('a bounded recent prefix states its selection size without claiming a cause or a full history',()=>{
  const p=setup(),v=produce();
  assert.ok(v.recent_records.length>2&&v.health.records>2);
  v.recent_records=v.recent_records.slice(0,2);
  assert.equal(p.window.CryptoOpportunityContract.validOpportunityShadow(v),true);
  const before=structuredClone(v);
  p.observer.render({opportunity_shadow:v});
  assert.match(p.get('opportunityRecords').textContent,new RegExp('Selección reciente: 2 de '+v.health.records+' registros'));
  assert.equal(p.get('opportunityRecords').querySelectorAll('article').length,2);
  assert.doesNotMatch(p.get('opportunityRecords').textContent,/Sin propuestas recibidas|presupuesto de sincronización|recortado por/);
  assert.match(p.get('opportunityRecords').textContent,/admisión efectiva no evaluable/);
  assert.deepEqual(v,before);
  assert.equal(p.calls.length,0);
});

test('an unknown journal total remains distinct from a genuinely empty journal',()=>{
  const p=setup();p.observer.render({opportunity_shadow:produce('not-started')});
  assert.match(p.get('opportunityRecords').textContent,/total del journal desconocido/);
  assert.match(p.get('opportunityRecords').textContent,/actividad total del journal no está confirmada/);
  assert.doesNotMatch(p.get('opportunityRecords').textContent,/Sin propuestas recibidas|0 de 0/);
  p.observer.render({opportunity_shadow:produce('idle')});
  assert.match(p.get('opportunityRecords').textContent,/Selección reciente: 0 de 0 registros/);
  assert.match(p.get('opportunityRecords').textContent,/Sin propuestas recibidas/);
});
test('every authority extension, injected unknown field and malformed numeric result fails closed',()=>{
  const changes=[v=>v.controls_enabled=true,v=>v.reservations_enabled=true,v=>v.autonomy_level=1,
    v=>v.mode='LIVE',v=>v.extra='synthetic',v=>v.recent_records[0].assessment.real_admission='ALLOW',
    v=>v.recent_records[0].assessment.estimated_costs='NaN',v=>v.coverage[0].engine='<script>unsafe()</script>'];
  for(const change of changes){const p=setup(),v=produce();change(v);p.observer.render({opportunity_shadow:v});
    assert.equal(p.get('opportunityState').textContent,'SIN EVIDENCIA');
    assert.equal(p.get('opportunityRecords').querySelectorAll('article').length,0);
    assert.doesNotMatch(p.get('opportunityRecords').innerHTML,/<script>|unsafe/);
    assert.equal(p.calls.length,0);}
});
test('disconnection and stale remote transport never present retained evidence as current',()=>{
  const p=setup();p.observer.render({opportunity_shadow:produce(),remote_sync_stale:true});
  assert.equal(p.get('opportunityState').textContent,'LECTURA ANTERIOR');
  assert.match(p.get('opportunityStatus').textContent,/Sincronización antigua/);
  p.observer.disconnected();assert.match(p.get('opportunityStatus').textContent,/actividad actuales desconocidas/);
  assert.ok(p.get('opportunityRecords').querySelectorAll('article').length>0);
  p.observer.render(null);p.observer.disconnected();
  assert.equal(p.get('opportunityState').textContent,'SIN CONEXIÓN');
  assert.doesNotMatch(source,/fetch\(|setInterval\(|portalApi|method:\s*['"]POST/);
});
test('new web dependencies are included once before app in local and remote build',()=>{
  const markup=readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
  const build=readFileSync(new URL('../../scripts/build_unified_portal.py',import.meta.url),'utf8');
  for(const name of ['opportunity-contract.js','opportunity-ui.js']){
    assert.equal(markup.split('src="/'+name+'"').length-1,1);
    assert.ok(markup.indexOf('src="/'+name+'"')<markup.indexOf('src="/app.js"'));
    assert.ok(build.includes("'"+name+"'"));
  }
});
