import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {validLivePreparation} from '../src/live-preparation.mjs';
import {portal} from './helpers/portal-dom.mjs';

const repo=fileURLToPath(new URL('../../',import.meta.url));
const source=fs.readFileSync(new URL('../../web/live-preparation.js',import.meta.url),'utf8');
const css=fs.readFileSync(new URL('../../web/portal.css',import.meta.url),'utf8');
const markup=fs.readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
const python='import json,sys;sys.path.insert(0,sys.argv[1]);from tests.test_live_preparation import report;print(json.dumps(report(proposal={"schema":1,"amount_usd":"100"})))';
const produced=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',python,repo],{encoding:'utf8'}));
const fixture=()=>structuredClone(produced);
const current=()=>{const value=fixture();value.at=new Date().toISOString();value.engines[1].budget.at=value.at;return value;};
const view=()=>{const p=portal();vm.runInContext(source,p.context);return {...p,live:p.context.CryptoLivePreparation};};

test('Python produces the identical closed browser and Worker preparation contract',()=>{
  const value=fixture();
  assert.equal(validLivePreparation(value),true);
  assert.equal(globalThis.CryptoLivePreparation.valid(value),true);
  assert.equal(Buffer.byteLength(JSON.stringify(value),'utf8')<8000,true);
  assert.deepEqual(value.engines.map(row=>row.id),['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE']);
  assert.equal(value.capital_proposal.amount_usd,'100');
  assert.equal(value.engines[1].budget.inclusive_stop_risk_usdt,'9.308');
});

test('authority, ready labels, extra fields and altered central gates cannot pass the validator',()=>{
  const mutations=[x=>x.state='READY',x=>x.schema=true,x=>x.mode='LIVE',x=>x.engine='GUARDIAN',x=>x.autonomy_level=1,x=>x.observation_days_required=29,
    ...['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed','automatic_activation'].map(key=>x=>x[key]=true),
    x=>x.extra='untrusted',x=>x.financial_authority=false,x=>x.blockers.pop(),x=>x.blockers.reverse(),x=>x.blockers[0]='APPROVED',
    x=>x.engines[0].state='CERTIFIED',x=>x.engines[0].extra=false,x=>x.capital_proposal.extra=false,x=>x.engines[0].qualified_days=30,x=>x.engines[0].qualified_state='QUALIFIED'];
  for(const mutate of mutations){const value=fixture();mutate(value);assert.equal(validLivePreparation(value),false);}
});

test('timestamps require an exact real UTC millisecond instant and budget cannot postdate its cut',()=>{
  for(const at of ['today','2026-02-30T20:35:00.000Z','2026-10-21T25:35:00.000Z','2026-10-21T20:35:00','2026-10-21T20:35:00.000+00:00','2026-10-21T20:35:00Z','2026-10-21T20:35:00.000Z\n']){
    const value=fixture();value.at=at;assert.equal(validLivePreparation(value),false,at);
  }
  const value=fixture();value.engines[1].budget.at='2026-10-21T20:35:00.001Z';assert.equal(validLivePreparation(value),false);
});

test('proposal is explicit, canonical, positive, bounded USD and never supplies a risk policy',()=>{
  for(const amount of [100,NaN,Infinity,true,'0','-1','01','100.00','1e2','NaN','Infinity','0.001','1000000000.01','1000000001','<img src=x>','1'.repeat(9000)]){
    const value=fixture();value.capital_proposal.amount_usd=amount;assert.equal(validLivePreparation(value),false,String(amount).slice(0,30));
  }
  for(const mutate of [x=>x.capital_proposal.status='ALLOCATED',x=>x.capital_proposal.status='NOT_PROVIDED',x=>x.capital_proposal.daily_loss_limit_usd='1',x=>x.capital_proposal.max_drawdown_pct=5]){
    const value=fixture();mutate(value);assert.equal(validLivePreparation(value),false);
  }
  for(const amount of ['0.01','100.1','1000000000']){const value=fixture();value.capital_proposal.amount_usd=amount;assert.equal(validLivePreparation(value),true);}
});

test('four environments remain segregated and unknown spans never become certified days',()=>{
  for(const mutate of [x=>x.engines.reverse(),x=>x.engines[0].environment='LIVE',x=>x.engines[1].environment='SPOT_TESTNET',x=>x.engines[2].environment='PAPER',
    x=>x.engines[0].reported_span_days=NaN,x=>x.engines[0].reported_span_days=Infinity,x=>x.engines[0].reported_span_days=true,x=>x.engines[0].reported_span_days=-1,x=>x.engines[0].reported_span_days=36501,
    x=>x.engines[0].reported_span_days=0,x=>x.engines[0].reported_span_days=null,x=>x.engines[0].span_gate='READY',x=>x.engines[2].protection='ARMED',x=>x.engines[0].blockers=[]]){
    const value=fixture();mutate(value);assert.equal(validLivePreparation(value),false);
  }
  const value=fixture();value.engines[0].environment='PAPER';value.engines[0].protection='NOT_APPLICABLE';assert.equal(validLivePreparation(value),true);
});

test('native Futures budget uses exact USDT decimals and its breach cannot be relabelled away',()=>{
  for(const mutate of [x=>x.engines[1].budget.state='WITHIN_OBSERVED_LIMIT',x=>x.engines[1].budget.inclusive_stop_risk_usdt='7.5',x=>x.engines[1].budget.stop_risk_limit_usdt='0',
    x=>x.engines[1].budget.inclusive_stop_risk_usdt=9.308,x=>x.engines[1].budget.inclusive_stop_risk_usdt='NaN',x=>x.engines[1].budget.inclusive_stop_risk_usdt='1e2',
    x=>x.engines[1].budget.inclusive_stop_risk_usdt='0.0000000000001',x=>x.engines[1].budget.inclusive_stop_risk_usdt='1000000000000.000000000001',
    x=>x.engines[1].budget.inclusive_stop_risk_usdt='09.308',x=>x.engines[1].budget.inclusive_stop_risk_usdt='9.3080',x=>x.engines[1].budget.inclusive_stop_risk_usd='9.308',
    x=>x.engines[0].budget=structuredClone(x.engines[1].budget),x=>x.engines[0].budget.at=x.at]){
    const value=fixture();mutate(value);assert.equal(validLivePreparation(value),false);
  }
  const value=fixture();value.engines[1].budget.inclusive_stop_risk_usdt='7.500000000001';assert.equal(validLivePreparation(value),true);
  value.engines[1].budget.inclusive_stop_risk_usdt='7.5';value.engines[1].budget.state='WITHIN_OBSERVED_LIMIT';value.engines[1].blockers=value.engines[1].blockers.filter(code=>code!=='ENGINE_BUDGET_EXCEEDED');assert.equal(validLivePreparation(value),true);
});

test('readonly preparation renders four blocked cards, USD proposal and the preserved Demo USDT breach',()=>{
  const p=view();p.live.render(current());
  assert.equal(p.get('livePreparationState').textContent,'LIVE BLOQUEADO · SOLO LECTURA');
  assert.equal(p.get('livePreparationCapital').textContent,'100 USD propuestos');
  assert.equal(p.get('livePreparationBlockers').textContent,'10 pendientes');
  assert.equal(p.get('livePreparationEngines').querySelectorAll('article').length,4);
  const text=p.get('livePreparationEngines').textContent;
  assert.match(text,/Spot Testnet.*Futures Demo.*Shadow.*Shadow/s);
  assert.match(text,/9\.308 \/ 7\.5 USDT/);assert.match(text,/Presupuesto nativo Demo.*Superado/s);
  assert.match(text,/30 días · solo intervalo, sin certificar/);assert.match(text,/Días válidos certificadosDesconocidos/);
  assert.equal(p.get('livePreparationEngines').querySelectorAll('details').length,4);
  assert.equal(p.get('live-preparation').querySelectorAll('button,input,select,form').length,0);
  assert.equal(p.get('livePreparationGates').querySelectorAll('article').length,10);
  assert.equal(p.calls.length,0);
});

test('an absent proposal is never inferred from the planning panel or exchange units',()=>{
  const p=view(),value=current();value.capital_proposal.amount_usd=null;value.capital_proposal.status='NOT_PROVIDED';
  p.live.render(value);
  assert.equal(p.get('livePreparationCapital').textContent,'Sin propuesta verificable');
  assert.doesNotMatch(p.get('livePreparationCapital').textContent,/100|USDT/);
  assert.match(p.get('livePreparationCapitalNote').textContent,/No hay capital asignado/);
});

test('refresh preserves independently opened conditions so a new cut does not interrupt reading',()=>{
  const p=view();p.live.render(current());
  p.get('livePreparationConditionsFUTURES').open=true;p.live.render(current());
  assert.equal(p.get('livePreparationConditionsFUTURES').open,true);
  assert.equal(p.get('livePreparationConditionsSPOT').open,false);
  assert.equal(p.get('livePreparationConditionsAI_MARKET_PULSE').open,false);
  assert.equal(p.get('livePreparationConditionsQUANT_ARBITRAGE').open,false);
  p.get('livePreparationConditionsFUTURES').open=false;p.live.render(current());assert.equal(p.get('livePreparationConditionsFUTURES').open,false);
  assert.equal(p.calls.length,0);
});

test('an entirely unknown Python evaluation remains valid and near-thirty spans are not rounded into thirty days',()=>{
  const empty='import json,sys;sys.path.insert(0,sys.argv[1]);from trader.live_preparation import evaluate_live_preparation;print(json.dumps(evaluate_live_preparation({})))';
  const value=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',empty,repo],{encoding:'utf8'}));
  assert.equal(validLivePreparation(value),true);
  const p=view();p.live.render(value);assert.match(p.get('livePreparationEngines').textContent,/Intervalo registradoDesconocido/);
  const near=current();near.engines[0].reported_span_days=29.999;near.engines[0].span_gate='BELOW_30_DAYS';near.engines[0].blockers.splice(1,0,'OBSERVATION_SPAN_INSUFFICIENT');
  assert.equal(validLivePreparation(near),true);p.live.render(near);assert.match(p.get('livePreparationEngines').textContent,/29\.999 días · inferior a 30 días/);
});

test('a new report timestamp does not turn stale or unknown motor sources into healthy data',()=>{
  const value=current(),p=view();
  value.engines[0].freshness='STALE';value.engines[0].blockers.splice(1,0,'SOURCE_STALE');
  value.engines[2].freshness='UNKNOWN';value.engines[2].blockers.splice(1,0,'SOURCE_UNKNOWN');
  assert.equal(validLivePreparation(value),true);p.live.render(value);
  assert.equal(p.get('livePreparationState').textContent,'LIVE BLOQUEADO · SOLO LECTURA');
  assert.match(p.get('livePreparationEngines').textContent,/Fuente atrasada/);
  assert.match(p.get('livePreparationEngines').textContent,/Frescura de fuente desconocida/);
  assert.doesNotMatch(p.get('livePreparationEngines').textContent,/LISTO|READY|CERTIFICADO|LIVE HABILITADO/);
});

test('old cuts, a future clock and remote synchronization failure mark all shown figures historical',()=>{
  const p=view();
  for(const offset of [-91000,6000]){
    const value=current();value.at=new Date(Date.now()+offset).toISOString();value.engines[1].budget.at=value.at;
    p.live.render(value);assert.match(p.get('livePreparationState').textContent,/CORTE NO VIGENTE/);assert.match(p.get('livePreparationNote').textContent,/no describen el estado actual/);
    assert.equal(p.get('livePreparationEngines').querySelectorAll('.live-preparation-history').length,4);
  }
  p.live.render(current(),true);assert.match(p.get('livePreparationState').textContent,/CORTE NO VIGENTE/);
  assert.match(p.get('livePreparationEngines').textContent,/9\.308 \/ 7\.5 USDT/);
});

test('missing, malformed or disconnected readings remove all earlier figures without provider requests',()=>{
  const p=view();
  for(const next of [null,{...current(),controls_enabled:true},{...current(),at:'<script>alert(1)</script>'}]){
    p.live.render(current());p.live.render(next);
    assert.equal(p.get('livePreparationEngines').textContent,'');assert.equal(p.get('livePreparationGates').textContent,'');assert.equal(p.get('livePreparationCapital').textContent,'Sin propuesta verificable');
    assert.doesNotMatch(p.get('livePreparationNote').innerHTML,/<script|<img/);
  }
  p.live.render(current());p.live.disconnected();
  assert.equal(p.get('livePreparationEngines').textContent,'');assert.match(p.get('livePreparationNote').textContent,/no permite inferir una caída/);assert.equal(p.calls.length,0);
});

test('external text is refused rather than interpreted as a label, instruction or DOM markup',()=>{
  const p=view(),value=current();value.engines[0].blockers[0]='<img src=x onerror=alert(1)>';assert.equal(validLivePreparation(value),false);p.live.render(value);
  assert.equal(p.get('livePreparationEngines').textContent,'');assert.equal(p.get('live-preparation').querySelectorAll('img,script').length,0);assert.equal(p.calls.length,0);
});

test('shared markup loads the module once before app, deep links to the visible System workspace and folds detail',()=>{
  assert.equal([...markup.matchAll(/src="\/live-preparation\.js"/g)].length,1);
  assert.equal(markup.indexOf('src="/live-preparation.js"')<markup.indexOf('src="/app.js"'),true);
  const p=portal({hash:'#live-preparation'});
  assert.equal(p.get('system-settings').hidden,false);assert.equal(p.get('live-preparation').open,true);assert.equal(p.get('modelSettingsPanel').hidden,true);
  assert.equal(p.get('live-preparation').tagName,'DETAILS');assert.equal(p.get('live-preparation').querySelector('.live-preparation-checklist').open,false);
  assert.ok(p.get('command-center').querySelector('a[href="#live-preparation"]'));
});

test('responsive rules keep preparation cards in a single mobile column and allow long values to wrap',()=>{
  assert.match(css,/@media\(max-width:640px\)\{\.live-preparation-overview,\.live-preparation-engines,\.live-preparation-gates\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/\.live-preparation-engine\{min-width:0;overflow-wrap:anywhere\}/);
  assert.match(css,/\.live-preparation-engine summary[^}]*min-height:44px/);
  // Layout assertions supplement the shipped DOM; they are not a browser geometry benchmark.
});
