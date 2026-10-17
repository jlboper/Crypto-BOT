import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

function portal({hostname='127.0.0.1'}={}){
  const elements=new Map(),calls=[];
  const get=id=>{
    if(!elements.has(id))elements.set(id,{id,textContent:'',innerHTML:'',className:'',dataset:{},disabled:false,
      listeners:{},classList:{add(){},remove(){},toggle(){}},addEventListener(name,callback){this.listeners[name]=callback;},scrollIntoView(){}});
    return elements.get(id);
  };
  const document={getElementById:get,querySelector:()=>null,querySelectorAll:()=>[]};
  const window={addEventListener(){},paperControlsAvailable:()=>true,portalButtonBusy:()=>false,portalApi:async(path,options)=>{calls.push({path,options});return {status:'pending'};}};
  const context=vm.createContext({window,document,URL,URLSearchParams,Date,location:{search:'',pathname:'/',hash:'',hostname},
    sessionStorage:{getItem:()=>null},history:{replaceState(){}},setInterval:()=>0,setTimeout,clearTimeout,console,navigator:{}});
  vm.runInContext(readFileSync(new URL('../../web/app.js',import.meta.url),'utf8'),context);
  vm.runInContext('refresh=async()=>{};',context);
  return {ui:window.FourEnginePortal,folds:window.PulsePortal,get,calls,window};
}
const now=()=>new Date().toISOString();

test('PAPER Spot uses simulated protections without claiming a missing native exchange confirmation',()=>{
  const {folds,get}=portal();
  folds.render(null,{mode:'PAPER',positions:0,activity:{state:'operational'}},{},[]);
  assert.equal(get('summarySpotProtection').textContent,'Sin exposición · stops simulados PAPER');
  folds.render(null,{mode:'PAPER',positions:1,activity:{state:'operational'}},{},[{symbol:'BTCUSDT'}]);
  assert.equal(get('summarySpotProtection').textContent,'Stops simulados · PAPER');
  folds.render(null,{mode:'TESTNET',positions:1,activity:{state:'operational'}},{},[{symbol:'BTCUSDT'}]);
  assert.equal(get('summarySpotProtection').textContent,'Confirmación nativa pendiente');
  folds.render(null,{mode:'TESTNET',positions:1,activity:{state:'operational'},native_protection:{positions:{BTCUSDT:{status:'ARMED'}}}},{},[{symbol:'BTCUSDT'}]);
  assert.equal(get('summarySpotProtection').textContent,'1/1 OCO confirmados');
});

function snapshot(){return {
  quant:{schema:1,engine:'QUANT_ARBITRAGE',mode:'SHADOW',state:'NOT_STARTED',initialized:false,enabled:false,
    execution_enabled:false,controls_available:false,promotion_allowed:false,at:now(),updated_at:null,positions:[],
    performance:{initial_capital:null,equity:null,net_pnl:null,closed_trades:null},
    strategies:[{id:'FUNDING_CARRY',state:'NOT_STARTED'},{id:'STATISTICAL_ARBITRAGE',state:'NOT_STARTED'}]},
  portfolio_guardian:{schema:1,engine:'PORTFOLIO_GUARDIAN',mode:'OBSERVER',state:'OBSERVING',at:now(),
    controls_enabled:false,can_veto:false,execution_enabled:false,scopes:[
      {id:'SPOT',environment:'SPOT_TESTNET',state:'FRESH',position_count:1,unpriced_positions:0,gross_usdt:100,net_usdt:100,
        nominal_stop_risk_usdt:2,capital:{equity_usdt:1002,cash_usdt:902,state:'FRESH'},limits:{gross_usdt:600,stop_risk_usdt:null},budget_status:{gross:'WITHIN',stop_risk:'UNKNOWN'},assets:[{native_protection:'ARMED'}]},
      {id:'FUTURES',environment:'FUTURES_DEMO',state:'FRESH',position_count:1,unpriced_positions:0,gross_usdt:120,net_usdt:-120,
        nominal_stop_risk_usdt:3,capital:{equity_usdt:1995,cash_usdt:2000,state:'FRESH'},limits:{gross_usdt:300,stop_risk_usdt:7.5},budget_status:{gross:'WITHIN',stop_risk:'OBSERVED_WITHIN'},assets:[{native_protection:'ARMED'}]},
      {id:'AI_MARKET_PULSE',environment:'SHADOW',state:'FRESH',position_count:0,unpriced_positions:0,gross_usdt:0,net_usdt:0,nominal_stop_risk_usdt:0,capital:{equity_usdt:1000,cash_usdt:1000,state:'FRESH'},limits:{},budget_status:{},assets:[]},
      {id:'QUANT_ARBITRAGE',environment:'SHADOW',state:'NOT_STARTED',position_count:null,unpriced_positions:null,capital:{},limits:{},budget_status:{},assets:[]}
    ],alerts:[],overlaps:[]}
};}

test('four engine UI renders Quant identity without fabricated capital, zero positions or performance',()=>{
  const {ui,get}=portal(),data=snapshot();
  data.quant.performance={initial_capital:1000,equity:1234,net_pnl:234,closed_trades:3};
  ui.render(data);
  assert.equal(get('summaryQuantState').textContent,'SIN INICIAR');
  for(const field of ['Capital','Positions','Return','Evaluation'])assert.equal(get('summaryQuant'+field).textContent,'—');
  assert.equal(get('quantFundingState').textContent,'SIN INICIAR');
  assert.equal(get('quantStatisticalState').textContent,'SIN INICIAR');
  assert.equal(get('pauseQuant').disabled,true);assert.equal(get('resumeQuant').disabled,true);
  assert.match(get('quantStatusNote').textContent,/no tiene un motor ni ledger inicializado/);
});

test('Guardian renders separate financial scopes with unknown inclusive stop budget and no financial total',()=>{
  const {ui,get}=portal();ui.render(snapshot());
  const value=get('guardianScopes').innerHTML;
  assert.equal(get('guardianState').textContent,'OBSERVER ACTIVO');
  for(const environment of ['SPOT_TESTNET','FUTURES_DEMO','SHADOW'])assert.match(value,new RegExp(environment));
  assert.match(value,/1,002 USDT \/ 902 USDT/);assert.match(value,/1,995 USDT \/ 2,000 USDT/);
  assert.match(value,/100 USDT \/ 100 USDT/);assert.match(value,/120 USDT \/ -120 USDT/);
  assert.match(value,/600 USDT \/ —/);assert.match(value,/300 USDT \/ 7.5 USDT/);
  assert.match(value,/Distancia nominal a stops/);assert.match(value,/SIN EVIDENCIA/);
  assert.doesNotMatch(value,/3,997|2,997|Total financiero|PnL total/);
  assert.match(get('guardianAlertSummary').textContent,/3\/4 ledgers/);
  assert.match(get('guardianLimitations').textContent,/no es una pérdida máxima/);
  assert.match(value,/Estados nativos registrados/);assert.match(value,/no son una confirmación actual independiente/);
});

test('stale remote Guardian clears current financial valuations and qualifies historical native confirmations',()=>{
  const {ui,get}=portal(),data=snapshot();data.remote_sync_stale=true;ui.render(data);
  assert.match(get('guardianState').textContent,/LECTURA ANTIGUA/);
  assert.doesNotMatch(get('guardianScopes').innerHTML,/1,002 USDT|1,995 USDT|100 USDT \/ 100 USDT/);
  assert.match(get('guardianScopes').innerHTML,/no confirman el estado actual/);
  assert.match(get('guardianAlertSummary').textContent,/Último registro/);
  assert.match(get('quantStatusNote').textContent,/Última identidad sincronizada/);
  assert.match(get('summaryGuardianStatus').textContent,/lectura antigua/);
});

test('Guardian stale timestamps, partial valuations, failures and future clocks do not imply a trading outage',()=>{
  const {ui,get}=portal(),data=snapshot();
  data.portfolio_guardian.state='PARTIAL';data.portfolio_guardian.scopes[0].state='PARTIAL';ui.render(data);
  assert.equal(get('guardianState').textContent,'OBSERVACIÓN PARCIAL');
  assert.match(get('guardianScopes').innerHTML,/Exposición bruta \/ neta<\/dt><dd>— \/ —/);
  data.portfolio_guardian.at=new Date(Date.now()-121000).toISOString();ui.render(data);
  assert.match(get('guardianState').textContent,/ANTIGUA/);
  data.portfolio_guardian.at=new Date(Date.now()+10000).toISOString();ui.render(data);
  assert.match(get('guardianState').textContent,/ANTIGUA/);
  ui.render(null);assert.equal(get('guardianState').textContent,'SIN DATOS');
  assert.match(get('guardianScopes').innerHTML,/No se sustituye por cero/);
  assert.match(get('quantStatusNote').textContent,/no modifica la operación/);
  assert.equal(get('summaryQuantState').textContent,'SIN DATOS');
});

test('Guardian refuses a control-capable contract and Quant refuses an enabled or unknown execution state',()=>{
  const {ui,get}=portal(),data=snapshot();data.portfolio_guardian.can_veto=true;data.quant.enabled=true;ui.render(data);
  assert.equal(get('guardianState').textContent,'SIN DATOS');assert.equal(get('summaryQuantState').textContent,'SIN DATOS');
  assert.equal(get('pauseQuant').disabled,true);assert.equal(get('resumeQuant').disabled,true);assert.doesNotMatch(get('guardianScopes').innerHTML,/100 USDT/);
});

test('Guardian untrusted alerts, environments and overlap fields remain escaped and bounded',()=>{
  const {ui,get}=portal(),data=snapshot(),attack='<img src=x onerror=alert(1)>';
  data.portfolio_guardian.scopes[0].environment=attack;
  data.portfolio_guardian.alerts=Array.from({length:50},()=>({code:attack,scope:'SPOT',symbol:attack}));
  data.portfolio_guardian.overlaps=Array.from({length:50},()=>({symbol:attack,scopes:['SPOT','FUTURES']}));
  ui.render(data);
  for(const id of ['guardianScopes','guardianAlerts','guardianOverlaps'])assert.doesNotMatch(get(id).innerHTML,/<img|<script/);
  assert.match(get('guardianScopes').innerHTML,/&lt;img/);assert.match(get('guardianOverlaps').innerHTML,/&lt;img/);
  assert.equal((get('guardianAlerts').innerHTML.match(/<article/g)||[]).length,20);
  assert.equal((get('guardianOverlaps').innerHTML.match(/<article/g)||[]).length,10);
  assert.match(get('guardianOverlaps').innerHTML,/No acredita cobertura ni capital compartido/);
});

test('Guardian and Quant navigation opens native folds and disconnected state removes valuations',()=>{
  const {ui,get,folds}=portal();
  for(const id of ['guardian-exposure','guardian-overlaps','guardian-quality','quant-funding','quant-statistical']){
    const target=get(id);target.tagName='DETAILS';target.open=false;
    assert.equal(folds.revealSection(id,false),true);assert.equal(target.open,true);
  }
  ui.render(snapshot());ui.disconnected();
  assert.equal(get('guardianState').textContent,'LECTURA NO DISPONIBLE');
  assert.equal(get('summaryQuantState').textContent,'LECTURA NO DISPONIBLE');
  assert.doesNotMatch(get('guardianScopes').innerHTML,/USDT/);
  assert.match(get('guardianStatusNote').textContent,/históricos/);
  assert.match(get('guardianAlerts').innerHTML,/actuales no disponibles/);
  assert.match(get('guardianOverlaps').innerHTML,/actuales no disponibles/);
  assert.match(get('guardianAlertSummary').textContent,/actuales no disponibles/);
  assert.doesNotMatch(get('guardianQuality').innerHTML,/Captura|Dentro del límite/);
});

function initializedQuant(overrides={}){
  const stamp=now();
  return {...snapshot().quant,initialized:true,enabled:true,controls_available:true,state:'SHADOW',at:stamp,updated_at:stamp,last_evaluation:stamp,
    freshness:{state:'FRESH',age_seconds:0},
    performance:{initial_capital:1000,equity:1001,cash:900,collateral_usdt:100,net_pnl:1,return_pct:.1,gross_exposure_usdt:100,
      drawdown_pct:.2,closed_trades:2,win_rate:50,profit_factor:1.2,costs_usdt:.4,simulated_funding_usdt:.2,observation_days:.5},
    positions:[{instrument:'BTCUSDT',strategy:'FUNDING_CARRY',opened_at:stamp,gross_exposure_usdt:100,net_exposure_usdt:0,net_pnl_usdt:1,
      entry_fees_usdt:.1,entry_slippage_usdt:.1,estimated_exit_cost_usdt:.2,funding_usdt:.2,risk_budget_usdt:2.5,
      legs:[{symbol:'BTCUSDT',direction:'LONG',venue:'SPOT_REFERENCE',state:'FRESH',quantity:.001,entry_price:50050,entry_reference:50000,mark_price:50500,entry_fee_usdt:.05,priced_at:stamp,received_at:stamp},
        {symbol:'BTCUSDT',direction:'SHORT',venue:'FUTURES_REFERENCE',state:'FRESH',quantity:.001,entry_price:50000,entry_reference:50050,mark_price:50500,entry_fee_usdt:.05,priced_at:stamp,received_at:stamp}]}],
    market:[{symbol:'BTCUSDT',state:'FRESH',spot_price:50000,futures_price:50050,basis_bps:10,observed_funding_rate:.0001,next_funding_at:stamp,funding_interval_seconds:28800,at:stamp,received_at:stamp}],
    strategies:[{id:'FUNDING_CARRY',state:'OBSERVING',signals:[{instrument:'BTCUSDT',action:'WAIT',reason:'PROJECTED_CARRY_BELOW_ALL_COSTS',at:stamp,
      metrics:{observed_funding_rate:.0001,projected_funding_usdt:.15,conditional_net_estimate_usdt:-.2,roundtrip_cost_usdt:.35}}]},
      {id:'STATISTICAL_ARBITRAGE',state:'OBSERVING',signals:[{instrument:'BTCUSDT/ETHUSDT',action:'WAIT',reason:'COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED',at:stamp,metrics:{z_score:2.1,hedge_ratio:1.3,residual_adf_lag1_t:-2.7}}]}],
    funding:[{symbol:'BTCUSDT',funding_at:stamp,received_at:stamp,rate:.0001,simulated_cashflow_usdt:.2,state:'SETTLED_SIMULATION'}],
    decisions:[{strategy:'FUNDING_CARRY',instrument:'BTCUSDT',at:stamp,action:'WAIT',reason:'PROJECTED_CARRY_BELOW_ALL_COSTS',rule_version:'quant-shadow-v1',
      metrics:{projected_funding_usdt:.15},available_at_decision:{observation_cutoff:stamp,aligned_observations:12,source_digest:'frozen-source'}}],
    journal:[{id:'journal-1',at:stamp,kind:'PAIR_OPENED_SIMULATION',position_id:'pair-1'}],sources:[{id:'BTCUSDT',state:'READY'}],
    health:{calls:3,errors:0,last_success_at:stamp},limits:{evaluation_interval_seconds:60},
    data_quality:{market:'COMPLETE',funding:'COMPLETE_OBSERVED_SCHEDULE'},benchmarks:[{symbol:'BTCUSDT',buy_hold_return_pct:1}],...overrides};
}

test('initialized Quant shows actual virtual evidence, two legs and projected funding separately from simulated settlements',()=>{
  const {ui,get}=portal();ui.render({quant:initializedQuant()});
  assert.equal(get('summaryQuantState').textContent,'SHADOW ACTIVO');
  assert.equal(get('summaryQuantCapital').textContent,'1,001 USDT');assert.equal(get('summaryQuantReturn').textContent,'1 USDT');
  assert.equal(get('summaryQuantPositions').textContent,'1 pares / 2 cierres');
  assert.match(get('quantFundingSignals').innerHTML,/Funding proyectado condicional<\/dt><dd>0.15 USDT/);
  assert.match(get('quantFunding').innerHTML,/Flujo asentado en simulación<\/dt><dd>0.2 USDT/);
  assert.match(get('quantFunding').innerHTML,/no es un ingreso real del exchange/);
  assert.equal((get('quantPositions').innerHTML.match(/pierna hipotética/g)||[]).length,2);
  assert.match(get('quantPositions').innerHTML,/Comisión \/ deslizamiento de entrada/);
  assert.match(get('quantPositions').innerHTML,/ejecución no atómica/);
  assert.equal(get('quantStatisticalState').textContent,'SCREEN · ENTRADAS BLOQUEADAS');
  assert.match(get('quantStatisticalSignals').innerHTML,/cointegración sin validación independiente/);
  assert.match(get('quantJournal').innerHTML,/Par hipotético abierto/);
  assert.match(get('quantDecisions').innerHTML,/frozen-source|projected_funding_usdt/);
  assert.match(get('quantBenchmarks').textContent,/No descuenta costes/);
  assert.equal(get('pauseQuant').disabled,false);assert.equal(get('resumeQuant').disabled,true);
});

test('Quant stale, remote and future clock evidence masks current money, marks and benchmarks and blocks controls',()=>{
  const {ui,get}=portal();
  for(const overrides of [{updated_at:new Date(Date.now()-91000).toISOString()}, {at:new Date(Date.now()-121000).toISOString()},
    {updated_at:new Date(Date.now()+10000).toISOString()}, {freshness:{state:'STALE',age_seconds:91}}, {remote_sync_stale:true}]){
    ui.render({quant:initializedQuant(overrides)});
    assert.match(get('summaryQuantState').textContent,/ANTIGUO/);
    assert.equal(get('summaryQuantCapital').textContent,'—');assert.equal(get('summaryQuantReturn').textContent,'—');
    assert.match(get('quantPerformance').innerHTML,/Equity virtual<\/dt><dd>—/);
    assert.match(get('quantPositions').innerHTML,/50,050 \/ —/);
    assert.doesNotMatch(get('quantMarket').innerHTML,/50,000 USDT/);
    assert.match(get('quantBenchmarks').textContent,/sin referencia reciente/);
    assert.equal(get('pauseQuant').disabled,true);assert.equal(get('resumeQuant').disabled,true);
  }
  ui.render({quant:initializedQuant(),remote_sync_stale:true});assert.equal(get('summaryQuantCapital').textContent,'—');
});

test('Quant pending authoritative funding and missing ledger never substitute null valuations or performance with zero',()=>{
  const {ui,get}=portal();ui.render({quant:initializedQuant({performance:{initial_capital:1000,equity:null,net_pnl:null,closed_trades:0,win_rate:null,profit_factor:null},data_quality:{funding:'PENDING_AUTHORITATIVE_EVENTS'}})});
  assert.equal(get('summaryQuantCapital').textContent,'—');assert.equal(get('summaryQuantReturn').textContent,'—');
  assert.match(get('quantPerformance').innerHTML,/Win rate \/ profit factor<\/dt><dd>— \/ —/);
  assert.match(get('quantHealth').innerHTML,/Pendiente de eventos históricos verificables/);
  ui.render({quant:{...snapshot().quant,state:'DEGRADED',health:{last_error:'SHADOW_LEDGER_UNAVAILABLE'}}});
  assert.equal(get('summaryQuantState').textContent,'LEDGER NO DISPONIBLE');
  assert.match(get('quantStatusNote').textContent,/no se reconstruye un capital ficticio/);
  assert.doesNotMatch(get('quantPerformance').innerHTML,/1,000|0 USDT/);
});

test('Quant independent pause uses authenticated supervisor route once and waits for fresh observed confirmation',async()=>{
  const {ui,get,calls}=portal();ui.init();ui.render({quant:initializedQuant()});
  await get('pauseQuant').listeners.click();assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/quant-arbitrage/pause');assert.equal(calls[0].options.body,'{}');
  assert.equal(calls[0].options.method,'POST');assert.equal(get('pauseQuant').disabled,true);
  ui.render({quant:initializedQuant()});await get('pauseQuant').listeners.click();assert.equal(calls.length,1);
  ui.render({quant:initializedQuant({state:'PAUSED'})});assert.equal(get('resumeQuant').disabled,false);
  assert.match(get('quantControlMessage').textContent,/Windows confirmó/);
  await get('resumeQuant').listeners.click();assert.equal(calls[1].path,'/api/quant-arbitrage/resume');assert.equal(calls[1].options.body,'{}');
});

test('remote Quant controls require the dedicated synchronized capability and are rechecked on click',async()=>{
  const {ui,get,window,calls}=portal({hostname:'crypto.example.test'});ui.init();ui.render({quant:initializedQuant()});
  assert.equal(get('pauseQuant').disabled,true,'A legacy remote agent cannot inherit generic Spot control privileges');
  window.quantControlsAvailable=()=>true;ui.render({quant:initializedQuant()});assert.equal(get('pauseQuant').disabled,false);
  window.quantControlsAvailable=()=>false;await get('pauseQuant').listeners.click();assert.equal(calls.length,0,'Capability revocation is checked again before sending');
  ui.render({quant:initializedQuant()});assert.equal(get('pauseQuant').disabled,true);
});

test('Quant daily and weekly loss limits disclose first valid UTC-period baselines and do not imply a midnight drawdown or an override',()=>{
  const {ui,get}=portal(),stamp=now(),period={period_start:stamp,baseline_at:stamp,baseline_equity:1000,return_pct:-1.1,limit_pct:1,halted:true,resets_at:stamp};
  ui.render({quant:initializedQuant({risk_halt:{state:'HALTED',at:stamp,method:'FIRST_VALID_LEDGER_EQUITY_WITHIN_UTC_PERIOD',daily:period,weekly:{...period,limit_pct:2}}})});
  assert.equal(get('summaryQuantState').textContent,'LÍMITE DE PÉRDIDA');
  assert.match(get('quantRisk').innerHTML,/Bloqueadas hasta reinicio del período/);
  assert.match(get('quantRisk').innerHTML,/-1.1% \/ 1%/);assert.match(get('quantRisk').innerHTML,/-1.1% \/ 2%/);
  assert.match(get('quantRiskMethod').textContent,/primera equity válida/);assert.match(get('quantRiskMethod').textContent,/después de medianoche/);
  assert.match(get('quantRiskMethod').textContent,/no cambia límites ni elimina/);
  ui.render({quant:initializedQuant({risk_halt:{state:'UNKNOWN',daily:{baseline_equity:null,return_pct:null,limit_pct:1},weekly:{baseline_equity:null,return_pct:null,limit_pct:2}}})});
  assert.equal(get('summaryQuantState').textContent,'VALORACIÓN PENDIENTE');assert.match(get('quantRisk').innerHTML,/valoración o baseline desconocidos/);
  ui.disconnected();assert.doesNotMatch(get('quantRisk').innerHTML,/-1.1|1,000 USDT/);
});

test('Quant stale individual legs and funding incomplete pair valuations stay unavailable even while source snapshots are fresh',()=>{
  const {ui,get}=portal(),q=initializedQuant();q.positions[0].legs[0].state='STALE';q.positions[0].legs[1].received_at=new Date(Date.now()-91000).toISOString();
  q.data_quality.funding='PENDING_AUTHORITATIVE_EVENTS';ui.render({quant:q});
  assert.match(get('quantPositions').innerHTML,/50,050 \/ —/);assert.match(get('quantPositions').innerHTML,/50,000 \/ —/);
  assert.match(get('quantPositions').innerHTML,/P&amp;L con costes estimados de salida<\/dt><dd>—/);
});

test('Quant diagnostics stay bounded, escaped, and unavailable after disconnection or incompatible execution flags',()=>{
  const {ui,get}=portal(),attack='<img src=x onerror=alert(1)>',q=initializedQuant();
  q.positions[0].instrument=attack;q.positions[0].legs[0].symbol=attack;q.decisions[0].reason=attack;
  q.decisions[0].available_at_decision.source_digest=attack;q.journal[0].kind=attack;
  q.sources=Array.from({length:50},()=>({id:attack,state:attack}));q.health.last_error=attack;
  ui.render({quant:q});
  for(const id of ['quantPositions','quantDecisions','quantJournal','quantSources']){assert.doesNotMatch(get(id).innerHTML,/<img|<script/);assert.match(get(id).innerHTML,/&lt;img/);}
  assert.equal((get('quantSources').innerHTML.match(/<article/g)||[]).length,12);
  assert.match(get('quantLastError').textContent,/<img/);
  ui.disconnected();for(const id of ['quantPositions','quantPerformance','quantComparison'])assert.doesNotMatch(get(id).innerHTML,/1,001 USDT|50,500|50,050/);
  assert.equal(get('pauseQuant').disabled,true);assert.equal(get('resumeQuant').disabled,true);
  ui.render({quant:initializedQuant({execution_enabled:true})});assert.equal(get('summaryQuantState').textContent,'SIN DATOS');
  ui.render({quant:initializedQuant({promotion_allowed:true})});assert.equal(get('summaryQuantState').textContent,'SIN DATOS');
});

test('Quant history is bounded to twelve decisions and journal entries without converting projections into simulated funding settlements',()=>{
  const {ui,get}=portal(),q=initializedQuant();
  q.decisions=Array.from({length:50},()=>({...q.decisions[0]}));
  q.journal=Array.from({length:50},()=>({kind:'MARGIN_STRESS_COST_SIMULATION',at:now(),stress_costs_usdt:.5,fees_usdt:.1,slippage_usdt:.2}));
  q.funding=[{...q.funding[0],state:'CONDITIONAL_PROJECTION_NOT_SETTLED'}];
  ui.render({quant:q});
  assert.equal((get('quantDecisions').innerHTML.match(/<article/g)||[]).length,12);
  assert.equal((get('quantJournal').innerHTML.match(/<article/g)||[]).length,12);
  assert.match(get('quantJournal').innerHTML,/Coste de estrés de margen simulado/);
  assert.match(get('quantJournal').innerHTML,/Coste de estrés simulado<\/dt><dd>0.5 USDT/);
  assert.match(get('quantFunding').innerHTML,/Una proyección no se contabiliza como ingreso/);
  assert.doesNotMatch(get('quantFunding').innerHTML,/0.2 USDT/);
});

test('real isolated Quant ledger projection renders positions, journal and funding limitations without simulated data becoming exchange execution',()=>{
  const {ui,get}=portal();
  const fixture=flags=>JSON.parse(execFileSync(process.env.PYTHON||'python',[
    fileURLToPath(new URL('../../tests/emit_quant_fixture.py',import.meta.url)),...flags],{encoding:'utf8'}));
  const dashboard=fixture([]);
  assert.equal(dashboard.quant.initialized,true);assert.equal(dashboard.quant.execution_enabled,false);
  ui.render(dashboard);
  assert.equal(get('summaryQuantState').textContent,'SHADOW ACTIVO');
  assert.match(get('quantPositions').innerHTML,/pierna hipotética/);
  assert.match(get('quantJournal').innerHTML,/Cohorte Shadow inicializada|Par hipotético abierto/);
  assert.match(get('quantDecisions').innerHTML,/Evidencia disponible al decidir/);
  const pending=fixture(['--pending']);
  assert.equal(pending.quant.data_quality.funding,'PENDING_AUTHORITATIVE_EVENTS');assert.equal(pending.quant.performance.equity,null);
  ui.render(pending);assert.equal(get('summaryQuantCapital').textContent,'—');
  assert.match(get('quantQuality').textContent,/Funding pendiente puede impedir valorar/);
});
