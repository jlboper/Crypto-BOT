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
      last_ai_reviews:{},ai_model:'gpt-6-luna',guardrails:{margin_type:'ISOLATED',position_mode:'ONE_WAY',max_positions:3,forward_margin_usdt:100,forward_min_score:75,forward_minimum_stop_pct:.025,forward_stop_atr_multiple:2,forward_reward_to_risk:2},
      recovery:{durable_order_journal:true,startup_position_reconciliation:true,separate_kill_switch:true},
      observation_health:{state:'OK',samples:10,expected_samples:10,cycle_coverage_pct:100,average_cycle_gap_seconds:900,last_cycle_age_seconds:20,closed_trades:0,realized_pnl_usdt:0,consecutive_errors:0,integrity:{order_journal_clear:true,local_position_count_valid:true}},
      scorecard:{observed_days:1,closed_trades:0,gross_realized_pnl_usdt:0,sampled_max_drawdown_pct:0,win_rate_pct:null,profit_factor:null,long_closed_trades:0,long_gross_pnl_usdt:0,short_closed_trades:0,short_gross_pnl_usdt:0,error_total:0,cycle_total:10,consecutive_errors:0},
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
  assert.equal(el('futuresForwardPosition').textContent,'Sin posición');
});
