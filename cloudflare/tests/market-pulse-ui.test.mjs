import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function portal({hash='',shellHidden=false}={}){
  const elements=new Map(),calls=[],listeners=new Map(),shell={hidden:shellHidden};
  const get=id=>{
    if(!elements.has(id))elements.set(id,{id,textContent:'',innerHTML:'',className:'',dataset:{},disabled:false,
      listeners:{},classList:{add(){},remove(){},toggle(){}},
      addEventListener(name,callback){this.listeners[name]=callback;},
      scrollIntoView(){this.scrolled=(this.scrolled||0)+1;}});
    return elements.get(id);
  };
  const document={getElementById:get,querySelector:selector=>selector==='.shell'?shell:null,querySelectorAll:()=>[]};
  const window={addEventListener(name,callback){listeners.set(name,callback);},paperControlsAvailable:()=>true,portalButtonBusy:()=>false,
    portalApi:async(path,options)=>{calls.push({path,options});return {status:'pending'};}};
  const context=vm.createContext({window,document,URL,URLSearchParams,Date,
    location:{search:'',pathname:'/',hash},sessionStorage:{getItem:()=>null},history:{replaceState(){}},
    setInterval:()=>0,setTimeout,clearTimeout,console,navigator:{}});
  vm.runInContext(readFileSync(new URL('../../web/app.js',import.meta.url),'utf8'),context);
  // Control tests inspect only the new isolated UI controller, without API reads from older engines.
  vm.runInContext('refresh=async()=>globalThis.__testRefresh?.();',context);
  return {ui:window.PulsePortal,get,calls,window,shell,listeners,setRefresh:callback=>{context.__testRefresh=callback;}};
}

function snapshot(overrides={}){
  return {schema:1,engine:'AI_MARKET_PULSE',enabled:true,controls_available:true,mode:'SHADOW',state:'SHADOW',
    at:new Date().toISOString(),updated_at:new Date().toISOString(),freshness:{state:'FRESH',age_seconds:1},
    execution_enabled:false,sources:{binance_ws:{state:'CONNECTED',last_update:new Date().toISOString()}},
    stats:{events_analyzed:0,relevant_news:0,opportunities:0,accepted:0,rejected:0},
    market:[],events:[],opportunities:[],decisions:[],positions:[],performance:{environment:'SHADOW',
      initial_capital:1000,cash:1000,equity:1000,net_pnl:0,return_pct:0,drawdown_pct:0,closed_trades:0,
      win_rate_pct:null,profit_factor:null,exposure:0,observation_days:0,costs:0,data_quality:'WARMING_UP'},
    health:{},research:{state:'FORWARD_ONLY',hypothesis_version:'pulse-v1',limitations:[]},...overrides};
}

test('deep navigation opens collapsed ancestors and rejects unknown targets',()=>{
  const {ui,get}=portal();
  const outer={tagName:'DETAILS',open:false,parentElement:null};
  const target=get('pulse-news');target.tagName='DETAILS';target.open=false;target.parentElement=outer;
  assert.equal(ui.revealSection('pulse-news',false),true);
  assert.equal(target.open,true);assert.equal(outer.open,true);
  assert.equal(ui.revealSection('untrusted-target',false),false);
});

test('provider status distinguishes available feeds and fallback standby',()=>{
  const {ui,get}=portal();
  ui.render(snapshot({sources:{binance_ws:{state:'CONNECTED'},binance_rest:{state:'STANDBY'},news:{state:'READY'}},
    news_providers:[{id:'sec',name:'SEC',kind:'regulatory',url:'https://www.sec.gov/news/pressreleases.rss',state:'READY',last_update:null,last_error:null}]}),{},{});
  assert.match(get('summaryPulseSources').textContent,/2\/2 fuentes activas.*respaldo disponible/);
  assert.match(get('pulseProviderSummary').textContent,/1\/1 fuentes disponibles/);
  assert.match(get('pulseNewsProviders').innerHTML,/REGULATORIA/);
});

test('legacy or absent Pulse snapshots show unavailable evidence instead of fabricated zeros',()=>{
  const {ui,get}=portal();
  ui.render(null,{mode:'TESTNET',equity:1002,exposure:100,positions:1,return_pct:.2,activity:{state:'operational'}},{});
  assert.equal(get('summaryPulseState').textContent,'SIN DATOS');
  assert.equal(get('summaryPulseReturn').textContent,'—');
  assert.equal(get('summaryPulseEvents').textContent,'— / —');
  assert.match(get('pulsePerformance').innerHTML,/Capital hipotético inicial<\/dt><dd>—/);
  assert.doesNotMatch(get('pulsePerformance').innerHTML,/NaN|undefined|0 USDT/);
  assert.equal(get('pauseMarketPulse').disabled,true);
  assert.equal(get('summarySpotState').textContent,'OPERATIVO');
  assert.equal(get('summarySpotCapital').textContent,'1,002 USDT');
  assert.match(get('pulseStatusNote').textContent,/no se infiere un fallo/);
});

test('Shadow warmup, valid zeros, null trade statistics, stale data and disabled controls remain distinct',()=>{
  const {ui,get}=portal();
  ui.render(snapshot({state:'WARMING_UP'}));
  assert.equal(get('summaryPulseState').textContent,'ACUMULANDO MUESTRAS');
  assert.equal(get('summaryPulseEvents').textContent,'0 / 0');
  assert.equal(get('summaryPulseReturn').textContent,'0%');
  assert.match(get('pulsePerformance').innerHTML,/Win rate<\/dt><dd>—/);
  assert.match(get('pulsePerformance').innerHTML,/Profit factor<\/dt><dd>—/);
  assert.match(get('pulseNews').innerHTML,/ausencia de noticias no es un error/);
  assert.equal(get('pauseMarketPulse').disabled,false);
  ui.render(snapshot({state:'DEGRADED',freshness:{state:'STALE',age_seconds:120},controls_available:false,
    market:[{symbol:'BTCUSDT',price:123,fresh:false,complete:true,change_1m_pct:null}]}));
  assert.equal(get('pulseFreshness').textContent,'ANTIGUO · 120 s');
  assert.match(get('pulseMarket').innerHTML,/ANTIGUO \/ SIN DATOS/);
  assert.match(get('platformAlerts').textContent,/Market Pulse: datos parciales · antiguo/);
  assert.equal(get('pauseMarketPulse').disabled,true);
  ui.disconnected();
  assert.equal(get('summaryPulseState').textContent,'LECTURA NO DISPONIBLE');
  assert.match(get('platformAlerts').textContent,/valores anteriores son históricos/);
});

test('untrusted news, URLs, provider failures and frozen decision evidence cannot inject executable markup',()=>{
  const {ui,get}=portal();
  const malicious='<img src=x onerror="window.stolen=true">';
  ui.render(snapshot({
    events:[{symbol:'BTCUSDT',title:malicious,url:'javascript:alert(1)',source:malicious,
      impact:'uncertain',kind:'rumor',credibility:.2,received_at:'2026-10-15T12:02:00Z'},
      {symbol:'ETHUSDT',title:'Anuncio oficial',url:'https://www.binance.com/en/support/announcement',
        source:'Binance',impact:'neutral',kind:'official',received_at:'2026-10-15T12:03:00Z'}],
    decisions:[{id:'id-1',at:'2026-10-15T12:02:03Z',symbol:malicious,action:'REJECT',score:15,
      confidence:.4,reason:malicious,favorable:[malicious],risks:[malicious],evidence:{received_at:'2026-10-15T12:02:00Z',headline:malicious}}],
    health:{last_error:malicious},
  }));
  for(const id of ['pulseNews','pulseDecisions']){
    assert.doesNotMatch(get(id).innerHTML,/<img|javascript:|<script/);
    assert.match(get(id).innerHTML,/&lt;img/);
  }
  assert.match(get('pulseNews').innerHTML,/href="https:\/\/www.binance.com/);
  assert.match(get('pulseNews').innerHTML,/rel="noopener noreferrer"/);
  assert.ok(get('pulseNews').innerHTML.indexOf('Anuncio oficial')<get('pulseNews').innerHTML.indexOf('&lt;img'));
  assert.match(get('pulseDecisions').innerHTML,/Información disponible al decidir/);
  assert.match(get('pulseDecisions').innerHTML,/2026-10-15T12:02:00Z/);
  assert.equal(get('pulseLastError').textContent,'Último diagnóstico: '+malicious);
  for(const url of ['javascript:alert(1)','data:text/html,evil','https://owner:secret@example.com','http://example.com'])assert.equal(ui.safeUrl(url),null);
});

test('an old remote projection cannot make an old FRESH engine snapshot look current',()=>{
  const {ui,get}=portal();
  ui.render(snapshot({remote_sync_stale:true}));
  assert.match(get('pulseFreshness').textContent,/PROYECCIÓN ANTIGUA/);
  assert.equal(get('summaryPulseState').textContent,'SHADOW');
  assert.match(get('pulseStatusNote').textContent,/no demuestra que el motor se haya detenido/);
  assert.equal(get('pauseMarketPulse').disabled,true);
  ui.render(snapshot({at:new Date(Date.now()-180000).toISOString()}));
  assert.match(get('pulseFreshness').textContent,/PROYECCIÓN ANTIGUA/);
  assert.match(get('platformAlerts').textContent,/operación actual sin verificar/);
});

test('stale Pulse projections suppress current valuations and qualify provider status as last-known',()=>{
  const {ui,get}=portal(),p=snapshot({remote_sync_stale:true,
    news_providers:[{id:'sec',name:'SEC',kind:'regulatory',state:'READY',url:'https://www.sec.gov/news/pressreleases.rss',last_update:new Date().toISOString()}],
    positions:[{symbol:'BTCUSDT',quantity:1,entry_price:100,mark_price:140,stop:90,target:150,unrealized_pnl:39.8}]});
  Object.assign(p.performance,{cash:800,equity:1039.8,net_pnl:39.8,return_pct:3.98,exposure:140,closed_trades:4,costs:2,benchmark_buy_hold:{BTCUSDT:4}});
  ui.render(p);
  assert.equal(get('summaryPulseReturn').textContent,'—');
  for(const label of ['Efectivo hipotético','Equity hipotético','P&amp;L neto simulado','Retorno simulado','Exposición hipotética'])assert.ok(get('pulsePerformance').innerHTML.includes(`${label}</dt><dd>—`));
  assert.match(get('pulsePerformance').innerHTML,/Cierres hipotéticos<\/dt><dd>4/);
  assert.match(get('pulseComparison').innerHTML,/Retorno simulado<\/dt><dd>—/);
  assert.match(get('pulsePositions').innerHTML,/Entrada \/ mark<\/dt><dd>100 \/ —/);
  assert.match(get('pulsePositions').innerHTML,/P&amp;L abierto hipotético<\/dt><dd>—/);
  assert.match(get('pulseBenchmark').textContent,/benchmarks actuales no disponibles/);
  assert.equal(get('pulseFinanceQuality').textContent,'VALORACIÓN ANTIGUA');
  assert.match(get('pulseProviderSummary').textContent,/Último estado: 1\/1 listas · antiguo/);
  assert.match(get('pulseNewsProviders').innerHTML,/Último estado: DISPONIBLE · ANTIGUO/);
  assert.match(get('summaryPulseSources').textContent,/Último estado:/);
  assert.equal(p.performance.equity,1039.8,'Rendering must not rewrite persisted producer data');
  p.remote_sync_stale=false;p.freshness={state:'STALE',age_seconds:31};
  ui.render(p);assert.equal(get('summaryPulseReturn').textContent,'—');
  p.freshness={state:'FRESH',age_seconds:0};ui.render(p);
  assert.equal(get('summaryPulseReturn').textContent,'+3.98%');
  assert.match(get('pulseProviderSummary').textContent,/1\/1 fuentes disponibles/);
});

test('authenticated portal-ready waits for refresh then reopens and scrolls the deep-linked fold',async()=>{
  const {ui,get,shell,listeners,setRefresh}=portal({hash:'#pulse-news',shellHidden:true});
  const target=get('pulse-news'),outer={tagName:'DETAILS',open:false,parentElement:null};
  target.tagName='DETAILS';target.open=false;target.parentElement=outer;
  ui.init();
  assert.equal(target.open,true);assert.equal(target.scrolled,undefined,'Hidden login state must not scroll the page');
  target.open=false;outer.open=false;
  let finishRefresh;
  setRefresh(()=>new Promise(resolve=>{finishRefresh=()=>{shell.hidden=false;resolve();};}));
  const pending=listeners.get('portal-ready')();
  assert.equal(target.open,false,'Deep link must wait for authenticated refresh');
  finishRefresh();await pending;
  assert.equal(target.open,true);assert.equal(outer.open,true);assert.equal(target.scrolled,1);
  shell.hidden=true;setRefresh(async()=>{});target.open=false;
  await listeners.get('portal-ready')();assert.equal(target.open,false,'Failed authentication must not reveal hidden content');
});

test('independent pause remains pending until observed state confirms it and cannot send a second action',async()=>{
  const {ui,get,calls}=portal();
  ui.init();ui.render(snapshot());
  await get('pauseMarketPulse').listeners.click();
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/market-pulse/pause');
  assert.equal(calls[0].options.body,'{}');
  assert.equal(get('pauseMarketPulse').disabled,true);
  ui.render(snapshot());
  assert.equal(get('resumeMarketPulse').disabled,true);
  await get('pauseMarketPulse').listeners.click();assert.equal(calls.length,1);
  ui.render(snapshot({state:'PAUSED'}));
  assert.equal(get('pauseMarketPulse').disabled,true);
  assert.equal(get('resumeMarketPulse').disabled,false);
  assert.match(get('pulseControlMessage').textContent,/Windows confirmó/);
  await get('resumeMarketPulse').listeners.click();
  assert.equal(calls[1].path,'/api/market-pulse/resume');
  assert.equal(calls[1].options.body,'{}');
});

test('summary uses isolated financial environments, complete equity and actual protection evidence',()=>{
  const {ui,get}=portal();
  ui.render(snapshot(),{mode:'TESTNET',equity:1000,exposure:80,positions:1,return_pct:1,
    activity:{state:'operational'},native_protection:{positions:{BTCUSDT:{status:'ARMED'}}}},
  {enabled:true,positions:[{symbol:'ETHUSDT',direction:'SHORT',leverage:2}],
    equity:[{wallet_balance:2000,unrealized_pnl:-5}],portfolio_budget:{notional_usdt:30,stop_loss_usdt:.75},
    scorecard:{account_return_pct:-.25,consecutive_errors:0},native_protection:{positions:{ETHUSDT:{status:'ARMED'}}}},
  [{symbol:'BTCUSDT'}]);
  assert.equal(get('summaryFuturesCapital').textContent,'1,995 USDT');
  assert.equal(get('summaryFuturesPositions').textContent,'0 / 1 · 2x');
  assert.equal(get('summaryFuturesExposure').textContent,'30 USDT / 0.75 USDT');
  assert.equal(get('summarySpotProtection').textContent,'1/1 OCO confirmados');
  assert.match(get('pulseComparison').innerHTML,/SHADOW · ejecución conservadora simulada/);
  assert.match(get('pulseBenchmark').textContent,/no son comparables como una sola cartera/);
});

test('symbol keyed buy-and-hold references render without implying matched observation periods',()=>{
  const {ui,get}=portal(),p=snapshot();
  p.performance.benchmark_buy_hold={BTCUSDT:1.25,ETHUSDT:-.5,SOLUSDT:null,untrusted:'bad'};
  p.performance.benchmark_cash_return_pct=0;
  ui.render(p);
  assert.match(get('pulseBenchmark').textContent,/BTCUSDT \+1.25% · ETHUSDT -0.5%/);
  assert.match(get('pulseBenchmark').textContent,/no contiene fechas ni muestras emparejadas/);
  assert.doesNotMatch(get('pulseBenchmark').textContent,/untrusted|SOLUSDT|sin suficientes muestras/);
});

test('Research Lab shows captured Pulse evidence and replay limitations while hiding older reports',()=>{
  const {ui,get}=portal();
  ui.renderResearch(undefined);assert.equal(get('researchMarketPulse').hidden,true);
  ui.renderResearch({engine:'AI_MARKET_PULSE',mode:'SHADOW',state:'FORWARD_ONLY',hypothesis_version:'pulse-v1',
    captured_at:'2026-10-15T12:00:00Z',decisions:42,events:3,closed_trades:0,observation_days:1.25,
    replay:{checked:40,mismatches:1,invalid_timestamps:1},automatic_promotion:false,historical_backtest_valid:false,
    out_of_sample_validated:false,limitations:['<script>untrusted</script>']});
  assert.equal(get('researchMarketPulse').hidden,false);
  assert.match(get('researchPulseObservation').textContent,/42 decisiones · 3 eventos · 0 cierres hipotéticos · 1.25 días/);
  assert.match(get('researchPulseReplay').textContent,/40 decisiones comprobadas · 1 divergencias · 1 timestamps inválidos/);
  assert.match(get('researchPulseLimitations').textContent,/fuera de muestra: pendiente. Promoción automática bloqueada/);
  assert.equal(get('researchPulseLimitations').innerHTML,'');
  ui.renderResearch(undefined);assert.equal(get('researchMarketPulse').hidden,true);
  assert.equal(get('researchPulseObservation').textContent,'');
});
