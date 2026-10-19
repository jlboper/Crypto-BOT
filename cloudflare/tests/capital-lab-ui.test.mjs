import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {portal} from './helpers/portal-dom.mjs';
import {validCapitalLab} from '../src/capital-lab.mjs';

const emitted=new Map();
function produce(variant='ready'){
  if(!emitted.has(variant))emitted.set(variant,JSON.parse(execFileSync(process.env.PYTHON||'python',['-B',fileURLToPath(new URL('../../tests/emit_capital_lab_fixture.py',import.meta.url)),'--variant',variant],{encoding:'utf8'})));
  return structuredClone(emitted.get(variant));
}
const setup=options=>{const p=portal(options);return {...p,lab:p.window.CapitalLabPortal};};
const cases=p=>p.get('capitalLabCases').children.filter(node=>node.tagName==='ARTICLE');

test('Capital Lab is an independent closed fold in the existing Research Lab workspace with backward navigation',()=>{
  const p=setup({hash:'#capital-lab'});
  assert.equal(p.get('capital-lab').parentElement.id,'research-workspace');assert.equal(p.get('research-lab').parentElement.id,'research-workspace');
  assert.equal(p.get('capital-lab').open,true);assert.equal(p.get('research-lab').open,false);
  assert.deepEqual(p.root.querySelectorAll('[data-workspace]').filter(node=>!node.hidden).map(node=>node.dataset.workspace),['research-lab']);
  assert.equal(p.root.querySelectorAll('[data-workspace]').length,7);
  p.ui.navigate('portfolio-capital');p.ui.navigate('capital-lab');p.history.back();assert.equal(p.get('portfolio-capital').hidden,false);p.history.forward();assert.equal(p.get('capital-lab').open,true);
  assert.equal(p.ui.resolve('quant-statistical'),'trading-engines');assert.equal(p.calls.length,0);
  const closed=setup();assert.equal(closed.get('capital-lab').open,false);
});

test('Lab fold remembers only its allowed visibility preference and remains independent of existing historical research',async()=>{
  const p=setup({saved:{'capital-lab':true,'research-lab':false,'unknown-lab':true}});
  assert.equal(p.get('capital-lab').open,true);assert.equal(p.get('research-lab').open,false);
  p.get('capital-lab').open=false;await p.get('capital-lab').dispatch('toggle');
  const saved=JSON.parse(p.storage.get('crypto-ai-trader.ui.folds.v1'));assert.equal(saved['capital-lab'],false);assert.equal(saved['unknown-lab'],undefined);
});

test('real seven-recipe producer survives Worker validation and renders only synthetic cases without changing operating capital',()=>{
  const data=produce(),p=setup();assert.equal(validCapitalLab(data),true);assert.equal(p.lab.validWrapper(data),true);
  p.get('capitalReservations').textContent='NO INTEGRADAS · importe desconocido';p.get('guardianState').textContent='OBSERVER EXISTENTE';p.get('summarySpotCapital').textContent='CAPITAL EXISTENTE';
  p.lab.render({capital_lab:data});assert.equal(p.get('capitalLabState').textContent,'ENSAYOS CONFORMES');assert.equal(cases(p).length,7);
  for(const card of cases(p)){assert.match(card.textContent,/LAB SIM/);assert.match(card.textContent,/SHADOW sintético/);assert.match(card.textContent,/Estado observado.*Estado esperado/);}
  assert.match(p.get('capitalLabEvidence').textContent,new RegExp(data.report_id));assert.match(p.get('capitalLabEvidence').textContent,new RegExp(data.report_digest));
  assert.equal(p.get('capitalReservations').textContent,'NO INTEGRADAS · importe desconocido');assert.equal(p.get('guardianState').textContent,'OBSERVER EXISTENTE');assert.equal(p.get('summarySpotCapital').textContent,'CAPITAL EXISTENTE');
  assert.equal(p.get('capital-lab').querySelectorAll('button,input,select,form').length,0);assert.equal(p.calls.length,0);
});

test('micro-USDT formatting uses exact integer quotient and remainder rather than binary rounding',()=>{
  const {lab}=setup();
  for(const [value,expected] of [[0,'0.000000'],[1,'0.000001'],[-1,'−0.000001'],[1000001,'1.000001'],[-1000001,'−1.000001'],[9000000000000000,'9,000,000,000.000000'],[8999999999999999,'8,999,999,999.999999']])assert.equal(lab.formatUnits(value),expected+' USDT · LAB SIM');
  for(const value of [null,undefined])assert.equal(lab.formatUnits(value),'— · desconocido');
  for(const value of [true,false,1.5,NaN,Infinity,'1',9000000000000001,Number.MAX_SAFE_INTEGER+1])assert.equal(lab.formatUnits(value),'Contrato incompatible');
});

test('negative book, zero available, shortfall and realised losses remain separate and checks preserve their units',()=>{
  const p=setup();p.lab.render({capital_lab:produce()});
  const loss=p.get('capital-case-SIM_LOSS_SHORTFALL');assert.match(loss.textContent,/Valor contable sintético−204.000000 USDT/);assert.match(loss.textContent,/Libre con signo−204.000000/);assert.match(loss.textContent,/Disponible para reservas simuladas0.000000/);assert.match(loss.textContent,/Déficit204.000000/);assert.match(loss.textContent,/P&L realizado simulado−1,200.000000/);
  const pair=p.get('capital-case-SIM_ATOMIC_PAIR');assert.match(pair.textContent,/Piernas presentes.*Observado: 2 · contador simulado/);assert.doesNotMatch(pair.textContent,/Observado: 2.000000 USDT/);
  const partial=p.get('capital-case-SIM_PARTIAL_CANCEL');assert.match(partial.textContent,/0.400000 USDT/);assert.match(partial.textContent,/1.600000 USDT/);
});

test('a correctly interrupted real recipe shows FAILED and NOT_EVALUATED with an unknown book, never a fabricated zero wallet',()=>{
  const data=produce('failed'),p=setup();assert.equal(validCapitalLab(data),true);assert.equal(p.lab.validWrapper(data),true);p.lab.render({capital_lab:data});
  assert.equal(p.get('capitalLabState').textContent,'ENSAYOS CON FALLOS');assert.equal(cases(p).length,7);assert.match(p.get('capitalLabCases').textContent,/Libro desconocido/);assert.match(p.get('capitalLabCases').textContent,/NO EVALUADO/);assert.doesNotMatch(p.get('capitalLabCases').textContent,/Valor contable sintético0.000000/);assert.equal(p.calls.length,0);
});

test('missing, unrun and corrupt producer states clear previous results and preserve unknown amounts',()=>{
  const p=setup();for(const data of [null,{}, {capital_lab:null},{capital_lab:produce('not-run')},{capital_lab:produce('corrupt')}]){
    p.lab.render({capital_lab:produce()});p.lab.render(data);assert.equal(cases(p).length,0);assert.match(p.get('capitalLabCases').textContent,/desconocidos/);assert.doesNotMatch(p.get('capitalLabCases').textContent,/0.000000|1,000.000000|CONFORME/);assert.equal(p.get('capitalLabEvidence').textContent,'');
  }
  p.lab.render({capital_lab:produce('not-run')});assert.equal(p.get('capitalLabState').textContent,'SIN EJECUTAR');assert.doesNotMatch(p.get('capitalLabStatus').textContent,/Reporte fechado/);
  p.lab.render({capital_lab:produce('corrupt')});assert.equal(p.get('capitalLabState').textContent,'NO DISPONIBLE');
});

test('authority, real account scope and malformed bounded schema are incompatible rather than silently normalized',()=>{
  const changes=[v=>v.execution_enabled=true,v=>v.real_account_adapter=true,v=>v.synthetic=false,v=>v.autonomy_level=1,v=>v.controls_enabled=true,v=>v.mode='SHADOW',v=>v.scenarios[0].scope.scenario_environment='SPOT_TESTNET',v=>v.scenarios[0].scope.simulated_account_id='REAL_ACCOUNT',v=>v.scenarios[1].id=v.scenarios[0].id,v=>v.scenarios.push(v.scenarios[0]),v=>v.scenarios[0].checks.push(v.scenarios[0].checks[0]),v=>v.scenarios[0].checks.reverse(),v=>v.scenarios[0].book.reserved_units=-1,v=>v.scenarios[0].book.reserved_units='1',v=>v.scenarios[0].book.reserved_units=true,v=>v.scenarios[0].book.reserved_units=1.25,v=>v.scenarios[0].book.reserved_units=9000000000000001,v=>v.scenarios[0].book.extra=0,v=>v.report_id='wrong',v=>v.at='2026-10-19',v=>v.at=new Date(Date.now()+30000).toISOString(),v=>v.limitations=['x'.repeat(8100)]];
  const p=setup();for(const change of changes){const data=produce();change(data);p.lab.render({capital_lab:data});assert.equal(p.get('capitalLabState').textContent,'NO DISPONIBLE');assert.equal(cases(p).length,0);}
});

test('untrusted labels are never used as HTML, IDs and diagnostic strings do not execute or trigger requests',()=>{
  const p=setup(),data=produce();data.scenarios[0].label='<img src=x onerror="fetch(1)">';p.lab.render({capital_lab:data});
  assert.equal(p.get('capitalLabState').textContent,'NO DISPONIBLE');assert.doesNotMatch(p.get('capitalLabCases').innerHTML,/<img|onerror|fetch\(1\)/);
  const failed=produce(),row=failed.scenarios[0];row.checks[0].actual='<script>send()</script>';row.checks[0].matches=false;row.matches=false;row.state=failed.state='FAILED';
  assert.equal(validCapitalLab(failed),true);p.lab.render({capital_lab:failed});assert.equal(p.get('capitalLabState').textContent,'ENSAYOS CON FALLOS');assert.doesNotMatch(p.get('capitalLabCases').innerHTML,/<script>|send\(\)/);assert.equal(p.calls.length,0);
});

test('contradictory equity, allocations, available, shortfall and conservation flags cannot render a trusted synthetic book',()=>{
  const changes=[r=>r.book.book_equity_units++,r=>r.book.free_units_signed++,r=>r.book.available_units--,r=>r.book.shortfall_units++,r=>r.book.fees_paid_units++,r=>r.conservation_matches=false,r=>r.book=null];
  const p=setup();for(const change of changes){const data=produce();change(data.scenarios[0]);assert.equal(validCapitalLab(data),false);assert.equal(p.lab.validWrapper(data),false);p.lab.render({capital_lab:data});assert.equal(p.get('capitalLabState').textContent,'NO DISPONIBLE');assert.equal(cases(p).length,0);}
});

test('scenario and top-level results must agree with exact expected checks and recipe books',()=>{
  const changes=[v=>v.scenarios[0].matches=false,v=>v.scenarios[0].checks[0].matches=false,v=>{v.scenarios[0].checks[0].actual++;v.scenarios[0].checks[0].matches=false;v.scenarios[0].matches=false;},v=>v.state='FAILED',v=>{const r=v.scenarios[0];r.book.reserved_units--;r.book.free_units_signed++;r.book.available_units++;},v=>{const c=v.scenarios[0].checks[0];c.expected=c.actual=1;},v=>{v.scenarios[0].state='FAILED';v.state='FAILED';}];
  const p=setup();for(const change of changes){const data=produce();change(data);assert.equal(validCapitalLab(data),false);assert.equal(p.lab.validWrapper(data),false);p.lab.render({capital_lab:data});assert.equal(cases(p).length,0);}
});

test('policy values, types, limitations and recipe identity stay frozen to the same closed Worker contract',()=>{
  const changes=[v=>v.policy.balance_max_age_seconds='120',v=>v.policy.balance_max_age_seconds=121,v=>v.policy.max_active_requests=true,v=>v.policy.max_active_requests=11,v=>v.policy.approved_actor='SIM_OTHER',v=>v.policy.initial_balance_units++,v=>v.policy.strategy_limits[0][1]++,v=>v.limitations.pop(),v=>v.limitations.reverse(),v=>v.source_version.recipe_sha256='a'.repeat(64)];
  const {lab}=setup();for(const change of changes){const data=produce();change(data);assert.equal(validCapitalLab(data),false);assert.equal(lab.validWrapper(data),false);}
});

test('safe integer limit remains exact for a conserved failed outcome while one-micro contradictions are rejected',()=>{
  const p=setup(),data=produce(),row=data.scenarios[0],maximum=9000000000000000;
  row.book={book_equity_units:maximum,reserved_units:0,committed_units:0,free_units_signed:maximum,available_units:maximum,shortfall_units:0,fees_paid_units:0,realized_pnl_units:maximum-1000000000};row.matches=false;row.state=data.state='FAILED';
  assert.equal(validCapitalLab(data),true);assert.equal(p.lab.validWrapper(data),true);p.lab.render({capital_lab:data});assert.match(p.get('capital-case-SIM_ATOMIC_PAIR').textContent,/9,000,000,000.000000 USDT/);
  for(const key of ['book_equity_units','free_units_signed','available_units','realized_pnl_units']){const broken=structuredClone(data);broken.scenarios[0].book[key]--;assert.equal(validCapitalLab(broken),false);assert.equal(p.lab.validWrapper(broken),false);}
  const unsafe=structuredClone(data);unsafe.scenarios[0].book.book_equity_units=maximum+1;assert.equal(p.lab.validWrapper(unsafe),false);
});

test('dated research evidence is not treated as a stale trading engine and disconnected transport is clearly qualified',()=>{
  const data=produce(),p=setup();data.at='2026-01-01T00:00:00+00:00';p.lab.render({capital_lab:data});assert.equal(p.get('capitalLabState').textContent,'ENSAYOS CONFORMES');assert.match(p.get('capitalLabStatus').textContent,/Reporte fechado/);
  p.lab.render({capital_lab:data,remote_sync_stale:true});assert.match(p.get('capitalLabStatus').textContent,/sincronización antigua/);for(const card of cases(p))assert.match(card.textContent,/último reporte recibido/);
  p.lab.disconnected();assert.match(p.get('capitalLabStatus').textContent,/Portal sin conexión/);assert.equal(cases(p).length,7);
  p.lab.render(null);p.lab.disconnected();assert.equal(p.get('capitalLabState').textContent,'SIN CONEXIÓN');assert.equal(cases(p).length,0);
});

test('refresh preserves a case detail already opened and the lab has no network or execution controls',()=>{
  const p=setup(),data=produce();p.lab.render({capital_lab:data});p.get('capital-case-SIM_LOSS_SHORTFALL').open=true;p.lab.render({capital_lab:data});
  assert.equal(p.get('capital-case-SIM_LOSS_SHORTFALL').open,true);assert.equal(p.get('capital-case-SIM_ATOMIC_PAIR').open,false);assert.equal(p.calls.length,0);
  const source=readFileSync(new URL('../../web/app.js',import.meta.url),'utf8').split('const CapitalLabPortal = (() => {')[1].split('window.CapitalLabPortal=CapitalLabPortal;')[0];
  assert.doesNotMatch(source,/fetch\(|api\(|setInterval\(|method:\s*['"]POST/);
});

test('remote bridge exposes the optional same report and remote staleness without any new endpoint or POST',async()=>{
  const source=readFileSync(new URL('../../web/portal-bridge.js',import.meta.url),'utf8');
  for(const report of [produce(),null]){
    const node=()=>({textContent:'',hidden:false,disabled:false,dataset:{},classList:{add(){},remove(){},toggle(){}},replaceChildren(){},append(){},setAttribute(){}});
    const calls=[],window={addEventListener(){},dispatchEvent(){}},document={addEventListener(){},getElementById:node,createElement:node,querySelector:node};
    const context=vm.createContext({window,document,location:{hostname:'portal.example.workers.dev',hash:''},structuredClone,Date,setTimeout,console,fetch:async(path,options)=>{calls.push({path,options});return {ok:true,status:200,json:async()=>({stale:true,csrf:'synthetic',snapshot:{dashboard:report?{capital_lab:report}:{}},commands:[],jobs:[]})};}});
    vm.runInContext(source,context);const result=await window.portalApi('/api/platform');assert.equal(result.remote_sync_stale,true);assert.deepEqual(result.capital_lab,report);assert.equal(calls.length,1);assert.equal(calls[0].path,'/v1/status');assert.notEqual(calls[0].options?.method,'POST');
  }
});
