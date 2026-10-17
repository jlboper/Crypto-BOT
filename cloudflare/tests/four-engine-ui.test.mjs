import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function portal(){
  const elements=new Map();
  const get=id=>{
    if(!elements.has(id))elements.set(id,{id,textContent:'',innerHTML:'',className:'',dataset:{},disabled:false,
      classList:{add(){},remove(){},toggle(){}},addEventListener(){},scrollIntoView(){}});
    return elements.get(id);
  };
  const document={getElementById:get,querySelector:()=>null,querySelectorAll:()=>[]};
  const window={addEventListener(){},paperControlsAvailable:()=>true,portalButtonBusy:()=>false,portalApi:async()=>{throw new Error('not configured');}};
  const context=vm.createContext({window,document,URL,URLSearchParams,Date,location:{search:'',pathname:'/',hash:''},
    sessionStorage:{getItem:()=>null},history:{replaceState(){}},setInterval:()=>0,setTimeout,clearTimeout,console,navigator:{}});
  vm.runInContext(readFileSync(new URL('../../web/app.js',import.meta.url),'utf8'),context);
  return {ui:window.FourEnginePortal,folds:window.PulsePortal,get};
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
  assert.equal(get('startQuant').disabled,true);
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
  assert.equal(get('startQuant').disabled,true);assert.doesNotMatch(get('guardianScopes').innerHTML,/100 USDT/);
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
