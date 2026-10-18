import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {portal} from './helpers/portal-dom.mjs';
import {validGuardianIntelligence} from '../src/guardian-intelligence.mjs';

const hash=char=>char.repeat(64);
const now=()=>new Date().toISOString();
function snapshot(){
  const at=now(),engines=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
  const report={schema:1,engine:'GUARDIAN_INTELLIGENCE',mode:'SHADOW',autonomy_level:0,controls_enabled:false,can_veto:false,execution_enabled:false,reservations_enabled:false,promotion_allowed:false,
    assessment_id:hash('a'),policy:{id:'guardian-intelligence-shadow-v1',calibrated:false},at,captured_at:at,cutoff_at:at,state:'PARTIAL',
    regime:{state:'BULLISH',method:'BTC_SPOT_CLOSED_1M_60M_DESCRIPTIVE_PROXY',window_minutes:60,observation_count:61,return_pct:1.2,realized_volatility_pct:.5,last_market_at:at,latest_available_at:at,reason:'INITIAL_DESCRIPTIVE_PROXY_ONLY',liquidity:{state:'UNKNOWN',at:null}},
    scopes:engines.map((id,i)=>({id,source_id:['spot','futures','pulse','quant'][i],environment:['SPOT_TESTNET','FUTURES_DEMO','SHADOW','SHADOW'][i],risk_state:i===1?'ENTRY_HALTED':'CAUTION',assessment:'WOULD_REVIEW',authoritative:false,reasons:['ACCOUNT_IDENTITY_AND_FULL_ORDER_INVENTORY_UNVERIFIED','INCLUSIVE_GLOBAL_RISK_NOT_CERTIFIED'],source_at:at,available_at:at,captured_at:at,inventory_complete:true,data_state:'FRESH',position_count:0,allocation:i===1?'REVIEW_EXISTING_PAUSE':'KEEP_UNASSIGNED',reported_engine_state:i===1?'PAUSED':'SHADOW',liveness:'NOT_ASSERTED_BY_DATA_AGE',evidence_id:hash(String(i+1)),latest_original_review:i===0?{state:'OBSERVED_METADATA_ONLY',id:'10',at,verdict:'REDUCE',confidence:.75,model:'test-model'}:{state:'UNAVAILABLE'}})),
    conflicts:[{symbol:'BTCUSDT',members:[{engine:'SPOT',direction:'LONG'},{engine:'FUTURES',direction:'SHORT'}],classification:'OPPOSING_CROSS_SCOPE_OBSERVATION',hedge_verified:false,allocation_action:'REVIEW_CROSS_SCOPE_OVERLAP'}],
    correlation:{state:'UNKNOWN'},counterfactual:{state:'UNKNOWN',losses_avoided:null,without_ai_pnl:null},evidence:{source_digest:hash('b'),source_ids:['spot','futures','pulse','quant'],original_decision_completeness:'NOT_PRE_SUBMIT_COMPLETE',input_valid:true},limitations:[],truncation:{conflicts_omitted:0}};
  return {guardian_intelligence:{schema:1,engine:'GUARDIAN_INTELLIGENCE',mode:'SHADOW',autonomy_level:0,controls_enabled:false,can_veto:false,execution_enabled:false,reservations_enabled:false,promotion_allowed:false,state:'PARTIAL',at,updated_at:at,freshness:{state:'FRESH',age_seconds:0},report,ai:{state:'DISABLED',authority:'NONE'},health:{last_error:null,errors:0,heartbeat_at:at,lease_state:'ACTIVE',lease_expires_at:at,records:1,compressed_corpus_bytes:1024,max_records:100,max_corpus_bytes:100000,capacity_state:'AVAILABLE',capacity_fraction:.01,ai_calls_today:0,ai_daily_limit:0},journal:[{id:hash('b'),cutoff_at:at,committed_at:at,report_digest:hash('c')} ]}};
}

test('actual Guardian workspace retains Observer and has six independently collapsible Intelligence sections',()=>{
  const p=portal({hash:'#intelligence-queries'});
  assert.deepEqual(p.root.querySelectorAll('[data-workspace]').filter(node=>!node.hidden).map(node=>node.dataset.workspace),['guardian-ai']);
  assert.equal(p.get('intelligence-queries').open,true);assert.ok(p.get('portfolio-guardian'));assert.equal(p.get('guardian-exposure').open,false);
  for(const id of ['intelligence-scopes','intelligence-sources','intelligence-ai','intelligence-conflicts','intelligence-journal','intelligence-queries'])assert.ok(p.get(id));
  assert.equal(p.calls.length,0);
});

test('compatible deterministic report renders four scopes, descriptive BTC regime and observed review metadata without capital assignments',()=>{
  const p=portal();p.intelligence.render(snapshot());
  assert.equal(p.get('intelligenceState').textContent,'EVIDENCIA PARCIAL');assert.match(p.get('intelligenceRegime').textContent,/Sesgo alcista observado/);
  assert.match(p.get('intelligenceRegimeMetrics').textContent,/1.2%/);assert.equal(p.get('intelligenceScopes').children.filter(node=>node.tagName==='ARTICLE').length,4);
  assert.match(p.get('intelligenceScopes').textContent,/REDUCE.*confianza declarada 75%/);assert.match(p.get('intelligenceScopes').textContent,/sin cambio aplicado por Guardian/);assert.match(p.get('intelligenceSources').textContent,/Disponible localmente/);
  assert.doesNotMatch(p.get('intelligenceScopes').textContent,/USDT|capital asignado|NORMAL|cuenta segura/);assert.match(p.get('intelligenceConflicts').textContent,/Cobertura no verificada/);assert.match(p.get('intelligenceJournal').textContent,/Registro persistido/);
});

test('missing and uninitialized wrappers preserve unknowns while separate Observer remains unchanged',()=>{
  const p=portal();p.get('guardianState').textContent='OBSERVER EXISTENTE';p.intelligence.render(null);
  assert.equal(p.get('guardianState').textContent,'OBSERVER EXISTENTE');assert.equal(p.get('intelligenceState').textContent,'SIN EVIDENCIA');assert.doesNotMatch(p.get('intelligenceHealth').textContent,/0 bytes|0 \/ 0/);
  const data=snapshot();Object.assign(data.guardian_intelligence,{state:'NOT_STARTED',report:null,ai:null,journal:[],updated_at:null,freshness:{state:'UNAVAILABLE',age_seconds:null},health:{records:null,errors:null,ai_calls_today:null,ai_daily_limit:0}});p.intelligence.render(data);
  assert.equal(p.get('intelligenceState').textContent,'SIN INICIAR');assert.match(p.get('intelligenceScopes').textContent,/Sin journal Intelligence inicializado/);assert.doesNotMatch(p.get('intelligenceScopes').textContent,/Cautela|Sesgo/);
});

test('any execution, veto, reservation, promotion, authority or malformed identity is incompatible',()=>{
  const p=portal();
  for(const key of ['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed']){
    const data=snapshot();data.guardian_intelligence[key]=true;p.intelligence.render(data);assert.equal(p.get('intelligenceState').textContent,'REPORTE NO COMPATIBLE');
  }
  for(const change of [report=>report.scopes[0].authoritative=true,report=>report.scopes[0].id='FUTURES',report=>report.assessment_id='not-a-digest',report=>report.policy.calibrated=true]){
    const data=snapshot();change(data.guardian_intelligence.report);p.intelligence.render(data);assert.match(p.get('intelligenceScopes').textContent,/No hay assessment verificable/);assert.doesNotMatch(p.get('intelligenceScopes').textContent,/REDUCE/);
  }
  const oversized=snapshot();oversized.guardian_intelligence.extra='ñ'.repeat(4000);p.intelligence.render(oversized);assert.equal(p.get('intelligenceState').textContent,'REPORTE NO COMPATIBLE');
});

test('old transport, old cutoffs and future clocks mask regime metrics and qualify every source as historical',()=>{
  const p=portal();
  for(const mutate of [data=>data.remote_sync_stale=true,data=>{const q=data.guardian_intelligence,at=new Date(Date.now()-200000).toISOString();q.updated_at=q.report.at=q.report.cutoff_at=q.report.captured_at=at;},data=>{const q=data.guardian_intelligence,at=new Date(Date.now()+10000).toISOString();q.updated_at=q.at=q.report.at=q.report.cutoff_at=q.report.captured_at=at;}]){
    const data=snapshot();mutate(data);p.intelligence.render(data);assert.equal(p.get('intelligenceState').textContent,'ÚLTIMO REPORTE HISTÓRICO');assert.doesNotMatch(p.get('intelligenceRegimeMetrics').textContent,/1.2%|0.5%/);assert.match(p.get('intelligenceScopes').textContent,/HISTÓRICO/);assert.doesNotMatch(p.get('intelligenceSources').textContent,/Calidad actualReciente/);assert.equal(p.intelligence.answer('¿Cómo está el mercado?').state,'HISTORICAL');
  }
});

test('individual stale sources and missing bar windows do not become recent by publishing a new wrapper',()=>{
  const p=portal(),data=snapshot();data.guardian_intelligence.report.scopes[2].source_at=new Date(Date.now()-31000).toISOString();data.guardian_intelligence.report.regime={state:'INSUFFICIENT_DATA',reason:'NONCONTIGUOUS_CLOSED_BAR_WINDOW',observation_count:50};p.intelligence.render(data);
  assert.match(p.get('intelligenceRegime').textContent,/Evidencia insuficiente/);assert.doesNotMatch(p.get('intelligenceRegimeMetrics').textContent,/undefined|NaN/);assert.match(p.intelligence.answer('¿Qué información falta?').text,/AI Market Pulse: actualidad desconocida/);
});

test('untrusted sources, conflicts, model comments and reasons remain bounded and escaped',()=>{
  const p=portal(),data=snapshot(),attack='<img src=x onerror="steal()">';
  data.guardian_intelligence.report.scopes[0].reasons=[attack];data.guardian_intelligence.report.scopes[0].source_id=attack;data.guardian_intelligence.report.conflicts[0].symbol=attack;data.guardian_intelligence.health.last_error=attack;
  data.guardian_intelligence.ai={state:'COMPLETED',advisory_only:true,controls_enabled:false,execution_enabled:false,at:now(),assessment_id:hash('a'),model:attack,commentary:{summary:attack,posture:'OBSERVE',cautions:[attack],evidence_ids:[hash('a')]}};
  p.intelligence.render(data);
  for(const id of ['intelligenceScopes','intelligenceSources','intelligenceConflicts','intelligenceAi']){assert.doesNotMatch(p.get(id).innerHTML,/<img|<script/);assert.match(p.get(id).innerHTML,/&lt;img/);}
  assert.equal(p.calls.length,0);
});

test('AI cache and differing assessment stay pinned to their original identity and cannot modify deterministic states',()=>{
  const p=portal(),data=snapshot();data.guardian_intelligence.ai={state:'CACHED_HISTORICAL',advisory_only:true,controls_enabled:false,execution_enabled:false,at:now(),assessment_id:hash('d'),cache_age_seconds:50,model:'test-model',commentary:{summary:'Revisar datos de esa captura',posture:'REVIEW_DATA',cautions:[],evidence_ids:[hash('d')]}};
  p.intelligence.render(data);assert.match(p.get('intelligenceAi').textContent,/COMENTARIO HISTÓRICO/);assert.match(p.get('intelligenceAi').textContent,new RegExp(hash('d')));assert.match(p.get('intelligenceScopes').textContent,/Cautela/);
  data.guardian_intelligence.ai.commentary.evidence_ids=[hash('e')];p.intelligence.render(data);assert.match(p.get('intelligenceAi').textContent,/Comentario no compatible/);
});

test('closed local intents explain evidence and refuse orders, SQL, secrets, arbitrary questions and ambiguous scopes without network',()=>{
  const p=portal();p.intelligence.render(snapshot());
  for(const [text,intent] of [['¿Cómo está el mercado?','REGIME'],['¿Qué información falta?','DATA_QUALITY'],['¿Por qué revisar Futures?','SCOPE_RISK'],['¿Qué dijo la IA de Spot?','ORIGINAL_REVIEW'],['¿Coinciden en BTC?','CONFLICTS']])assert.equal(p.intelligence.answer(text).intent,intent);
  assert.equal(p.intelligence.answer('¿Por qué revisar Spot y Futures?').state,'AMBIGUOUS');
  for(const text of ['compra BTC','vende todo','ejecuta una orden','aumenta el riesgo','pausa Futures','reanuda Spot','SELECT * FROM trades','sql DROP TABLE orders','api_key=secret-value','sk-secret-value','cuéntame un chiste'])assert.equal(p.intelligence.answer(text).state,'UNSUPPORTED',text);
  assert.equal(p.intelligence.answer('¿Coinciden en DOGE?').state,'UNKNOWN');assert.match(p.intelligence.answer('¿Coinciden en DOGE?').text,/DOGEUSDT: sin coincidencias/);assert.match(p.intelligence.answer('¿COINCIDEN EN BTC?').text,/BTCUSDT: 1 coincidencia/);
  assert.equal(p.intelligence.answer('¿Cuánto habría ganado sin IA?').state,'UNKNOWN');assert.match(p.intelligence.answer('¿Cuánto habría ganado sin IA?').text,/no existe una cohorte contrafactual/);assert.equal(p.calls.length,0);
});

test('browser query convenience history cites persisted assessment but stores no raw question and never reattributes an answer',async()=>{
  const p=portal(),data=snapshot();p.intelligence.render(data);p.get('intelligenceQuestion').value='¿Qué información falta?';p.get('intelligenceIntent').value='SUMMARY';p.get('intelligenceScope').value='ALL';await p.get('intelligenceQueryForm').dispatch('submit');
  assert.match(p.get('intelligenceAnswer').textContent,new RegExp(hash('a')));assert.match(p.get('intelligenceAnswer').textContent,new RegExp(hash('b')));assert.match(p.get('intelligenceAnswer').textContent,/no es auditoría durable/);assert.doesNotMatch(p.get('intelligenceQueryHistory').textContent,/Qué información falta/);assert.equal(p.calls.length,0);
  const next=snapshot();next.guardian_intelligence.report.assessment_id=hash('d');p.intelligence.render(next);assert.match(p.get('intelligenceAnswerFreshness').textContent,/assessment histórico/);assert.match(p.get('intelligenceAnswer').textContent,new RegExp(hash('a')));
  const historical=new Date(Date.now()-100000).toISOString();data.guardian_intelligence.updated_at=data.guardian_intelligence.report.at=data.guardian_intelligence.report.cutoff_at=data.guardian_intelligence.report.captured_at=historical;p.intelligence.render(data);assert.equal(p.intelligence.answer('', 'REGIME').state,'HISTORICAL');
});

test('disconnection and incompatible refresh clear all current derived evidence and prior answer',async()=>{
  const p=portal();p.intelligence.render(snapshot());p.get('intelligenceQuestion').value='resumen';p.get('intelligenceIntent').value='SUMMARY';p.get('intelligenceScope').value='ALL';await p.get('intelligenceQueryForm').dispatch('submit');
  p.intelligence.disconnected();assert.equal(p.get('intelligenceState').textContent,'LECTURA NO DISPONIBLE');assert.doesNotMatch(p.get('intelligenceScopes').textContent,/REDUCE|Cautela/);assert.doesNotMatch(p.get('intelligenceAi').textContent,/COMENTARIO/);assert.match(p.get('intelligenceAnswer').textContent,/Sin conexión verificable/);assert.equal(p.intelligence.answer('resumen').state,'UNKNOWN');
  p.intelligence.render(null);assert.match(p.get('intelligenceAnswer').textContent,/Sin reporte actual verificable/);
});

test('AI usage unknowns and observer lease states remain distinct from zero cost and operating engine authority',()=>{
  const p=portal(),data=snapshot();data.guardian_intelligence.ai={state:'COMPLETED',advisory_only:true,controls_enabled:false,execution_enabled:false,at:now(),assessment_id:hash('a'),model:'test-model',commentary:{summary:'Revisar la evidencia disponible',posture:'REVIEW_DATA',cautions:[],evidence_ids:[hash('a')]},usage:{input_tokens:null,output_tokens:null,cached_tokens:null,estimated_cost_usd:null,pricing_verified_at:'2026-10-18'}};
  data.guardian_intelligence.health.lease_state='NONE';p.intelligence.render(data);assert.match(p.get('intelligenceHealth').textContent,/Lease observadorSin propietario/);assert.match(p.get('intelligenceAi').textContent,/Tokens entrada \/ salida— \/ —/);assert.match(p.get('intelligenceAi').textContent,/Coste API estimado de esa respuestaDesconocido/);assert.doesNotMatch(p.get('intelligenceAi').textContent,/0 USD/);
  data.guardian_intelligence.health.lease_state='RELEASED';p.intelligence.render(data);assert.match(p.get('intelligenceHealth').textContent,/Lease observadorLiberado/);
  data.guardian_intelligence.state='RETENTION_FULL';data.guardian_intelligence.health.capacity_state='FULL';p.intelligence.render(data);assert.match(p.get('intelligenceState').textContent,/RETENCIÓN LLENA/);assert.match(p.get('intelligenceHealth').textContent,/Retención llena/);
  data.guardian_intelligence.state='STOPPED';p.intelligence.render(data);assert.match(p.get('intelligenceState').textContent,/OBSERVADOR DETENIDO/);assert.equal(p.intelligence.answer('resumen').state,'HISTORICAL');data.guardian_intelligence.state='PARTIAL';
  data.guardian_intelligence.ai.at=new Date(Date.now()+10000).toISOString();p.intelligence.render(data);assert.match(p.get('intelligenceAi').textContent,/Comentario no compatible/);
});

test('real four-ledger Guardian service producer survives strict Worker projection and renders its persisted assessment in the shipped DOM',()=>{
  const produce=variant=>JSON.parse(execFileSync(process.env.PYTHON||'python',[fileURLToPath(new URL('../../tests/emit_guardian_intelligence_fixture.py',import.meta.url)),'--variant',variant],{encoding:'utf8'}));
  const p=portal(),ready=produce('ready');assert.equal(validGuardianIntelligence(ready),true);assert.ok(ready.report);assert.equal(ready.ai.state,'COMPLETED');
  p.intelligence.render({guardian_intelligence:ready});assert.match(p.get('intelligenceState').textContent,/OBSERVANDO|PARCIAL/);assert.match(p.get('intelligenceEvidence').textContent,new RegExp(ready.report.assessment_id));assert.match(p.get('intelligenceJournal').textContent,new RegExp(ready.journal[0].id));assert.match(p.get('intelligenceAi').textContent,/INTERPRETACIÓN OPCIONAL/);assert.equal(p.intelligence.answer('resumen').assessment_id,ready.report.assessment_id);assert.equal(p.intelligence.answer('resumen').record_id,ready.journal[0].id);assert.equal(p.calls.length,0);
  const stale=produce('stale');assert.equal(validGuardianIntelligence(stale),true);p.intelligence.render({guardian_intelligence:stale});assert.equal(p.get('intelligenceState').textContent,'ÚLTIMO REPORTE HISTÓRICO');assert.equal(p.intelligence.answer('resumen').state,'HISTORICAL');
  const missing=produce('not-started');assert.equal(validGuardianIntelligence(missing),true);p.intelligence.render({guardian_intelligence:missing});assert.equal(p.get('intelligenceState').textContent,'SIN INICIAR');assert.equal(p.intelligence.answer('resumen').state,'UNKNOWN');
});
