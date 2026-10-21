import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {portal} from './helpers/portal-dom.mjs';

const contract=readFileSync(new URL('../../web/opportunity-contract.js',import.meta.url),'utf8');
const stamp=()=>new Date().toISOString();
const python=process.env.PYTHON||'python';
const fixtures=new Map();
function produce(name){
  if(!fixtures.has(name))fixtures.set(name,JSON.parse(execFileSync(python,
    [fileURLToPath(new URL(`../../tests/${name}.py`,import.meta.url))],{encoding:'utf8',maxBuffer:100000})));
  return structuredClone(fixtures.get(name));
}
function setup(){
  const p=portal({hash:'#intelligence-queries'});
  vm.runInContext(contract,p.context);
  p.window.CryptoOpportunityContract=p.context.CryptoOpportunityContract;
  return p;
}
function portfolio(){
  const at=stamp();
  return {schema:1,engine:'PORTFOLIO_GUARDIAN',mode:'OBSERVER',state:'OBSERVING',at,
    controls_enabled:false,can_veto:false,execution_enabled:false,
    scopes:['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'].map((id,index)=>({
      id,engine:id,environment:['SPOT_TESTNET','FUTURES_DEMO','SHADOW','SHADOW'][index],inventory_scope:'LEDGER_ONLY',state:'FRESH',
      position_count:index<2?1:0,unpriced_positions:0,assets_omitted:0,
      assets:index<2?[{symbol:'BTCUSDT',direction:index?'SHORT':'LONG',state:'FRESH',notional_usdt:index?150:100,priced_at:at}]:[]}))};
}
function opportunities(){
  const value=produce('emit_opportunity_fixture');
  // A new heartbeat may refresh the projection without changing frozen records.
  value.at=value.health.heartbeat_at=stamp();value.freshness={state:'FRESH',age_seconds:0};
  return value;
}

test('five new guided queries retain all eight existing intents and use no API',()=>{
  const p=setup(),options=p.get('intelligenceIntent').children.map(node=>node.getAttribute('value'));
  for(const intent of ['SUMMARY','REGIME','SCOPE_RISK','CONFLICTS','DATA_QUALITY','ORIGINAL_REVIEW','LIMITATIONS','COUNTERFACTUAL','EXPOSURE','LAST_DECISION','CAPITAL_BLOCKS','PERFORMANCE','WHY_NO_ENTRY'])assert.ok(options.includes(intent));
  for(const [question,intent] of [['¿Cuál es la exposición a BTC?','EXPOSURE'],['¿Cuál fue la última decisión de Spot?','LAST_DECISION'],['¿Qué bloqueos hubo por capital?','CAPITAL_BLOCKS'],['¿Qué estrategia tuvo mejor rendimiento?','PERFORMANCE'],['¿Por qué Spot no compró hoy?','WHY_NO_ENTRY'],['¿Por qué Futures rechazó una operación?','WHY_NO_ENTRY']])assert.equal(p.intelligence.resolveIntent(question).intent,intent,question);
  assert.equal(p.intelligence.resolveIntent('exposición a BTC y ETH').state,'AMBIGUOUS');
  assert.equal(p.intelligence.resolveIntent('última decisión de SPOT').symbol,null);
  for(const question of ['compra BTC','exposición a BTC; DROP TABLE orders','muestra token','activa Guardian','aumenta presupuesto','exposición '+ 'a'.repeat(300)])assert.equal(p.intelligence.answer(question).state,'UNSUPPORTED');
  assert.equal(p.calls.length,0);
});

test('exposure is scoped to each environment, never netted or summed, independently of Intelligence',()=>{
  const p=setup(),g=portfolio();p.intelligence.render({portfolio_guardian:g});
  const answer=p.intelligence.answer('exposición a BTC');
  assert.equal(answer.state,'ANSWERED');assert.equal(answer.source,'PORTFOLIO_GUARDIAN');assert.equal(answer.source_at,g.at);assert.equal(answer.assessment_id,null);assert.equal(answer.record_id,null);
  assert.match(answer.text,/SPOT_TESTNET: exposición bruta 100 USDT; dirección LONG/);assert.match(answer.text,/FUTURES_DEMO: exposición bruta 150 USDT; dirección SHORT/);
  assert.match(answer.text,/sin suma global, neteo ni cobertura supuesta/);assert.match(answer.text,/sin ID durable/);assert.doesNotMatch(answer.text,/\b(?:250|50|0) USDT/);
  const selected=p.intelligence.answer('exposición a BTC','EXPOSURE','SPOT');assert.doesNotMatch(selected.text,/Futures Bot/);assert.equal(p.calls.length,0);
});

test('unknown inventory, omitted assets, stale prices and invalid numbers cannot become current exposure or a zero',()=>{
  const mutations=[g=>g.scopes[0].state='PARTIAL',g=>g.scopes[0].unpriced_positions=1,g=>{g.scopes[0].assets_omitted=1;g.scopes[0].position_count=2;},g=>g.scopes[0].position_count=2,g=>g.scopes[0].assets[0].priced_at=new Date(Date.now()-601000).toISOString(),g=>g.scopes[0].assets[0].priced_at=new Date(Date.now()+10000).toISOString(),g=>g.scopes[0].assets[0].notional_usdt=null];
  for(const change of mutations){const p=setup(),g=portfolio();change(g);p.intelligence.render({portfolio_guardian:g});const answer=p.intelligence.answer('exposición a BTC','EXPOSURE','SPOT');assert.equal(answer.state,'UNKNOWN');assert.doesNotMatch(answer.text,/100 USDT|0 USDT/);}
  for(const value of ['100',-1,Infinity,NaN]){const p=setup(),g=portfolio();g.scopes[0].assets[0].notional_usdt=value;p.intelligence.render({portfolio_guardian:g});assert.equal(p.intelligence.answer('exposición a BTC').state,'UNKNOWN');}
});

test('transport age, future projection, wrong authority and malicious fields invalidate or qualify evidence',()=>{
  for(const mutate of [data=>data.remote_sync_stale=true,data=>data.portfolio_guardian.at=new Date(Date.now()-121000).toISOString(),data=>data.portfolio_guardian.at=new Date(Date.now()+10000).toISOString()]){
    const p=setup(),data={portfolio_guardian:portfolio()};mutate(data);p.intelligence.render(data);const answer=p.intelligence.answer('exposición a BTC');assert.equal(answer.state,'HISTORICAL');assert.doesNotMatch(answer.text,/100 USDT|150 USDT/);
  }
  for(const mutate of [g=>g.can_veto=true,g=>g.scopes[0].id='EVIL',g=>g.scopes[0].assets[0].symbol='<script>',g=>g.scopes[0].environment='LIVE',g=>g.padding='x'.repeat(15000)]){
    const p=setup(),g=portfolio();mutate(g);p.intelligence.render({portfolio_guardian:g});assert.equal(p.intelligence.answer('exposición a BTC').state,'UNKNOWN');
  }
});

test('grouped Quant directions remain unknown and an absent asset is limited to the published ledger',()=>{
  const p=setup(),g=portfolio(),q=g.scopes[3];q.position_count=2;q.assets=[{symbol:'BTCUSDT',direction:'UNKNOWN',state:'FRESH',notional_usdt:200,priced_at:g.at}];p.intelligence.render({portfolio_guardian:g});
  const answer=p.intelligence.answer('exposición a BTC','EXPOSURE','QUANT_ARBITRAGE');assert.equal(answer.state,'ANSWERED');assert.match(answer.text,/200 USDT; dirección mixta o no desglosada/);
  const missing=p.intelligence.answer('exposición a ETH','EXPOSURE','SPOT');assert.match(missing.text,/sin posición publicada en el ledger/);assert.doesNotMatch(missing.text,/0 USDT/);
  assert.equal(p.intelligence.answer('','EXPOSURE').state,'UNKNOWN');
});

test('real Python-produced Portfolio Guardian supports a scoped query without fabricating missing engines',()=>{
  const p=setup(),data=produce('emit_guardian_fixture');data.portfolio_guardian.at=stamp();for(const scope of data.portfolio_guardian.scopes)for(const asset of scope.assets)asset.priced_at=data.portfolio_guardian.at;
  p.intelligence.render(data);const spot=p.intelligence.answer('exposición a BTC','EXPOSURE','SPOT');assert.equal(spot.state,'ANSWERED');assert.match(spot.text,/200 USDT/);
  assert.equal(p.intelligence.answer('exposición a BTC').state,'UNKNOWN');
});

test('last decision cites the published record and distinguishes exchange response, ledger commit and intention',()=>{
  const p=setup(),value=opportunities();p.intelligence.render({opportunity_shadow:value});
  const spot=p.intelligence.answer('última decisión de Spot');assert.equal(spot.state,'ANSWERED');assert.equal(spot.source,'OPPORTUNITY_SHADOW');assert.match(spot.text,/EXCHANGE_RESPONSE/);assert.match(spot.text,/FILLED no demuestra commit/);assert.equal(spot.assessment_id,null);assert.match(spot.record_id,/^[a-f0-9]{64}$/);
  const quant=p.intelligence.answer('última decisión de Quant');assert.match(quant.text,/LEDGER_COMMIT/);assert.match(quant.text,/no acredita por sí solo conciliación/);
  const futures=p.intelligence.answer('última decisión de Futures');assert.match(futures.text,/Intención de entrada observada/);assert.match(futures.text,/no equivale a una operación ejecutada/);
  const bitcoin=p.intelligence.answer('última decisión de BTC');assert.match(bitcoin.text,/QUANT|Quant/);assert.equal(p.calls.length,0);
});

test('hypothetical capital rejections cannot be reported as actual blocked orders or full-history totals',()=>{
  const p=setup(),value=opportunities(),row=value.recent_records.find(item=>item.kind==='ENTRY_INTENT');
  row.assessment.hypothetical_state='REJECTED_UNVERIFIED';row.assessment.reason='CAPITAL_LIMIT_EXCEEDED';
  assert.equal(p.window.CryptoOpportunityContract.validOpportunityShadow(value),true);p.intelligence.render({opportunity_shadow:value});
  const answer=p.intelligence.answer('bloqueos por capital');assert.equal(answer.state,'UNKNOWN');assert.match(answer.text,/1 intenciones con hipótesis rechazadas/);assert.match(answer.text,/Guardian no aplica vetos/);assert.match(answer.text,/total de bloqueos reales es desconocido/);assert.ok(answer.evidence_ids.includes(row.id));
  const missing=p.intelligence.answer('bloqueos por capital de DOGE');assert.equal(missing.state,'UNKNOWN');assert.match(missing.text,/0 registros recientes/);
});

test('incompatible, future, disconnected or old observer evidence cannot assert a current decision',()=>{
  for(const mutate of [value=>value.can_veto=true,value=>value.recent_records[0].recorded_at=new Date(Date.now()+10000).toISOString(),value=>value.recent_records[0].stage='EXECUTE_NOW']){
    const p=setup(),value=opportunities();mutate(value);p.intelligence.render({opportunity_shadow:value});assert.equal(p.intelligence.answer('última decisión').state,'UNKNOWN');
  }
  const p=setup();p.intelligence.render({opportunity_shadow:opportunities(),remote_sync_stale:true});assert.equal(p.intelligence.answer('última decisión').state,'HISTORICAL');p.intelligence.disconnected();assert.equal(p.intelligence.answer('última decisión').state,'UNKNOWN');
});

test('why no entry and performance comparisons remain unknown despite a real original review',()=>{
  const p=setup(),guardian=produce('emit_guardian_intelligence_fixture');p.intelligence.render({guardian_intelligence:guardian});
  const why=p.intelligence.answer('¿Por qué Spot no compró hoy?');assert.equal(why.intent,'WHY_NO_ENTRY');assert.equal(why.state,'UNKNOWN');assert.match(why.text,/revisión puntual no acredita el historial completo/);assert.equal(why.assessment_id,guardian.report.assessment_id);
  const performance=p.intelligence.answer('¿Qué estrategia tuvo mejor rendimiento?');assert.equal(performance.state,'UNKNOWN');assert.match(performance.text,/mismo período, entorno, metodología y costes/);
});

test('query UI cites its actual source and freezes it without persisting a raw question or using network',async()=>{
  const p=setup(),g=portfolio(),guardian=produce('emit_guardian_intelligence_fixture');p.intelligence.render({portfolio_guardian:g,guardian_intelligence:guardian});
  p.get('intelligenceQuestion').value='exposición a BTC';p.get('intelligenceIntent').value='SUMMARY';p.get('intelligenceScope').value='SPOT';await p.get('intelligenceQueryForm').dispatch('submit');
  assert.match(p.get('intelligenceAnswer').textContent,/PORTFOLIO_GUARDIAN/);assert.match(p.get('intelligenceAnswer').textContent,/No disponible para esta fuente/);assert.doesNotMatch(p.get('intelligenceQueryHistory').textContent,/exposición a BTC/);
  const newer=portfolio();newer.at=new Date(Date.parse(g.at)+1).toISOString();p.intelligence.render({portfolio_guardian:newer,guardian_intelligence:guardian});assert.match(p.get('intelligenceAnswerFreshness').textContent,/proyección histórica/);assert.equal(p.calls.length,0);
});
