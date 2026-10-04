import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { pbkdf2Sync } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import worker, { sha256 } from '../src/worker.mjs';

// Real SQLite executes the same parameterized SQL; workerd/D1 is tested separately.
class LocalD1 {
  constructor(){this.sqlite=new DatabaseSync(':memory:');for(const name of ['0001_portal.sql','0002_jobs.sql','0003_owner_password.sql','0004_bot_releases.sql'])this.sqlite.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));}
  prepare(sql){
    const db=this;
    const make=args=>({
      bind:(...values)=>make(values),
      _all:()=>db.sqlite.prepare(sql).all(...args),
      async all(){return {results:this._all(),success:true};},
      async first(){return this._all()[0]||null;},
      async run(){return {results:this._all(),success:true};},
    });
    return make([]);
  }
  async batch(queries){
    this.sqlite.exec('BEGIN IMMEDIATE');
    try{const result=queries.map(q=>({results:q._all(),success:true}));this.sqlite.exec('COMMIT');return result;}
    catch(error){this.sqlite.exec('ROLLBACK');throw error;}
  }
  close(){this.sqlite.close();}
}

const origin='https://paper.example.workers.dev';
const owner='A'.repeat(43), device='B'.repeat(43);
const proof=(password,salt)=>pbkdf2Sync(password,salt,600000,32,'sha256').toString('hex');
const snapshot=()=>({mode:'PAPER',equity:1000,cash:900,exposure:100,positions:[{symbol:'BTCUSDT',quantity:1,entry_price:100,stop_price:95,take_profit:110}],killed:false,last_cycle_at:new Date().toISOString(),ai_model:'gpt-5.6-luna',installed_version:'0.8.5',update_state:'signed_rollout'});

test('Spot cycle diagnostics sync safely and preserve legacy snapshot compatibility',async t=>{
  const f=await fixture(t);
  const s={...snapshot(),dashboard:{status:{mode:'PAPER'},positions:[],equity:[],trades:[],reviews:[],events:[],
    risk:{},research:{assets:[]},research_state:{running:false,error:null},updates:{}}};
  assert.equal((await f.sync({snapshot:s,acks:[]})).status,200);
  s.dashboard.status.spot_cycle=null;
  assert.equal((await f.sync({snapshot:s,acks:[]})).status,200);
  const c={state:'NO_OPPORTUNITIES',at:new Date().toISOString(),universe:30,evaluated:30,signals:0,
    candidates:0,reviews:0,opened:0,reasons:{BELOW_SCORE:30},minimum_score:75,btc_bullish:false,
    error_code:null,age_seconds:2,fresh:true};
  s.dashboard.status.spot_cycle=c;
  assert.equal((await f.sync({snapshot:s,acks:[]})).status,200);
  await f.login();
  assert.deepEqual((await f.request('/v1/status')).body.snapshot.dashboard.status.spot_cycle,c);
  for(const update of [{state:'UNKNOWN'},{evaluated:true},{signals:-1},{universe:10001},
    {reasons:{raw_secret:1}},{error_code:'raw_secret'},{secret:'raw_secret'},{fresh:'yes'}]){
    const invalid=structuredClone(s);
    Object.assign(invalid.dashboard.status.spot_cycle,update);
    assert.equal((await f.sync({snapshot:invalid,acks:[]})).status,400,JSON.stringify(update));
  }
  // Failed writes retain the last valid diagnostic.
  assert.deepEqual((await f.request('/v1/status')).body.snapshot.dashboard.status.spot_cycle,c);
});

test('Worker accepts the actual Python Spot projection for every emitted code and state',async t=>{
  const f=await fixture(t);
  const projected=JSON.parse(execFileSync('python',['-c',`
import json
from datetime import UTC, datetime
from trader.monitoring import spot_cycle_status, SPOT_CYCLE_STATES, SPOT_CYCLE_REASONS, SPOT_CYCLE_ERRORS
now=datetime.now(UTC)
base=dict(at=now.isoformat(),universe=30,evaluated=31,signals=2,candidates=2,reviews=1,opened=0,
          reasons={code:1 for code in SPOT_CYCLE_REASONS},minimum_score=75,btc_bullish=False,error_code=None)
reports=[spot_cycle_status(dict(base,state=state),900,now) for state in sorted(SPOT_CYCLE_STATES)]
reports += [spot_cycle_status(dict(base,state='ERROR',error_code=code),900,now) for code in sorted(SPOT_CYCLE_ERRORS)]
print(json.dumps(reports))
`],{cwd:new URL('../../',import.meta.url),encoding:'utf8'}));
  for(const diagnostic of projected){
    assert.ok(diagnostic);
    const s={...snapshot(),dashboard:{status:{mode:'PAPER',spot_cycle:diagnostic},positions:[],equity:[],
      trades:[],reviews:[],events:[],risk:{},research:{assets:[]},research_state:{running:false,error:null},updates:{}}};
    assert.equal((await f.sync({snapshot:s,acks:[]})).status,200,JSON.stringify(diagnostic));
  }
});

async function fixture(t){
  const env={DB:new LocalD1(),PORTAL_ORIGIN:origin,OWNER_KEY_HASH:await sha256(owner),DEVICE_KEY_HASH:await sha256(device),ASSETS:{fetch:async()=>new Response('<html>Portal shell</html>',{headers:{'Content-Type':'text/html'}})}};
  t.after(()=>env.DB.close());
  let cookie='',csrf='';
  const request=async(path,body,extra={})=>{
    const response=await worker.fetch(new Request(origin+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:origin,Cookie:cookie,'X-CSRF-Token':csrf,...extra},...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)})}),env);
    return {status:response.status,headers:response.headers,body:await response.json()};
  };
  const login=async()=>{const r=await request('/v1/login',{password:owner});assert.equal(r.status,200);cookie=r.headers.get('set-cookie').split(';')[0];csrf=r.body.csrf;return r;};
  const sync=async(body={snapshot:snapshot(),acks:[]})=>request('/v1/device/sync',body,{Authorization:`Bearer ${device}`});
  return {env,request,login,sync};
}


test('legacy cache-busting root URL redirects cleanly without opening query parameters',async t=>{
  const f=await fixture(t);
  const response=await worker.fetch(new Request(origin+'/?v=2',{redirect:'manual'}),f.env);
  assert.equal(response.status,302);
  assert.equal(response.headers.get('location'),origin+'/');
});

test('private portal assets are never served from stale browser cache',async t=>{
  const f=await fixture(t);
  const root=await worker.fetch(new Request(origin+'/'),f.env);
  assert.equal(root.status,200);
  assert.match(root.headers.get('cache-control')||'',/no-store/);
  assert.equal(root.headers.get('clear-site-data'),null);
  const app=await worker.fetch(new Request(origin+'/app.js'),f.env);
  assert.equal(app.status,200);
  assert.match(app.headers.get('cache-control')||'',/no-store/);
  assert.equal(app.headers.get('pragma'),'no-cache');
});

test('authenticated Futures pause diagnostics exposes only the stored safe projection',async t=>{
  const f=await fixture(t);
  const s={...snapshot(),mode:'TESTNET',installed_version:'0.9.2',dashboard:{
    status:{mode:'TESTNET'},
    positions:[],equity:[],trades:[],reviews:[],events:[],
    risk:{},research:{assets:[]},research_state:{running:false,error:null},updates:{},
    futures_forward:{
      enabled:true,killed:true,symbols:['BTCUSDT','ETHUSDT','SOLUSDT'],automatic_leverage:1,
      positions:[],position:null,trades:[],equity:[],closed_trades:0,gross_pnl:0,
      pause_diagnostics:{active:true,label:'3 errores consecutivos del ciclo Futures',detail:'three consecutive Futures forward errors',source:'automatic_safety',paused_at:'2026-09-27T17:00:00+00:00',last_error:{message:'temporary test error',at:'2026-09-27T16:59:00+00:00'},consecutive_errors:3,pending_reconciliation:false}
    }
  }};
  assert.equal((await f.sync({snapshot:s,acks:[]})).status,200);
  await f.login();
  const response=await f.request('/v1/futures-pause-diagnostics');
  assert.equal(response.status,200);
  assert.equal(response.body.installed_version,'0.9.2');
  assert.equal(response.body.killed,true);
  assert.equal(response.body.has_pause_diagnostics,true);
  assert.equal(response.body.pause_diagnostics.source,'automatic_safety');
  assert.equal(response.body.pause_diagnostics.consecutive_errors,3);
  assert.equal(typeof response.body.stale,'boolean');
});

test('device sync accepts legacy and multi-asset Futures forward dashboard shapes',async t=>{
  const f=await fixture(t);
  const base=snapshot();
  const legacy={...base,mode:'TESTNET',dashboard:{
    status:{mode:'TESTNET'},
    positions:[],equity:[],trades:[],reviews:[],events:[],
    risk:{},research:{assets:[]},research_state:{running:false,error:null},
    updates:{},paper_scorecard:{mode:'TESTNET',status:'INSUFFICIENT_EVIDENCE',by_asset:[]},
    futures_forward:{enabled:true,killed:false,symbol:'BTCUSDT',automatic_leverage:1,position:null,
      trades:[],equity:[],closed_trades:0,gross_pnl:0}
  }};
  assert.equal((await f.sync({snapshot:legacy,acks:[]})).status,200);

  const modern=structuredClone(legacy);
  modern.dashboard.status.spot_cycle={
    state:'RISK_HALT',at:'2026-10-04T17:00:00Z',universe:30,evaluated:0,signals:0,candidates:0,reviews:0,opened:0,
    reasons:{LOSS_LIMIT:1},minimum_score:70,btc_bullish:true,error_code:null,age_seconds:0,fresh:true,
    risk_halt:{periods:['daily'],daily_return_pct:-2.71,weekly_return_pct:-2.71,daily_limit_pct:2,weekly_limit_pct:5,resets_at:'2026-10-05T00:00:00Z'}
  };
  modern.dashboard.futures_forward={
    enabled:true,killed:false,symbols:['BTCUSDT','ETHUSDT','SOLUSDT'],automatic_leverage:1,
    positions:[],position:null,trades:[],equity:[],closed_trades:0,gross_pnl:0,
    latest_signals:{},last_ai_reviews:{},shadow_scorecard:[],
    cycle_diagnostic:{state:'WAITING_CANDLE',at:'2026-10-04T17:00:00Z',timeframe:'1h',minimum_score:70,
      symbols:3,evaluated:0,signals:0,reviews:0,opened:0,statuses:{NO_NEW_CANDLE:3}},
    guardrails:{margin_type:'ISOLATED',position_mode:'ONE_WAY',max_positions:3,forward_timeframe:'1h',forward_min_score:70},
    recovery:{durable_order_journal:true},live_readiness:{enabled:false},
    pause_diagnostics:{active:true,label:'3 errores consecutivos de protección Futures',
      detail:'three consecutive Futures protection errors',source:'automatic_safety',
      paused_at:'2026-09-27T16:40:24+00:00',
      last_error:{message:'Untracked Futures Demo position: SOLUSDT',at:'2026-09-27T16:40:20+00:00'},
      consecutive_errors:3,
      incident:{id:'FUT-0007',source:'protection',message:'Automatic Futures margin is not isolated',
        repetitions:1113,first_at:'2026-09-27T16:40:20+00:00',last_at:'2026-09-28T14:20:00+00:00',resolved_at:null},
      pending_reconciliation:true}
  };
  assert.equal((await f.sync({snapshot:modern,acks:[]})).status,200);
  const trials=structuredClone(modern);
  trials.dashboard.futures_forward.symbols=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'];
  trials.dashboard.futures_forward.leverage_trials={levels:[1,2,3],next_leverage:2,
    fixed_notional:true,notional_limit_usdt:100,started_at:'2026-10-04T03:00:00Z',
    results:[1,2,3].map(leverage=>({leverage,closed_trades:0,gross_pnl_usdt:0}))};
  assert.equal((await f.sync({snapshot:trials,acks:[]})).status,200);
  const portfolio=structuredClone(trials);
  portfolio.dashboard.futures_forward.symbols=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT','DOTUSDT','LTCUSDT','BCHUSDT','TRXUSDT','ATOMUSDT','NEARUSDT'];
  const pf=portfolio.dashboard.futures_forward;
  pf.latest_signals=Object.fromEntries(pf.symbols.map(symbol=>[symbol,{
    symbol,timeframe:'4h',candle_close_time:999,direction:'LONG',score:80,long_score:80,short_score:10,
    price:100,atr:2,rsi:60,ema_fast:101,ema_slow:99,volume_ratio:1.3,at:'2026-10-04T03:00:00Z'}]));
  pf.positions=pf.symbols.slice(0,5).map(symbol=>({symbol,leverage:1}));
  pf.portfolio_budget={notional_limit_usdt:300,stop_loss_limit_usdt:7.5,cost_buffer_pct:.005,
    notional_usdt:250,stop_loss_usdt:7,at:'2026-10-04T03:00:00Z'};
  assert.equal((await f.sync({snapshot:portfolio,acks:[]})).status,200);
  // Existing exposure above a cap still synchronizes; only new entries are blocked.
  pf.portfolio_budget.notional_usdt=350;
  pf.portfolio_budget.stop_loss_usdt=10;
  assert.equal((await f.sync({snapshot:portfolio,acks:[]})).status,200);
  for(const change of [x=>x.symbols.push('EXTRAUSDT'),x=>x.positions.push({symbol:'ADAUSDT'}),
    x=>x.portfolio_budget.notional_limit_usdt=301,x=>x.portfolio_budget.stop_loss_limit_usdt=8,
    x=>x.portfolio_budget.cost_buffer_pct=0,x=>x.portfolio_budget.secret='unexpected']){
    const bad=structuredClone(portfolio);change(bad.dashboard.futures_forward);
    assert.equal((await f.sync({snapshot:bad,acks:[]})).status,400);
  }
  for(const change of [t=>t.levels=[1,2,4],t=>t.next_leverage=4,t=>t.fixed_notional=false,
    t=>t.notional_limit_usdt=300,t=>t.results[0].closed_trades=-1,t=>t.secret='unexpected']){
    const badTrial=structuredClone(trials);
    change(badTrial.dashboard.futures_forward.leverage_trials);
    assert.equal((await f.sync({snapshot:badTrial,acks:[]})).status,400);
  }
  const signals=structuredClone(modern);
  signals.dashboard.futures_forward.latest_signals={ETHUSDT:{
    symbol:'ETHUSDT',timeframe:'4h',candle_close_time:999,direction:'LONG',score:80,
    long_score:80,short_score:10,price:100,atr:2,rsi:60,ema_fast:101,ema_slow:99,
    volume_ratio:1.3,at:'2026-10-03T15:00:00+00:00'},BTCUSDT:null};
  assert.equal((await f.sync({snapshot:signals,acks:[]})).status,200);
  for(const change of [s=>s.score=101,s=>s.symbol='SOLUSDT',s=>s.secret='unexpected']){
    const invalidSignal=structuredClone(signals);
    change(invalidSignal.dashboard.futures_forward.latest_signals.ETHUSDT);
    assert.equal((await f.sync({snapshot:invalidSignal,acks:[]})).status,400);
  }
  const invalid=structuredClone(modern);
  invalid.dashboard.futures_forward.pause_diagnostics.source='arbitrary';
  assert.equal((await f.sync({snapshot:invalid,acks:[]})).status,400);
  const badIncident=structuredClone(modern);
  badIncident.dashboard.futures_forward.pause_diagnostics.incident.repetitions=-1;
  assert.equal((await f.sync({snapshot:badIncident,acks:[]})).status,400);
});

test('signed rollout automatically queues a newer bot release and does not downgrade',async t=>{
  const f=await fixture(t);
  const releaseId='a'.repeat(64);
  const envelope={manifest:{version:'0.8.6'},signature:'test'};
  f.env.DB.sqlite.prepare('INSERT INTO bot_releases(sequence,release_id,commit_sha,envelope,created) VALUES(?,?,?,?,?)')
    .run(10,releaseId,'b'.repeat(40),JSON.stringify(envelope),1);
  const update=await f.sync({snapshot:{...snapshot(),installed_version:'0.8.5'},acks:[]});
  assert.equal(update.status,200);
  assert.equal(update.body.jobs.length,1);
  assert.equal(update.body.jobs[0].action,'update_install');
  assert.equal(update.body.jobs[0].release_id,releaseId);

  f.env.DB.sqlite.prepare("UPDATE jobs SET status='completed'").run();
  const current=await f.sync({snapshot:{...snapshot(),installed_version:'0.8.6'},acks:[]});
  assert.equal(current.body.jobs.length,0);
  const newerLocal=await f.sync({snapshot:{...snapshot(),installed_version:'0.9.0'},acks:[]});
  assert.equal(newerLocal.body.jobs.length,0);
});

test('signed rollout skips intermediate versions and installs the latest release',async t=>{
  const f=await fixture(t);
  const oldId='1'.repeat(64), latestId='2'.repeat(64);
  f.env.DB.sqlite.prepare('INSERT INTO bot_releases(sequence,release_id,commit_sha,envelope,created) VALUES(?,?,?,?,?)')
    .run(20,oldId,'3'.repeat(40),JSON.stringify({manifest:{version:'0.8.7'},signature:'test'}),1);
  f.env.DB.sqlite.prepare('INSERT INTO bot_releases(sequence,release_id,commit_sha,envelope,created) VALUES(?,?,?,?,?)')
    .run(21,latestId,'4'.repeat(40),JSON.stringify({manifest:{version:'0.8.8'},signature:'test'}),2);
  const update=await f.sync({snapshot:{...snapshot(),installed_version:'0.8.6'},acks:[]});
  assert.equal(update.status,200);
  assert.equal(update.body.jobs.length,1);
  assert.equal(update.body.jobs[0].action,'update_install');
  assert.equal(update.body.jobs[0].release_id,latestId);
});

test('failed automatic rollout is not retried in a loop',async t=>{
  const f=await fixture(t);
  const releaseId='c'.repeat(64);
  const envelope={manifest:{version:'0.8.6'},signature:'test'};
  f.env.DB.sqlite.prepare('INSERT INTO bot_releases(sequence,release_id,commit_sha,envelope,created) VALUES(?,?,?,?,?)')
    .run(11,releaseId,'d'.repeat(40),JSON.stringify(envelope),1);
  const first=await f.sync({snapshot:{...snapshot(),installed_version:'0.8.5'},acks:[]});
  const id=first.body.jobs[0].id;
  await f.sync({snapshot:{...snapshot(),installed_version:'0.8.5'},acks:[],
    job_results:[{id,action:'update_install',status:'failed',message:'supervisor rejected candidate'}]});
  const again=await f.sync({snapshot:{...snapshot(),installed_version:'0.8.5'},acks:[]});
  assert.equal(again.body.jobs.length,0);
  const row=f.env.DB.sqlite.prepare('SELECT status FROM jobs WHERE id=?').get(id);
  assert.equal(row.status,'failed');
});

test('owner login, secure cookie, status and logout revoke the session',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/v1/status')).status,401);
  const logged=await f.login();
  assert.match(logged.headers.get('set-cookie'),/Secure; HttpOnly; SameSite=Strict/);
  const initial=await f.request('/v1/status');assert.equal(initial.body.stale,true);assert.equal(initial.body.snapshot,null);
  assert.equal((await f.request('/v1/logout',{})).status,200);
  assert.equal((await f.request('/v1/status')).status,401);
});

test('PAPER controls require a current capable Windows snapshot, retain exact position and report result',async t=>{
  const f=await fixture(t);await f.login();
  const request={action:'paper_close',request_id:'paper-close-request-0001',payload:{symbol:'BTCUSDT',opened_at:'2026-01-01T00:00:00Z',reference_price:101}};
  assert.equal((await f.request('/v1/paper-controls',request)).status,409);
  await f.sync({snapshot:{...snapshot(),paper_controls:true,dashboard:{status:{mode:'PAPER'},positions:[{symbol:'BTCUSDT',opened_at:request.payload.opened_at}],equity:[],trades:[],reviews:[],events:[],research:{assets:[]}}},acks:[],control_results:[]});
  assert.equal((await f.request('/v1/paper-controls',{...request,payload:{...request.payload,opened_at:'wrong'}})).status,409);
  const created=await f.request('/v1/paper-controls',request);assert.equal(created.status,202);
  assert.equal((await f.request('/v1/paper-controls',{...request,payload:{...request.payload,reference_price:102}})).status,409);
  const delivered=await f.sync({snapshot:{...snapshot(),paper_controls:true},acks:[]});
  assert.deepEqual(delivered.body.paper_controls[0].payload,request.payload);
  await f.sync({snapshot:{...snapshot(),paper_controls:true},acks:[],control_results:[{id:created.body.id,status:'completed',message:'Posición PAPER cerrada: BTCUSDT'}]});
  const status=await f.request('/v1/status');
  assert.equal(status.body.paper_controls[0].status,'completed');
  assert.equal(status.body.activity[0].action,'paper_close');
  assert.equal((await f.request('/v1/paper-controls',{action:'risk_profile',request_id:'risk-profile-request-0001',payload:{profile:'infinito'}})).status,400);
  assert.equal((await f.request('/v1/paper-controls',{action:'risk_profile',request_id:'risk-profile-request-0002',payload:{profile:'moderado'}})).status,202);
  assert.equal((await f.request('/v1/paper-controls',request,{'X-CSRF-Token':'bad'})).status,403);
});

test('legacy manual Testnet controls are retired while unified operational controls remain',async t=>{
  const f=await fixture(t);await f.login();
  await f.sync({snapshot:{...snapshot(),paper_controls:true,operations_controls:true},acks:[]});
  const command=(action,payload,id)=>({action,payload,request_id:id});
  assert.equal((await f.request('/v1/paper-controls',command('testnet_buy',{},'testnet-trade-0000001'))).status,400);
  assert.equal((await f.request('/v1/paper-controls',command('testnet_close',{},'testnet-close-0000001'))).status,400);
  assert.equal((await f.request('/v1/paper-controls',command('testnet_reconcile',{},'testnet-rec-00000001'))).status,400);
  assert.equal((await f.request('/v1/paper-controls',command('testnet_audit',{},'testnet-audit-0000001'))).status,400);
  assert.equal((await f.request('/v1/paper-controls',command('ai_model',{model:'unknown'},'model-select-0000001'))).status,400);
  assert.equal((await f.request('/v1/paper-controls',command('testnet_smoke',{},'smoke-paper-00000001'))).status,409);
  assert.equal((await f.request('/v1/paper-controls',command('execution_mode',{mode:'testnet'},'mode-change-00000001'))).status,202);
});

test('supervised Testnet smoke control is TESTNET-only and idempotent',async t=>{
  const f=await fixture(t);await f.login();
  await f.sync({snapshot:{...snapshot(),mode:'TESTNET',paper_controls:true,operations_controls:true},acks:[]});
  const request={action:'testnet_smoke',payload:{},request_id:'testnet-smoke-000001'};
  const created=await f.request('/v1/paper-controls',request);
  assert.equal(created.status,202);
  const duplicate=await f.request('/v1/paper-controls',request);
  assert.equal(duplicate.status,202);
  assert.equal(duplicate.body.id,created.body.id);
  const delivered=await f.sync({snapshot:{...snapshot(),mode:'TESTNET',paper_controls:true,operations_controls:true},acks:[]});
  assert.equal(delivered.body.paper_controls[0].action,'testnet_smoke');
  assert.deepEqual(delivered.body.paper_controls[0].payload,{});
});


test('Futures forward pause and resume controls are accepted remotely in TESTNET',async t=>{
  const f=await fixture(t);
  const base=snapshot();
  const testnet={...base,mode:'TESTNET',operations_controls:true,paper_controls:true,dashboard:{
    status:{mode:'TESTNET'},positions:[],equity:[],trades:[],reviews:[],events:[],
    risk:{},research:{assets:[]},research_state:{running:false,error:null},
    updates:{},paper_scorecard:{mode:'TESTNET',status:'INSUFFICIENT_EVIDENCE',by_asset:[]},
    futures_forward:{enabled:true,killed:true,symbols:['BTCUSDT','ETHUSDT','SOLUSDT'],automatic_leverage:1,positions:[],position:null,trades:[],equity:[],closed_trades:0,gross_pnl:0}
  }};
  assert.equal((await f.sync({snapshot:testnet,acks:[]})).status,200);
  await f.login();
  for(const action of ['futures_forward_pause','futures_forward_resume']){
    const response=await f.request('/v1/paper-controls',{action,payload:{},request_id:action+'-request-0001'});
    assert.equal(response.status,202);
    assert.equal(response.body.action,action);
    assert.equal(response.body.status,'pending');
    f.env.DB.sqlite.prepare("UPDATE jobs SET status='completed'").run();
  }
});

test('Futures Testnet controls require TESTNET and remain idempotent',async t=>{
  const f=await fixture(t);await f.login();
  const command=(action,payload,id)=>({action,payload,request_id:id});
  await f.sync({snapshot:{...snapshot(),paper_controls:true,operations_controls:true},acks:[]});
  assert.equal((await f.request('/v1/paper-controls',command('futures_testnet_check',{},'futures-check-paper-01'))).status,409);
  await f.sync({snapshot:{...snapshot(),mode:'TESTNET',paper_controls:true,operations_controls:true},acks:[]});
  assert.equal((await f.request('/v1/paper-controls',command('futures_testnet_smoke',{direction:'LONG',leverage:4},'futures-bad-lev-0001'))).status,400);
  const request=command('futures_testnet_smoke',{direction:'SHORT',leverage:2},'futures-smoke-000001');
  const created=await f.request('/v1/paper-controls',request);
  assert.equal(created.status,202);
  const duplicate=await f.request('/v1/paper-controls',request);
  assert.equal(duplicate.status,202);
  assert.equal(duplicate.body.id,created.body.id);
  const delivered=await f.sync({snapshot:{...snapshot(),mode:'TESTNET',paper_controls:true,operations_controls:true},acks:[]});
  assert.equal(delivered.body.paper_controls[0].action,'futures_testnet_smoke');
  assert.deepEqual(delivered.body.paper_controls[0].payload,{direction:'SHORT',leverage:2});
});

test('activity combines jobs and commands, paginates privately, and rejects unbounded routes',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/v1/activity/0')).status,401);
  await f.login();await f.sync();
  for(let i=0;i<29;i++){
    const result=await f.request('/v1/commands',{action:'kill',request_id:`activity_${i.toString().padStart(14,'0')}`});
    assert.equal(result.status,202);
  }
  const first=await f.request('/v1/activity/0');
  assert.equal(first.body.items.length,25);
  assert.equal(first.body.next_page,1);
  assert.equal(first.body.retention_days,90);
  const second=await f.request('/v1/activity/1');
  assert.equal(second.body.items.length,4);
  assert.equal(second.body.next_page,null);
  const status=await f.request('/v1/status');
  assert.equal(status.body.activity.length,3);
  assert.equal((await f.request('/v1/activity/100')).status,404);
  assert.equal((await f.request('/v1/activity/0?token=bad')).status,400);
});

test('password change requires current password and CSRF, revokes all sessions, preserves device access',async t=>{
  const f=await fixture(t);const first=await f.login();await f.login();
  const next='A long unique test passphrase 2026';
  const salt='T'.repeat(43),body={current_password:owner,new_password:proof(next,salt),salt};
  assert.equal((await f.request('/v1/password',body,{'X-CSRF-Token':'wrong'})).status,403);
  assert.equal((await f.request('/v1/password',{...body,current_password:'wrong'})).status,400);
  assert.equal((await f.request('/v1/password',{...body,new_password:'short'})).status,400);
  assert.equal((await f.request('/v1/password',{...body,new_password:owner})).status,400);
  assert.equal((await f.request('/v1/password',{...body,new_password:device})).status,400);
  assert.equal((await f.request('/v1/password',body)).status,200);
  assert.equal((await f.request('/v1/status')).status,401);
  assert.equal((await f.request('/v1/status',undefined,{Cookie:first.headers.get('set-cookie').split(';')[0]})).status,401);
  assert.equal((await f.request('/v1/login',{password:owner})).status,401);
  assert.equal((await f.request('/v1/login',{password:body.new_password})).status,200);
  assert.equal((await f.request('/v1/login',{password:next})).status,401);
  assert.deepEqual((await f.request('/v1/auth-parameters')).body,{scheme:'pbkdf2-sha256',salt,iterations:600000});
  const saved=f.env.DB.sqlite.prepare('SELECT * FROM owner_password').get();
  assert.equal(saved.iterations,600000);assert.equal(saved.digest.includes(next),false);
  assert.equal((await f.sync()).status,200);
});

test('simultaneous password changes have exactly one winner and recovery rotates bootstrap',async t=>{
  const f=await fixture(t);await f.login();
  const passwords=['First independent passphrase','Second independent passphrase'].map((p,i)=>proof(p,String(i).repeat(43)));
  const responses=await Promise.all(passwords.map((new_password,i)=>f.request('/v1/password',{current_password:owner,new_password,salt:String(i).repeat(43)})));
  assert.deepEqual(responses.map(r=>r.status).sort(),[200,409]);
  const winner=passwords[responses.findIndex(r=>r.status===200)];
  assert.equal((await f.request('/v1/login',{password:winner})).status,200);
  f.env.OWNER_KEY_HASH=await sha256('Z'.repeat(43));
  assert.equal((await f.request('/v1/status')).status,401);
  assert.equal((await f.request('/v1/login',{password:winner})).status,401);
  assert.equal((await f.request('/v1/login',{password:'Z'.repeat(43)})).status,200);
});

test('failed credential transaction preserves old password and session',async t=>{
  const f=await fixture(t);await f.login();
  f.env.DB.sqlite.exec("CREATE TRIGGER reject_password BEFORE INSERT ON owner_password BEGIN SELECT RAISE(ABORT,'test failure'); END");
  assert.equal((await f.request('/v1/password',{current_password:owner,new_password:proof('Never installed passphrase','F'.repeat(43)),salt:'F'.repeat(43)})).status,503);
  assert.equal((await f.request('/v1/status')).status,200);
  assert.equal((await f.request('/v1/login',{password:owner})).status,200);
});

test('owner and device credentials are separated; no unauthenticated DB writes',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/v1/device/sync',{snapshot:snapshot()},{Authorization:`Bearer ${owner}`})).status,401);
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) n FROM snapshots').get().n,0);
  assert.equal((await f.request('/v1/login',{password:device})).status,401);
});

test('global login limit is atomic and bounded, including concurrent requests',async t=>{
  const f=await fixture(t);
  const attempts=await Promise.all(Array.from({length:12},()=>f.request('/v1/login',{password:'wrong'})));
  assert.equal(attempts.filter(r=>r.status===401).length,10);
  assert.equal(attempts.filter(r=>r.status===429).length,2);
  f.env.DB.sqlite.exec('UPDATE login_budget SET window_start=0');
  assert.equal((await f.login()).status,200);
});

test('CSRF, cross origin, credential URLs and unsupported commands are rejected',async t=>{
  const f=await fixture(t);await f.login();
  const command={action:'kill',request_id:'c'.repeat(20)};
  assert.equal((await f.request('/v1/commands',command,{'X-CSRF-Token':'bad'})).status,403);
  assert.equal((await f.request('/v1/commands',command,{Origin:'https://evil.example'})).status,403);
  assert.equal((await f.request('/v1/status?token=not-a-secret')).status,400);
  assert.equal((await f.request('/v1/commands',{...command,action:'shell'})).status,400);
});

test('resume is refused without a fresh Windows heartbeat, kill may queue',async t=>{
  const f=await fixture(t);await f.login();
  assert.equal((await f.request('/v1/commands',{action:'resume',request_id:'r'.repeat(20)})).status,409);
  assert.equal((await f.request('/v1/commands',{action:'kill',request_id:'k'.repeat(20)})).status,202);
  await f.sync();
  assert.equal((await f.request('/v1/commands',{action:'resume',request_id:'s'.repeat(20)})).status,202);
});

test('command idempotency is atomic; replay cannot supersede a newer command',async t=>{
  const f=await fixture(t);await f.login();await f.sync();
  const cmd={action:'resume',request_id:'x'.repeat(20)};
  const repeats=await Promise.all(Array.from({length:5},()=>f.request('/v1/commands',cmd)));
  assert.equal(new Set(repeats.map(r=>r.body.id)).size,1);
  const kill=await f.request('/v1/commands',{action:'kill',request_id:'y'.repeat(20)});
  await f.request('/v1/commands',cmd);
  const pending=(await f.sync()).body.commands;
  assert.equal(pending.length,1);assert.equal(pending[0].id,kill.body.id);assert.equal(pending[0].action,'kill');
  assert.equal((await f.request('/v1/commands',{...cmd,action:'kill'})).status,409);
});

test('device acknowledgements record only delivered commands and tolerate late ack',async t=>{
  const f=await fixture(t);await f.login();
  const created=await f.request('/v1/commands',{action:'kill',request_id:'z'.repeat(20)});
  const first=await f.sync({snapshot:snapshot(),acks:[created.body.id]});
  assert.equal(first.body.commands.length,1,'an undelivered command is not acknowledged');
  f.env.DB.sqlite.prepare('UPDATE commands SET expires=0 WHERE id=?').run(created.body.id);
  await f.sync({snapshot:snapshot(),acks:[created.body.id]});
  assert.equal((await f.request('/v1/status')).body.commands[0].status,'applied');
});

test('expired commands are not delivered',async t=>{
  const f=await fixture(t);await f.login();
  await f.request('/v1/commands',{action:'kill',request_id:'e'.repeat(20)});
  f.env.DB.sqlite.exec('UPDATE commands SET expires=0');
  assert.deepEqual((await f.sync()).body.commands,[]);
  assert.equal((await f.request('/v1/status')).body.commands[0].status,'expired');
});

test('schema rejects LIVE mode, unknown fields, malformed positions and balances',async t=>{
  const f=await fixture(t);
  for(const invalid of [{...snapshot(),mode:'LIVE'},{...snapshot(),api_key:'not-a-secret'},{...snapshot(),cash:-1},{...snapshot(),positions:[{symbol:'BTCUSDT'}]},{...snapshot(),ai_model:'sk-not-a-secret'}]){
    assert.equal((await f.sync({snapshot:invalid})).status,400);
  }
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) n FROM snapshots').get().n,0);
});

test('body bytes, JSON errors and content types are bounded',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/v1/login','{"password":"'+'x'.repeat(66000)+'"}')).status,413);
  assert.equal((await f.request('/v1/login','[')).status,400);
  assert.equal((await f.request('/v1/login',[],{'Content-Type':'text/plain'})).status,415);
});

test('rotating owner secret invalidates existing sessions',async t=>{
  const f=await fixture(t);await f.login();
  f.env.OWNER_KEY_HASH=await sha256('C'.repeat(43));
  assert.equal((await f.request('/v1/status')).status,401);
});

test('database batch failure rolls back snapshot and acknowledges nothing',async t=>{
  const f=await fixture(t);await f.sync();
  f.env.DB.sqlite.exec("CREATE TRIGGER fail_command BEFORE UPDATE ON commands BEGIN SELECT RAISE(ABORT,'injected'); END;");
  await f.login();await f.request('/v1/commands',{action:'kill',request_id:'f'.repeat(20)});
  const failed=await f.sync({snapshot:{...snapshot(),equity:1200},acks:[]});
  assert.equal(failed.status,503);
  assert.equal(JSON.parse(f.env.DB.sqlite.prepare('SELECT payload FROM snapshots').get().payload).equity,1000);
  assert.equal(failed.body.error,'Service temporarily unavailable');
});

test('daily cleanup retains financial snapshot and removes expired session/history',async t=>{
  const f=await fixture(t);await f.login();await f.sync();
  f.env.DB.sqlite.exec("UPDATE sessions SET expires=0; INSERT INTO commands(request_id,action,expires,status,created) VALUES('old','kill',0,'expired',0)");
  await worker.scheduled({},f.env);
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) n FROM commands').get().n,0);
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) n FROM sessions').get().n,0);
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) n FROM snapshots').get().n,1);
});

test('static shell has strict security headers and missing provisioning fails closed',async t=>{
  const f=await fixture(t);
  f.env.ASSETS={fetch:async()=>new Response('<html></html>',{headers:{'cache-control':'public, max-age=0, must-revalidate','content-security-policy':"default-src *"}})};
  const response=await worker.fetch(new Request(origin+'/'),f.env);
  assert.equal(response.status,200);assert.match(response.headers.get('cache-control')||'',/^no-store(?:,|$)/);
  assert.match(response.headers.get('content-security-policy'),/frame-ancestors 'none'/);
  f.env.PORTAL_ORIGIN='https://portal.invalid';
  assert.equal((await worker.fetch(new Request(origin+'/'),f.env)).status,503);
});

test('health checks the migrated database and reports only an immutable deployment revision',async t=>{
  const f=await fixture(t);f.env.PORTAL_COMMIT='d'.repeat(40);
  const healthy=await f.request('/v1/health');
  assert.equal(healthy.status,200);assert.deepEqual(healthy.body,{status:'ok',commit:'d'.repeat(40)});
  f.env.PORTAL_COMMIT='untrusted';
  assert.equal((await f.request('/v1/health')).body.commit,null);
});

test('expanded dashboard remains authenticated and bounded',async t=>{
  const f=await fixture(t);
  const dashboard={status:{mode:'PAPER'},positions:[],equity:[],trades:[],reviews:[],events:[],research:{assets:[]}};
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard},acks:[]})).status,200);
  const testnet={mode:'READ_ONLY_DRY_RUN',order_submission_enabled:false,planner:'public_filters_and_synthetic_reconciliation',next_step:'manual review'};
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,testnet}},acks:[]})).status,200);
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,testnet:{...testnet,order_submission_enabled:true}}},acks:[]})).status,400);
  assert.equal((await f.request('/v1/status')).status,401);
  await f.login();
  assert.deepEqual((await f.request('/v1/status')).body.snapshot.dashboard,{...dashboard,testnet});
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,status:{mode:'LIVE'}}},acks:[]})).status,400);
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,equity:Array(301).fill({})}},acks:[]})).status,400);
  const asset={symbol:'BTCUSDT',closed_trades:1,net_realized_pnl_usdt:1,win_rate_pct:100,
    open_exposure_usdt:null,estimated_open_pnl_usdt:null};
  const scorecard={mode:'PAPER',status:'INSUFFICIENT_EVIDENCE',by_asset:Array.from({length:24},(_,i)=>
    ({...asset,symbol:`SYM${i}USDT`})),attribution:{research_symbols:['BTCUSDT'],exit_reasons:[]}};
  assert.ok(JSON.stringify(scorecard).length>3500);
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,paper_scorecard:scorecard}},acks:[]})).status,200);
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,paper_scorecard:{...scorecard,by_asset:Array(51).fill(asset)}}},acks:[]})).status,400);
  assert.equal((await f.sync({snapshot:{...snapshot(),dashboard:{...dashboard,paper_scorecard:{...scorecard,extra:'x'.repeat(13000)}}},acks:[]})).status,400);
});

test('update discovery requires an owner session and exposes no approval endpoint',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/v1/updates')).status,401);
  assert.equal((await f.request('/v1/updates/approve',{})).status,401);
  await f.login();
  assert.equal((await f.request('/v1/updates/approve',{})).status,404);
});

test('background jobs persist, deduplicate, reject unsupported actions and accept only delivered results',async t=>{
  const f=await fixture(t);await f.login();
  const body={action:'research',request_id:'research-request-0001'};
  assert.equal((await f.request('/v1/jobs',body)).status,409);
  await f.sync();
  assert.equal((await f.request('/v1/jobs',{...body,action:'shell'})).status,400);
  const job=(await f.request('/v1/jobs',body)).body;
  assert.equal((await f.request('/v1/jobs',body)).body.id,job.id);
  assert.equal((await f.request('/v1/jobs',{...body,action:'update_install',release_id:'a'.repeat(64)})).status,409);
  const first=await f.sync({snapshot:snapshot(),job_results:[{id:job.id,action:'research',status:'completed',message:'not delivered'}]});
  assert.equal(first.body.jobs[0].id,job.id);
  await f.sync({snapshot:snapshot(),job_results:[{id:job.id,action:'research',status:'running',message:'Running'}]});
  assert.deepEqual((await f.sync()).body.jobs,[]);
  await f.sync({snapshot:snapshot(),job_results:[{id:job.id,action:'research',status:'failed',message:'Failed safely'}]});
  assert.equal((await f.request('/v1/status')).body.jobs[0].status,'failed');
  await f.sync({snapshot:snapshot(),job_results:[{id:job.id,action:'research',status:'completed',message:'must not reverse failure'}]});
  assert.equal((await f.request('/v1/status')).body.jobs[0].status,'failed');
  const invalid=await f.sync({snapshot:{...snapshot(),equity:1500},job_results:[{id:job.id,action:'research',status:'invalid',message:''}]});
  assert.equal(invalid.status,400);
  assert.equal((await f.request('/v1/status')).body.snapshot.equity,1000);
});

test('bot installation binds approval to an enabled unexpired Windows-verified release',async t=>{
  const f=await fixture(t);await f.login();
  const candidate={release_id:'a'.repeat(64),version:'0.6.3',sequence:123,commit:'b'.repeat(40),expires:Math.floor(Date.now()/1000)+3600,enabled:true};
  const body={action:'update_install',request_id:'exact-bot-update-0001',release_id:candidate.release_id};
  await f.sync();
  assert.equal((await f.request('/v1/jobs',body)).status,409);
  await f.sync({snapshot:{...snapshot(),bot_update:{...candidate,enabled:false}}});
  assert.equal((await f.request('/v1/jobs',body)).status,409);
  await f.sync({snapshot:{...snapshot(),bot_update:candidate}});
  assert.equal((await f.request('/v1/jobs',{...body,release_id:'c'.repeat(64)})).status,409);
  const accepted=await f.request('/v1/jobs',body);assert.equal(accepted.status,202);
  assert.equal((await f.request('/v1/jobs',body)).body.id,accepted.body.id);
  assert.equal((await f.request('/v1/jobs',{...body,release_id:'c'.repeat(64)})).status,409);
  const delivery=await f.sync({snapshot:{...snapshot(),bot_update:candidate}});
  assert.equal(delivery.body.jobs[0].release_id,candidate.release_id);
});

test('voluntary restore accepts only the fresh exact Windows verified previous code',async t=>{
  const f=await fixture(t);await f.login();
  const offer={restore_id:'a'.repeat(64),current_release_id:'b'.repeat(64),version:'0.6.2',current_version:'0.6.3',enabled:true};
  const body={action:'update_restore',request_id:'exact-restore-request-01',release_id:offer.restore_id};
  await f.sync();
  assert.equal((await f.request('/v1/jobs',body)).status,409);
  await f.sync({snapshot:{...snapshot(),bot_restore:offer}});
  assert.equal((await f.request('/v1/jobs',{...body,release_id:'c'.repeat(64)})).status,409);
  const accepted=await f.request('/v1/jobs',body);
  assert.equal(accepted.status,202);
  assert.equal(accepted.body.action,'update_restore');
  const stored=f.env.DB.sqlite.prepare('SELECT action,release_id FROM jobs WHERE id=?').get(accepted.body.id);
  assert.equal(stored.action,'update_install');
  assert.equal(stored.release_id,'restore:'+offer.restore_id);
  const delivered=await f.sync({snapshot:{...snapshot(),bot_restore:offer}});
  assert.equal(delivered.body.jobs[0].release_id,offer.restore_id);
  assert.equal(delivered.body.jobs[0].action,'update_restore');
  await f.sync({snapshot:{...snapshot(),bot_restore:offer},job_results:[{id:accepted.body.id,action:'update_install',status:'completed',message:'Wrong job'}]});
  assert.equal((await f.request('/v1/status')).body.jobs[0].status,'pending');
  await f.sync({snapshot:{...snapshot(),bot_restore:offer},job_results:[{id:accepted.body.id,action:'update_restore',status:'completed',message:'Previous code healthy'}]});
  assert.deepEqual((await f.request('/v1/status')).body.jobs[0],{id:accepted.body.id,action:'update_restore',status:'completed',message:'Previous code healthy'});
});

test('stale running job fails closed and no longer blocks a fresh request',async t=>{
  const f=await fixture(t);await f.login();await f.sync();
  const first=(await f.request('/v1/jobs',{action:'research',request_id:'stale-research-job-01'})).body;
  await f.sync();
  await f.sync({snapshot:snapshot(),job_results:[{id:first.id,action:'research',status:'running',message:'Running'}]});
  f.env.DB.sqlite.prepare('UPDATE jobs SET created=0 WHERE id=?').run(first.id);
  const next=await f.request('/v1/jobs',{action:'update_check',request_id:'fresh-update-check-01'});
  assert.equal(next.status,202);
  const statuses=(await f.request('/v1/status')).body.jobs;
  assert.equal(statuses.find(item=>item.id===first.id).status,'failed');
});


test('expanded research sync accepts bounded portfolios and rejects operating promotion or oversized evidence', async t=>{
  const f=await fixture(t);
  const scenario={method:'joint_execution_shared_cash',market:'FUTURES',profile:'base',leverage:10,
    automatic_promotion:false,curve:[{time:1000,equity:1000}],limits:{positions:5},
    net_return_pct:-2,max_drawdown_pct:3,closed_trades:20,fees:2,funding_cost:1,liquidations:0};
  const research={mode:'RESEARCH_ONLY',auto_promotion:false,assets:Array.from({length:30},(_,i)=>({symbol:`A${i}USDT`})),
    futures_assets:Array.from({length:15},(_,i)=>({symbol:`F${i}USDT`})),
    joint_portfolios:Array.from({length:18},()=>structuredClone(scenario)),history:Array.from({length:12},()=>({assets:30}))};
  const s={...snapshot(),dashboard:{status:{mode:'PAPER'},positions:[],equity:[],trades:[],reviews:[],events:[],
    research,research_state:{running:false,automatic:true,next_run_at:'2026-10-05T00:00:00Z'}}};
  assert.equal((await f.sync({snapshot:s,acks:[]})).status,200);
  for(const mutate of [r=>r.joint_portfolios[0].automatic_promotion=true,
    r=>r.joint_portfolios[0].curve=Array.from({length:121},()=>({equity:1000})),
    r=>r.futures_assets.push({symbol:'EXTRAUSDT'}),r=>r.history.push({}),r=>r.extra='x'.repeat(240000)]){
    const invalid=structuredClone(s);mutate(invalid.dashboard.research);
    assert.equal((await f.sync({snapshot:invalid,acks:[]})).status,400);
  }
});
