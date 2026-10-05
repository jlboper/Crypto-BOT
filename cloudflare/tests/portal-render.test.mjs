import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function fakeElement(id=''){
  const classes=new Set();
  return {
    id, textContent:'', innerHTML:'', className:'', value:'', hidden:false, disabled:false,
    dataset:{}, clientWidth:800, clientHeight:200,
    classList:{
      add:(...xs)=>xs.forEach(x=>classes.add(x)),
      remove:(...xs)=>xs.forEach(x=>classes.delete(x)),
      toggle:(x,on)=>{if(on===undefined){classes.has(x)?classes.delete(x):classes.add(x);}else{on?classes.add(x):classes.delete(x);}},
      contains:x=>classes.has(x),
    },
    addEventListener(){}, replaceChildren(){}, append(){}, appendChild(){}, scrollIntoView(){},
    closest(){return null;}, click(){},
    getContext(){return {
      scale(){},clearRect(){},fillText(){},beginPath(){},lineTo(){},moveTo(){},closePath(){},fill(){},stroke(){},
      createLinearGradient(){return {addColorStop(){}};},
      set fillStyle(v){},set font(v){},set strokeStyle(v){},set lineWidth(v){}
    };},
  };
}

test('v0.9 multi-asset portal snapshot renders without falling into disconnected state', async()=>{
  const source=readFileSync(new URL('../../web/app.js',import.meta.url),'utf8');
  const elements=new Map();
  const el=id=>{if(!elements.has(id))elements.set(id,fakeElement(id));return elements.get(id);};
  el('executionModeChoice').value='testnet';
  const document={
    hidden:false,
    getElementById:el,
    querySelector:()=>fakeElement('shell'),
    createElement:()=>fakeElement(),
  };
  const storage=new Map();
  const sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
  const responses={
    '/api/status':{mode:'TESTNET',equity:1002,cash:902,exposure:100,return_pct:.2,positions:1,max_positions:5,
      killed:false,ai_enabled:true,ai_model:'gpt-6-luna',risk:{risk_per_trade_pct:.0075,max_position_pct:.15,max_total_exposure_pct:.6,daily_loss_limit_pct:.02,weekly_loss_limit_pct:.05},
      paper_risk_profile:'normal',activity:{state:'operational',age_seconds:20,last_cycle_at:'2026-09-27T15:30:00Z'},
      observation_health:{state:'OK',samples:10,expected_samples:10,cycle_coverage_pct:100,average_cycle_gap_seconds:900,last_cycle_age_seconds:20,closed_trades:0,realized_pnl_usdt:0,integrity:{}}},
    '/api/positions':[{symbol:'BTCUSDT',quantity:.001,entry_price:100000,market_price:100100,unrealized_pnl:.1,unrealized_pct:.1,stop_price:97500,take_profit:105000,opened_at:'2026-09-27T12:00:00Z'}],
    '/api/trades':[], '/api/ai-reviews':[], '/api/equity':[{equity:1002,cash:902,exposure:100,created_at:'2026-09-27T15:30:00Z'}],
    '/api/events':[], '/api/research':{mode:'RESEARCH_ONLY',status:'NOT_RUN',assets:[]}, '/api/research/status':{running:false,error:null},
    '/api/paper-scorecard':{mode:'TESTNET',status:'INSUFFICIENT_EVIDENCE',equity_points:1,observed_days:1,closed_trades:0,
      net_realized_pnl_usdt:0,fees_usdt:0,sampled_max_drawdown_pct:0,win_rate_pct:null,open_positions:1,price_status:'fresh',
      estimated_open_pnl_usdt:.1,open_exposure_usdt:100,invalid_points:0,by_asset:[],attribution:{exit_reasons:[],market_preflight:{checked:0}}},
    '/api/futures-forward':{enabled:true,killed:false,symbols:['BTCUSDT','ETHUSDT','SOLUSDT'],automatic_leverage:1,
      positions:[],position:null,trades:[],equity:[{wallet_balance:4999.43,available_balance:4999.43,unrealized_pnl:0,created_at:'2026-09-27T15:30:00Z'}],
      closed_trades:0,gross_pnl:0,latest_signals:{BTCUSDT:{long_score:65,short_score:15},ETHUSDT:{long_score:40,short_score:30},SOLUSDT:{long_score:55,short_score:25}},
      last_ai_reviews:{},ai_model:'gpt-6-luna',guardrails:{margin_type:'ISOLATED',position_mode:'ONE_WAY',max_positions:3,forward_timeframe:'1h',forward_margin_usdt:100,forward_min_score:70,forward_minimum_stop_pct:.025,forward_stop_atr_multiple:2,forward_reward_to_risk:2},
      cycle_diagnostic:{state:'NO_OPPORTUNITIES',at:new Date().toISOString(),timeframe:'1h',minimum_score:70,symbols:3,evaluated:3,signals:0,reviews:0,opened:0,statuses:{FLAT:3}},
      recovery:{durable_order_journal:true,startup_position_reconciliation:true,separate_kill_switch:true},
      observation_health:{state:'OK',samples:10,expected_samples:10,cycle_coverage_pct:100,average_cycle_gap_seconds:900,last_cycle_age_seconds:20,closed_trades:0,realized_pnl_usdt:0,consecutive_errors:0,incident_total:0,failure_attempt_total:0,cycle_total:10,reason_codes:[],integrity:{order_journal_clear:true,local_position_count_valid:true,evidence_gap_clear:true}},
      scorecard:{observed_days:1,closed_trades:0,gross_realized_pnl_usdt:0,sampled_max_drawdown_pct:0,win_rate_pct:null,profit_factor:null,average_win_usdt:null,average_loss_usdt:null,expectancy_usdt_per_close:null,mae_mfe_available:false,long_closed_trades:0,long_gross_pnl_usdt:0,short_closed_trades:0,short_gross_pnl_usdt:0,error_total:0,incident_total:0,failure_attempt_total:0,cycle_total:10,consecutive_errors:0},
      shadow_scorecard:[]}
  };
  const window={
    devicePixelRatio:1,
    portalApi:async path=>{if(!(path in responses))throw new Error('missing mock '+path);return structuredClone(responses[path]);},
    paperControlsAvailable:()=>true, portalButtonBusy:()=>false,
    addEventListener(){},
  };
  const context={
    console,window,document,sessionStorage,
    location:{search:'',pathname:'/',hash:''},history:{replaceState(){}},
    navigator:{},URL,URLSearchParams,Blob,
    setInterval:()=>0,setTimeout,clearTimeout,
    confirm:()=>false,alert(){},
  };
  context.globalThis=context;
  vm.createContext(context);
  vm.runInContext(source+'\n;globalThis.__refresh=refresh;',context,{filename:'web/app.js'});
  await context.__refresh();
  assert.equal(el('botState').textContent,'OPERATIVO');
  assert.notEqual(el('botState').textContent,'PORTAL SIN CONEXIÓN');
  assert.match(el('operationSummary').textContent,/Motor TESTNET activo/);
  assert.match(el('equity').textContent,/1,002\.00 USDT/);
  assert.match(el('futuresForwardWallet').textContent,/4,999\.43 USDT/);
  assert.equal(el('futuresForwardPosition').textContent,'SIN POSICIÓN');
  assert.equal(el('futuresHealthCounters').textContent,'0 / 0 / 10');
  assert.equal(el('futuresConfiguredTimeframe').textContent,'1H');
  assert.equal(el('futuresCycleState').textContent,'SIN OPORTUNIDADES');
  assert.match(el('futuresCycleSummary').textContent,/3 contratos evaluados en 1H.*score mínimo 70\/100/);
  assert.match(el('futuresCycleReasons').textContent,/3: sin señal LONG\/SHORT/);
  const futures=responses['/api/futures-forward'];
  futures.cycle_diagnostic={state:'ATTENTION',at:new Date().toISOString(),timeframe:'1h',minimum_score:70,
    symbols:3,evaluated:1,signals:0,reviews:0,opened:0,statuses:{FLAT:1,ASSET_UNAVAILABLE:2},
    issues:[
      {symbol:'ATOMUSDT',status:'ASSET_UNAVAILABLE',reason:'Futures Demo reference price unavailable: ATOMUSDT'},
      {symbol:'NEARUSDT',status:'ASSET_UNAVAILABLE',reason:'Futures Demo quantity filters unavailable'},
    ]};
  await context.__refresh();
  assert.equal(el('futuresCycleState').textContent,'REQUIERE ATENCIÓN');
  assert.equal(el('futuresForwardState').textContent,'ACTIVO · DATOS PARCIALES');
  assert.equal(el('futuresHealthState').textContent,'VIGILAR');
  assert.equal(el('observationHealthState').textContent,'VIGILAR');
  assert.match(el('futuresHealthReason').textContent,/bloqueo parcial/);
  assert.match(el('futuresCycleSummary').textContent,/3 contratos.*1 evaluados.*0 señales.*0 revisiones IA/);
  assert.match(el('futuresMultiAsset').innerHTML,/dato histórico/);
  assert.doesNotMatch(el('futuresMultiAsset').innerHTML,/65 \/ 15/);
  futures.latest_signals.BTCUSDT={long_score:65,short_score:15,at:new Date().toISOString(),timeframe:'1h'};
  futures.cycle_diagnostic.issues.push({symbol:'BTCUSDT',status:'ASSET_UNAVAILABLE',reason:'Reference <missing>'});
  await context.__refresh();
  assert.match(el('futuresMultiAsset').innerHTML,/Score LONG \/ SHORT · sobre 100/);
  assert.match(el('futuresMultiAsset').innerHTML,/65 \/ 15/);
  assert.match(el('futuresMultiAsset').innerHTML,/DATOS NO DISPONIBLES/);
  assert.match(el('futuresMultiAsset').innerHTML,/Reference &lt;missing&gt;/);
  futures.latest_signals.BTCUSDT.at=new Date(Date.now()-7200000).toISOString();
  await context.__refresh();
  assert.doesNotMatch(el('futuresSignalGrid').innerHTML,/65 \/ 15/);
  assert.match(el('futuresSignalGrid').innerHTML,/DATO HISTÓRICO/);
  futures.cycle_diagnostic.at=new Date(Date.now()-3600000).toISOString();
  await context.__refresh();
  assert.equal(el('futuresForwardState').textContent,'SIN ANÁLISIS RECIENTE');
  assert.equal(el('futuresCycleState').textContent,'SIN DATOS RECIENTES');
  assert.doesNotMatch(el('futuresMultiAsset').innerHTML,/Reference &lt;missing&gt;/);

  futures.cycle_diagnostic.at=new Date().toISOString();
  await context.__refresh();
  assert.match(el('futuresCycleReasons').textContent,/ATOM: Futures Demo reference price unavailable/);
  assert.match(el('futuresCycleReasons').textContent,/NEAR: Futures Demo quantity filters unavailable/);
  futures.cycle_diagnostic={state:'NO_OPPORTUNITIES',at:new Date().toISOString(),timeframe:'1h',minimum_score:70,
    symbols:3,evaluated:3,signals:0,reviews:0,opened:0,statuses:{FLAT:3},issues:[]};
  futures.symbols=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'];
  futures.leverage_trials={levels:[1,2,3],next_leverage:3,fixed_notional:true,notional_limit_usdt:100,
    results:[1,2,3].map(leverage=>({leverage,closed_trades:0,gross_pnl_usdt:0}))};
  await context.__refresh();
  assert.equal(el('futuresLimitLeverage').textContent,'1x / 2x / 3x');
  assert.equal(el('futuresHealthState').textContent,'ESTABLE');
  assert.equal(el('futuresConfiguredSymbols').textContent,'BTC / ETH / SOL / BNB / XRP');
  assert.match(el('futuresLeverageTrials').innerHTML,/Próxima entrada: 3x/);
  assert.match(el('futuresLeverageTrials').innerHTML,/sin comparación de rentabilidad equivalente/);
  futures.symbols.push('ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT','DOTUSDT','LTCUSDT','BCHUSDT','TRXUSDT','ATOMUSDT','NEARUSDT');
  Object.assign(futures.guardrails,{max_positions:5,forward_total_notional_usdt:300,forward_total_stop_loss_usdt:7.5});
  futures.portfolio_budget={notional_limit_usdt:300,stop_loss_limit_usdt:7.5,cost_buffer_pct:.005,notional_usdt:120,stop_loss_usdt:3.5,at:'2026-10-04T03:00:00Z'};
  await context.__refresh();
  assert.match(el('futuresConfiguredSymbols').textContent,/ATOM \/ NEAR$/);
  assert.equal(el('futuresConfiguredPositions').textContent,'5 posiciones máx.');
  assert.match(el('futuresPortfolioBudget').textContent,/120.00 USDT \/ 300.00 USDT/);
  assert.match(el('futuresPortfolioBudget').textContent,/3.50 USDT \/ 7.50 USDT/);
  assert.match(el('futuresPortfolioBudget').textContent,/costos reales pueden superar/);


  Object.assign(futures.scorecard,{observed_days:31,closed_trades:40,strategy_closed_trades:1,
    technical_closed_trades:39,strategy_win_rate_pct:100,strategy_profit_factor:999});
  futures.shadow_scorecard=[{strategy_key:'old',legacy_measurement:true,pnl_pct:50,trades:2},
    {strategy_key:'v2-s70',legacy_measurement:false,pnl_pct:10,trades:1}];
  await context.__refresh();
  assert.equal(el('futuresEvidenceState').textContent,'EVIDENCIA INSUFICIENTE');
  assert.match(el('futuresEvidenceNote').textContent,/1 cierres de estrategia; 39 cierres técnicos/);
  assert.match(el('futuresShadowStrategies').innerHTML,/No es retorno de cartera/);
  assert.doesNotMatch(el('futuresShadowStrategies').innerHTML,/>old</);
  futures.scorecard.risk_halt={active:true,period:'daily'};
  await context.__refresh();
  assert.equal(el('futuresForwardState').textContent,'LÍMITE DE PÉRDIDA · PROTECCIONES ACTIVAS');
  assert.equal(el('futuresLimitState').textContent,'ENTRADAS BLOQUEADAS POR PÉRDIDA');
  futures.recovery.native_exchange_stop_orders=true;
  futures.positions=[{symbol:'BTCUSDT',direction:'LONG',leverage:1,entry_price:100,quantity:.1,stop_price:95,take_profit:110}];
  futures.native_protection={supported:true,positions:{BTCUSDT:{status:'UNCONFIRMED',error:'Consulta pendiente'}}};
  responses['/api/status'].native_protection={supported:true,positions:{BTCUSDT:{status:'UNCONFIRMED'}}};
  await context.__refresh();
  assert.match(el('futuresMultiAsset').innerHTML,/UNCONFIRMED/);
  assert.match(el('futuresForwardSafety').textContent,/0 pares confirmados/);
  assert.match(el('operationSummary').textContent,/0\/1 posiciones con OCO confirmado/);
  futures.native_protection.positions.BTCUSDT.status='ARMED';
  responses['/api/status'].native_protection.positions.BTCUSDT.status='ARMED';
  await context.__refresh();
  assert.match(el('futuresMultiAsset').innerHTML,/CONFIRMADA EN BINANCE/);
  assert.match(el('futuresForwardSafety').textContent,/1 pares confirmados/);
  assert.match(el('operationSummary').textContent,/1\/1 posiciones con OCO confirmado/);

  // Technical repairs are not trading-strategy observations.
  Object.assign(futures.scorecard,{closed_trades:38,strategy_closed_trades:0,technical_closed_trades:38,
    strategy_gross_pnl_usdt:0,strategy_win_rate_pct:null,strategy_profit_factor:null,
    win_rate_pct:15.8,profit_factor:.14});
  futures.equity=[{wallet_balance:5000,unrealized_pnl:12}];
  futures.last_ai_reviews={BTCUSDT:{verdict:'REJECT',at:'2026-10-03T10:00:00Z'},
    ETHUSDT:{verdict:'ALLOW',at:'2026-10-02T10:00:00Z'}};
  await context.__refresh();
  assert.equal(el('futuresObservedTrades').textContent,'0');
  assert.equal(el('futuresTechnicalTrades').textContent,'38');
  assert.equal(el('futuresObservedQuality').textContent,'— / —');
  assert.equal(el('futuresForwardClosed').textContent,'0 de estrategia · 38 técnicos');
  assert.match(el('futuresEvidenceMetrics').innerHTML,/P&amp;L de estrategia bruto/);
  assert.match(el('futuresForwardAi').textContent,/^BTC · REJECT · \d+%$/);
  assert.equal(el('futuresPositionPrices').textContent,'100');
  assert.equal(el('futuresPositionUnrealized').textContent,'Sin cotización por contrato');
  assert.match(el('futuresAccountUnrealized').textContent,/12\.00 USDT/);
  // A second contract cannot inherit account-wide P&L or an invented mark.
  futures.positions.push({symbol:'ETHUSDT',direction:'SHORT',quantity:1,entry_price:200,
    stop_price:210,take_profit:180,leverage:1});
  await context.__refresh();
  assert.equal(el('futuresPositionCard').hidden,true);
  assert.match(el('futuresMultiAsset').innerHTML,/1 \/ 200/);
  assert.equal(el('futuresPositionPrices').textContent,'—');
  assert.equal(vm.runInContext('futuresEquityValue({wallet_balance:5000,unrealized_pnl:-25})',context),4975);
  assert.equal(vm.runInContext('futuresEquityValue({wallet_balance:5000})',context),null);
  Object.assign(futures.scorecard,{observed_days:31,strategy_closed_trades:30,consecutive_errors:2});
  Object.assign(responses['/api/paper-scorecard'],{observed_days:31,closed_trades:30});
  await context.__refresh();
  assert.equal(el('dualEvidenceState').textContent,'ACUMULANDO DATOS');
  responses['/api/research']={mode:'RESEARCH_ONLY',auto_promotion:false,generated_at:'2026-10-04T00:00:00Z',
    assets:[],futures_assets:[{symbol:'BTCUSDT',champion_candidate:'trend',oos_return_pct:-2,folds:[{}],
      holdout:{net_return_pct:-1},double_cost_holdout:{net_return_pct:-2},discarded_reasons:['forward_test_independent']}],
    joint_portfolios:[{market:'FUTURES',profile:'base',leverage:10,initial_cash:1000,net_return_pct:-2,
      max_drawdown_pct:3,closed_trades:20,fees:2,funding_cost:1,liquidations:0,limits:{risk_pct:.5,gross_pct:80},
      holdout:{net_return_pct:-1},double_cost_holdout:{net_return_pct:-2},curve:[{time:1,equity:1000},{time:2,equity:980}],
      discarded_reasons:['Falta forward test independiente']}],
    history:[{generated_at:'2026-10-04T00:00:00Z',assets:30,futures_assets:15,scenarios:[{market:'FUTURES',profile:'base',leverage:10,net_return_pct:-2,max_drawdown_pct:3,closed_trades:20,liquidations:0}]}],
    forward_observation:[{market:'FUTURES',status:'WAITING_NEW_DATA',observed_days:0,symbols:['BTCUSDT']}]};
  responses['/api/research/status']={running:false,automatic:true,last_completed_at:'2026-10-04T00:00:00Z',next_run_at:'2026-10-05T00:00:00Z',error:null};
  await context.__refresh();
  assert.match(el('researchSchedule').textContent,/cada 24 h/);
  assert.equal(el('researchButton').textContent,'Actualizar análisis ahora');
  assert.match(el('researchPortfolios').innerHTML,/10x/);
  assert.match(el('researchHistory').innerHTML,/30 \/ 15/);
  assert.match(el('researchForward').innerHTML,/Esperando velas/);
  assert.match(el('researchFuturesAssets').innerHTML,/Falta forward independiente/);
  assert.notEqual(el('botState').textContent,'PORTAL SIN CONEXIÓN');

  responses['/api/research/status'].error='Análisis detenido: ValueError';
  await context.__refresh();
  assert.match(el('researchSchedule').textContent,/informe anterior.*0 activos Spot y 1 Futures/);
  const riskProfiles={minimo:.25,leve:.35,prudente:.5,moderado:.65,alto:.85,normal:1};
  for(const [name,fraction] of Object.entries(riskProfiles)){
    responses['/api/status'].paper_risk_profile=name;
    await context.__refresh();
    assert.equal(Number(el('riskTrade').textContent.replace('%','')),Number((.75*fraction).toFixed(2)));
  }
  Object.assign(responses['/api/paper-scorecard'],{win_rate_pct:25,profit_factor:.39,expectancy_usdt_per_close:-1.69});
  await context.__refresh();
  assert.equal(el('spotObservedQuality').textContent,'25.0% / 0.39');
  assert.equal(el('spotObservedReturn').textContent,'+0.20%');
  assert.equal(el('futuresObservedExpectancy').textContent,'0.00 USDT');
  assert.match(el('spotObservedExpectancy').textContent,/-1.69 USDT/);
  assert.match(el('futuresMoreMetrics').innerHTML,/ATRIBUCIÓN PENDIENTE/);

  // Last-cycle evidence is distinct from the engine heartbeat and expires in the browser.
  const status=responses['/api/status'];
  delete status.spot_cycle;
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'SIN DETALLE AÚN');
  status.spot_cycle={state:'NO_OPPORTUNITIES',at:new Date().toISOString(),universe:30,evaluated:30,
    signals:0,candidates:0,reviews:0,opened:0,reasons:{BELOW_SCORE:30},minimum_score:75,
    btc_bullish:false,error_code:null,age_seconds:0,fresh:true};
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'TRABAJANDO · SIN OPORTUNIDADES');
  assert.match(el('spotCycleSummary').textContent,/30 evaluadas.*0 señales de compra/);
  assert.match(el('spotCycleReasons').textContent,/30: no alcanzan el score mínimo/);
  Object.assign(status.spot_cycle,{state:'FILTERED',signals:1,candidates:1,reviews:1,reasons:{AI_REJECTED:1}});
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'CANDIDATAS DESCARTADAS');
  assert.match(el('spotCycleReasons').textContent,/descartadas por la revisión IA/);
  Object.assign(status.spot_cycle,{state:'ATTENTION',reasons:{AI_UNAVAILABLE:1}});
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'REQUIERE ATENCIÓN');
  Object.assign(status.spot_cycle,{state:'ERROR',error_code:'FRESH_PRICES_UNAVAILABLE',reasons:{CYCLE_ERROR:1}});
  status.activity.state='offline';
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'ERROR EN EL CICLO');
  assert.match(el('spotCycleSummary').textContent,/cotizaciones recientes no disponibles/);
  assert.match(el('spotCycleState').className,/offline/);
  status.activity.state='operational';
  Object.assign(status.spot_cycle,{state:'NO_OPPORTUNITIES',error_code:null,
    at:new Date(Date.now()-3600000).toISOString(),fresh:true});
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'SIN DATOS RECIENTES');
  status.spot_cycle.at=new Date().toISOString();
  status.killed=true;
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'NUEVAS ENTRADAS PAUSADAS');
  status.killed=false;
  await context.__refresh();
  window.portalApi=async()=>{throw Error('synthetic disconnect');};
  await context.__refresh();
  assert.equal(el('spotCycleState').textContent,'SIN DATOS RECIENTES');
  assert.equal(el('spotCycleReasons').textContent,'');

});
