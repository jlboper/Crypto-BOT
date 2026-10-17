import { timingSafeEqual } from 'node:crypto';
import { githubUpdates, UpdateError } from './github-updates.mjs';
import { passwordDigest, validPassword, PASSWORD_ITERATIONS } from './password.mjs';
import { signRelease, releaseFailureCode } from './bot-releases.mjs';

const encoder = new TextEncoder();
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const HASH = /^[a-f0-9]{64}$/;
const LIMIT = 524288;
const JOB_MAX_SECONDS = 3 * 3600;
const security = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Strict-Transport-Security': 'max-age=31536000',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
};

export async function sha256(text) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(text))), b => b.toString(16).padStart(2, '0')).join('');
}
function same(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  const left = encoder.encode(a), right = encoder.encode(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...security, 'Content-Type': 'application/json; charset=utf-8', ...extra } });
}
class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function assert(condition, message) { if (!condition) throw new HttpError(400, message); }
const observerEngines=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
const exactKeys=(value,fields)=>object(value)&&Object.keys(value).length===fields.length&&fields.every(k=>Object.hasOwn(value,k));
const observerStamp=value=>value===null||(typeof value==='string'&&value.length<=40&&/T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value)));
const observerNumber=value=>value===null||(typeof value==='number'&&Number.isFinite(value));
const observerNonnegative=value=>observerNumber(value)&&(value===null||value>=0);
const observerPositive=value=>observerNumber(value)&&(value===null||value>0);
const observerCount=value=>Number.isSafeInteger(value)&&value>=0&&value<=100000;
const observerSymbol=value=>typeof value==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(value);
function validateEngineCatalog(catalog,mode){
  const expected=[
    ['SPOT','Spot Bot',mode==='TESTNET'?'SPOT_TESTNET':mode==='PAPER'?'PAPER':'UNKNOWN','TREND','OBSERVED_EXTERNALLY'],
    ['FUTURES','Futures Bot','FUTURES_DEMO','LONG_SHORT','OBSERVED_EXTERNALLY'],
    ['AI_MARKET_PULSE','AI Market Pulse','SHADOW','EVENTS','OBSERVED_EXTERNALLY'],
    ['QUANT_ARBITRAGE','Quant Arbitrage','SHADOW','CARRY_STATISTICAL_RESEARCH','NOT_STARTED']];
  assert(Array.isArray(catalog)&&catalog.length===4&&catalog.every((row,index)=>
    exactKeys(row,['id','name','environment','role','state'])&&
    ['id','name','environment','role','state'].every((key,column)=>row[key]===expected[index][column])),
    'Invalid engine catalog');
}
function validateQuantArbitrage(q){
  assert(exactKeys(q,['schema','engine','mode','state','initialized','enabled','execution_enabled',
    'controls_available','at','updated_at','freshness','positions','performance','strategies','promotion_allowed'])
    &&q.schema===1&&q.engine==='QUANT_ARBITRAGE'&&q.mode==='SHADOW'&&q.state==='NOT_STARTED'
    &&['initialized','enabled','execution_enabled','controls_available','promotion_allowed'].every(k=>q[k]===false)
    &&q.at!==null&&observerStamp(q.at)&&q.updated_at===null
    &&exactKeys(q.freshness,['state','age_seconds'])&&q.freshness.state==='UNAVAILABLE'&&q.freshness.age_seconds===null
    &&Array.isArray(q.positions)&&q.positions.length===0
    &&exactKeys(q.performance,['initial_capital','equity','net_pnl','closed_trades'])&&Object.values(q.performance).every(v=>v===null)
    &&Array.isArray(q.strategies)&&q.strategies.length===2&&q.strategies.every((row,index)=>
      exactKeys(row,['id','state'])&&row.id===['FUNDING_CARRY','STATISTICAL_ARBITRAGE'][index]&&row.state==='NOT_STARTED')
    &&JSON.stringify(q).length<1600,'Invalid Quant Arbitrage status');
}
function validatePortfolioGuardian(g){
  const error='Invalid Portfolio Guardian status';
  const native=['ARMED','PENDING','ERROR','UNAVAILABLE','RECONCILING','UNKNOWN','NOT_APPLICABLE'];
  const scopeFields=['id','engine','environment','inventory_scope','state','position_count','unpriced_positions',
    'gross_usdt','net_usdt','known_gross_usdt','known_net_usdt','nominal_stop_risk_usdt','capital','limits',
    'budget_status','observed_budget','assets','assets_omitted'];
  const assetFields=['symbol','direction','quantity','mark_price','notional_usdt','signed_notional_usdt',
    'stop_price','nominal_stop_risk_usdt','priced_at','native_protection','state','concentration_pct'];
  const asset=a=>exactKeys(a,assetFields)&&observerSymbol(a.symbol)&&['LONG','SHORT','UNKNOWN'].includes(a.direction)
    &&['quantity','mark_price','stop_price'].every(k=>observerPositive(a[k]))
    &&['notional_usdt','nominal_stop_risk_usdt'].every(k=>observerNonnegative(a[k]))
    &&observerNumber(a.signed_notional_usdt)&&observerStamp(a.priced_at)&&native.includes(a.native_protection)
    &&['FRESH','UNKNOWN'].includes(a.state)&&observerNonnegative(a.concentration_pct)
    &&(a.concentration_pct===null||a.concentration_pct<=100);
  const scope=(s,index)=>exactKeys(s,scopeFields)&&s.id===observerEngines[index]&&s.engine===s.id
    &&({SPOT:['SPOT_TESTNET','PAPER','UNKNOWN'],FUTURES:['FUTURES_DEMO'],AI_MARKET_PULSE:['SHADOW'],QUANT_ARBITRAGE:['SHADOW']}[s.id]).includes(s.environment)
    &&s.inventory_scope==='LEDGER_ONLY'&&['FRESH','PARTIAL','UNAVAILABLE','NOT_STARTED'].includes(s.state)
    &&['position_count','unpriced_positions'].every(k=>s[k]===null||observerCount(s[k]))
    &&['gross_usdt','known_gross_usdt','nominal_stop_risk_usdt'].every(k=>observerNonnegative(s[k]))
    &&['net_usdt','known_net_usdt'].every(k=>observerNumber(s[k]))
    &&exactKeys(s.capital,['equity_usdt','cash_usdt','available_usdt','at','state'])
    &&['equity_usdt','cash_usdt','available_usdt'].every(k=>observerNonnegative(s.capital[k]))
    &&observerStamp(s.capital.at)&&['FRESH','UNKNOWN'].includes(s.capital.state)
    &&exactKeys(s.limits,['gross_usdt','stop_risk_usdt'])&&Object.values(s.limits).every(observerPositive)
    &&exactKeys(s.budget_status,['gross','stop_risk'])&&['UNKNOWN','WITHIN','EXCEEDED'].includes(s.budget_status.gross)
    &&['UNKNOWN','OBSERVED_WITHIN','OBSERVED_EXCEEDED'].includes(s.budget_status.stop_risk)
    &&exactKeys(s.observed_budget,['gross_usdt','stop_risk_usdt','at'])
    &&observerNonnegative(s.observed_budget.gross_usdt)&&observerNonnegative(s.observed_budget.stop_risk_usdt)&&observerStamp(s.observed_budget.at)
    &&Array.isArray(s.assets)&&s.assets.length<=40&&s.assets.every(asset)
    &&new Set(s.assets.map(a=>a.symbol)).size===s.assets.length&&observerCount(s.assets_omitted)
    &&(s.position_count===null?s.assets.length===0:s.assets.length+s.assets_omitted<=s.position_count)
    &&(s.unpriced_positions===null||s.position_count!==null&&s.unpriced_positions<=s.position_count)
    &&(s.id!=='QUANT_ARBITRAGE'||s.state==='NOT_STARTED'&&s.position_count===null&&s.unpriced_positions===null
      &&['gross_usdt','net_usdt','known_gross_usdt','known_net_usdt','nominal_stop_risk_usdt'].every(k=>s[k]===null)
      &&['equity_usdt','cash_usdt','available_usdt','at'].every(k=>s.capital[k]===null)&&s.capital.state==='UNKNOWN'
      &&Object.values(s.limits).every(v=>v===null)&&Object.values(s.observed_budget).every(v=>v===null));
  const alertCodes=['GUARDIAN_UNAVAILABLE','INVALID_POSITION','DUPLICATE_POSITION','PROTECTIVE_THRESHOLD_CROSSED',
    'NATIVE_PROTECTION_UNCONFIRMED','POSITION_VALUE_UNKNOWN','AGGREGATE_VALUE_UNKNOWN','SOURCE_STALE_OR_UNAVAILABLE',
    'GROSS_LIMIT_EXCEEDED','OBSERVED_STOP_RISK_LIMIT_EXCEEDED'];
  const limitations=['SEPARATE_ENVIRONMENTS_NO_FINANCIAL_TOTAL','LEDGER_INVENTORY_IS_NOT_COMPLETE_EXCHANGE_ACCOUNT_RECONCILIATION',
    'NOMINAL_STOP_DISTANCE_EXCLUDES_COSTS_GAPS_AND_FUNDING','NATIVE_PROTECTION_IS_NOT_A_GUARANTEED_LOSS_BOUND',
    'RESERVATIONS_NOT_INTEGRATED_NO_ADMISSION_OR_VETO','CROSS_SCOPE_OVERLAP_IS_NOT_A_VERIFIED_HEDGE',
    'FUNDING_LIQUIDATION_NOT_OBSERVED','CORRELATION_DRAWDOWN_NOT_COMPUTED'];
  assert(exactKeys(g,['schema','engine','mode','state','at','controls_enabled','can_veto','execution_enabled',
    'scopes','reservations','risk_quality','overlaps','alerts','truncation','limitations'])
    &&g.schema===1&&g.engine==='PORTFOLIO_GUARDIAN'&&g.mode==='OBSERVER'
    &&['OBSERVING','PARTIAL','DEGRADED'].includes(g.state)&&g.at!==null&&observerStamp(g.at)
    &&g.controls_enabled===false&&g.can_veto===false&&g.execution_enabled===false
    &&Array.isArray(g.scopes)&&g.scopes.length===4&&g.scopes.every(scope)
    &&g.scopes.reduce((count,s)=>count+s.assets.length,0)<=40
    &&exactKeys(g.reservations,['state','reserved_usdt','reserved_stop_risk_usdt'])
    &&g.reservations.state==='NOT_INTEGRATED'&&g.reservations.reserved_usdt===null&&g.reservations.reserved_stop_risk_usdt===null
    &&exactKeys(g.risk_quality,['correlation','daily_loss','weekly_loss','drawdown'])&&Object.values(g.risk_quality).every(v=>v==='UNKNOWN'),error);
  assert(Array.isArray(g.alerts)&&g.alerts.length<=20&&g.alerts.every(a=>
    exactKeys(a,['code','severity','scope','symbol'])&&alertCodes.includes(a.code)&&a.severity==='WARNING'
    &&(a.scope===null||observerEngines.includes(a.scope))&&(a.symbol===null||observerSymbol(a.symbol)))
    &&Array.isArray(g.overlaps)&&g.overlaps.length<=10&&g.overlaps.every(o=>
      exactKeys(o,['symbol','scopes','directions','classification'])&&observerSymbol(o.symbol)&&o.classification==='CROSS_SCOPE_OBSERVATION'
      &&Array.isArray(o.scopes)&&o.scopes.length>=2&&o.scopes.length<=4&&o.scopes.every(s=>observerEngines.includes(s))
      &&new Set(o.scopes).size===o.scopes.length&&Array.isArray(o.directions)&&o.directions.length===o.scopes.length
      &&o.directions.every(d=>['LONG','SHORT','UNKNOWN'].includes(d)))
    &&exactKeys(g.truncation,['assets_omitted','alerts_omitted','overlaps_omitted'])&&Object.values(g.truncation).every(observerCount)
    &&g.truncation.assets_omitted===g.scopes.reduce((count,s)=>count+s.assets_omitted,0)
    &&Array.isArray(g.limitations)&&g.limitations.length===limitations.length&&new Set(g.limitations).size===limitations.length
    &&g.limitations.every(l=>limitations.includes(l))&&JSON.stringify(g).length<15000,error);
}
function validateMarketPulse(p) {
  const error='Invalid Market Pulse status';
  const keys=(value,allowed)=>object(value)&&Object.keys(value).every(k=>allowed.includes(k));
  const stamp=value=>value===null||(typeof value==='string'&&value.length<=40&&Number.isFinite(Date.parse(value)));
  const text=value=>typeof value==='string'&&value.length<=280;
  const finite=value=>value===null||(typeof value==='number'&&Number.isFinite(value));
  const nonnegative=value=>finite(value)&&(value===null||value>=0);
  const symbol=value=>typeof value==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(value);
  const identifier=value=>Number.isSafeInteger(value)&&value>=0||typeof value==='string'&&/^[a-zA-Z0-9._:-]{1,100}$/.test(value);
  const action=value=>['BUY','SELL','SHORT','HOLD','REJECT','WAIT_FOR_CONFIRMATION','WAIT FOR CONFIRMATION'].includes(value);
  const strings=value=>Array.isArray(value)&&value.length<=16&&value.every(text);
  const marketFields=['symbol','price','change_1m_pct','change_5m_pct','relative_volume','anomaly_z',
    'momentum','acceleration','volatility_pct','spread_bps','depth_quote','imbalance','liquidity_change_pct','fresh','complete','at'];
  const market=value=>keys(value,marketFields)&&symbol(value.symbol)
    &&Object.entries(value).every(([k,v])=>k==='symbol'||k==='at'&&stamp(v)
      ||['fresh','complete'].includes(k)&&typeof v==='boolean'
      ||!['symbol','at','fresh','complete'].includes(k)&&finite(v));
  const evidence=value=>keys(value,['market','event_id','rule_version','published_at','received_at','decision_at',
    'btc_change_1m_pct','btc_change_5m_pct','estimated_cost_bps','confirmations','selection_rank','selection_pool','selection_rule'])
    &&(value.selection_rank===undefined||value.selection_pool===undefined||value.selection_rank<=value.selection_pool)
    &&Object.entries(value).every(([k,v])=>k==='market'?market(v):k==='event_id'?v===null||identifier(v)
      :k==='rule_version'?text(v):['published_at','received_at','decision_at'].includes(k)?stamp(v)
      :['selection_rank','selection_pool'].includes(k)?Number.isInteger(v)&&v>=1&&v<=10
      :k==='selection_rule'?v==='QUANTITATIVE_SCORE_THEN_CONFIDENCE_LIQUIDITY'
      :k==='confirmations'?strings(v)||Number.isSafeInteger(v)&&v>=0:finite(v));
  const decisionFields=['id','at','symbol','score','confidence','action','favorable','risks','reason','evidence'];
  const decision=value=>keys(value,decisionFields)&&symbol(value.symbol)&&action(value.action)
    &&Object.entries(value).every(([k,v])=>['symbol','action'].includes(k)||k==='id'&&identifier(v)
      ||k==='at'&&stamp(v)||k==='score'&&Number.isFinite(v)&&v>=0&&v<=100
      ||k==='confidence'&&Number.isFinite(v)&&v>=0&&v<=1
      ||['favorable','risks'].includes(k)&&strings(v)||k==='reason'&&text(v)||k==='evidence'&&evidence(v));
  const safeUrl=value=>{
    if(value===null)return true;
    if(typeof value!=='string'||value.length>480)return false;
    try{const u=new URL(value);return u.protocol==='https:'&&u.hostname.includes('.')
      &&!u.username&&!u.password&&!u.search&&!u.hash&&(!u.port||u.port==='443')
      &&!u.hostname.endsWith('.local')&&!u.hostname.endsWith('.localhost')
      &&!/(?:sk-|gh[pousr]_|github_pat_|api[_-]?key|token|secret|password)/i.test(u.pathname);}catch{return false;}
  };
  const event=value=>keys(value,['id','published_at','received_at','symbol','source','url','title','impact',
    'credibility','kind','decision','reason','market_reaction_pct'])&&(symbol(value.symbol)||value.symbol==='MARKET')
    &&Object.entries(value).every(([k,v])=>k==='symbol'||k==='id'&&identifier(v)
      ||['published_at','received_at'].includes(k)&&stamp(v)||k==='url'&&safeUrl(v)
      ||['source','title','reason'].includes(k)&&text(v)||k==='kind'&&['official','report','rumor'].includes(v)
      ||k==='impact'&&['positive','negative','neutral','uncertain'].includes(v)
      ||k==='credibility'&&Number.isFinite(v)&&v>=0&&v<=1
      ||k==='decision'&&(v===null||action(v))||k==='market_reaction_pct'&&finite(v));
  const position=value=>keys(value,['symbol','quantity','entry_price','mark_price','stop','target','opened_at',
    'unrealized_pnl','environment'])&&symbol(value.symbol)&&value.environment==='SHADOW'
    &&Object.entries(value).every(([k,v])=>['symbol','environment'].includes(k)||k==='opened_at'&&stamp(v)
      ||!['symbol','environment','opened_at'].includes(k)&&finite(v));
  const performanceKeys=['initial_capital','cash','equity','net_pnl','return_pct','drawdown_pct','closed_trades',
    'win_rate_pct','profit_factor','exposure','observation_days','costs','environment','data_quality',
    'benchmark_cash_return_pct','benchmark_buy_hold'];
  assert(keys(p,['schema','engine','mode','state','at','updated_at','freshness','enabled','controls_available',
    'execution_enabled','sources','stats','market','events','opportunities','decisions','positions','performance','health','research',
    'news_providers','universe'])
    &&p.schema===1&&p.engine==='AI_MARKET_PULSE'&&p.mode==='SHADOW'&&p.execution_enabled===false
    &&['SHADOW','PAUSED','WARMING_UP','DEGRADED','NOT_STARTED'].includes(p.state)
    &&typeof p.enabled==='boolean'&&typeof p.controls_available==='boolean'&&(!p.controls_available||p.enabled)
    &&p.at!==null&&stamp(p.at)&&stamp(p.updated_at)
    &&keys(p.freshness,['state','age_seconds'])&&['FRESH','STALE','UNAVAILABLE'].includes(p.freshness.state)
    &&nonnegative(p.freshness.age_seconds),error);
  assert(keys(p.sources,['binance_ws','binance_rest','news'])&&Object.entries(p.sources).every(([k,v])=>
    keys(v,['state','last_update'])&&stamp(v.last_update)&&({binance_ws:['CONNECTING','CONNECTED','DISCONNECTED','STALE'],
      binance_rest:['STANDBY','RECOVERY','ERROR'],news:['DISABLED','READY','ERROR']}[k]).includes(v.state)),error);
  assert(keys(p.stats,['events_analyzed','relevant_news','opportunities','accepted','rejected','decisions'])
    &&Object.values(p.stats).every(v=>Number.isSafeInteger(v)&&v>=0),error);
  for(const [key,maximum,validate] of [['market',10,market],['events',12,event],['opportunities',12,decision],
    ['decisions',16,decision],['positions',3,position]]){
    assert(Array.isArray(p[key])&&p[key].length<=maximum&&p[key].every(validate),error);
  }
  assert(keys(p.performance,performanceKeys)&&Object.entries(p.performance).every(([k,v])=>
    k==='environment'?v==='SHADOW':k==='data_quality'?['COMPLETE','PARTIAL','UNAVAILABLE'].includes(v)
    :k==='benchmark_buy_hold'?v===null||object(v)&&Object.keys(v).length<=10
      &&keys(v,Object.keys(v).filter(symbol))&&Object.values(v).every(finite):finite(v)),error);
  if(p.news_providers!==undefined){
    assert(Array.isArray(p.news_providers)&&p.news_providers.length<=5
      &&new Set(p.news_providers.map(v=>v?.id)).size===p.news_providers.length
      &&p.news_providers.every(v=>keys(v,['id','name','url','kind','state','last_update','last_error'])
        &&typeof v.id==='string'&&/^[a-z][a-z0-9_-]{0,63}$/.test(v.id)&&text(v.name)
        &&safeUrl(v.url)&&['official','editorial','regulatory'].includes(v.kind)
        &&['READY','ERROR','STANDBY','DISABLED'].includes(v.state)&&stamp(v.last_update)
        &&(v.last_error===null||typeof v.last_error==='string'&&/^[A-Z0-9_:.-]{1,100}$/.test(v.last_error))),error);
  }
  if(p.universe!==undefined){
    assert(keys(p.universe,['selection','selected_at','source'])
      &&Object.values(p.universe).every(text)
      &&(!/^https?:/i.test(p.universe.source)||safeUrl(p.universe.source)),error);
  }
  assert(keys(p.health,['latency_ms','reconnects','errors','last_error','ws_messages','rest_calls','news_calls',
    'ai_reviews','ai_errors','buffer_seconds','uptime_seconds','ai_daily_cap','ai_used_today',
    'ai_min_interval_seconds','ai_max_output_tokens','ai_max_input_bytes'])&&Object.entries(p.health).every(([k,v])=>
      k==='last_error'?v===null||typeof v==='string'&&/^[A-Z0-9_:.-]{1,100}$/.test(v):nonnegative(v)),error);
  assert(keys(p.research,['state','hypothesis_version','promotion_allowed','limitations'])
    &&p.research.state==='FORWARD_ONLY'&&p.research.promotion_allowed===false&&text(p.research.hypothesis_version)
    &&strings(p.research.limitations)&&JSON.stringify(p).length<20000,error);
}
async function readBody(request, maximum = 65536) {
  if ((request.headers.get('content-type') || '').split(';')[0] !== 'application/json') throw new HttpError(415, 'JSON required');
  const declared = request.headers.get('content-length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > maximum)) throw new HttpError(413, 'Body too large');
  if (!request.body) throw new HttpError(400, 'Body required');
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maximum) { await reader.cancel(); throw new HttpError(413, 'Body too large'); }
    chunks.push(value);
  }
  const data = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length; }
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(data)); }
  catch { throw new HttpError(400, 'Invalid JSON'); }
  assert(object(value), 'Object required');
  return value;
}
function validateSnapshot(snapshot) {
  assert(object(snapshot) && ['PAPER','TESTNET'].includes(snapshot.mode), 'Trading snapshot required');
  const allowed = ['mode','equity','cash','exposure','positions','killed','last_cycle_at','ai_model','installed_version','update_state','dashboard','bot_update','bot_restore','paper_controls','operations_controls'];
  assert(Object.keys(snapshot).every(k => allowed.includes(k)), 'Unknown snapshot field');
  if(snapshot.paper_controls!==undefined)assert(snapshot.paper_controls===true,'Invalid PAPER capability');
  if(snapshot.operations_controls!==undefined)assert(snapshot.operations_controls===true,'Invalid controls capability');
  for (const key of ['equity', 'cash', 'exposure']) {
    assert(snapshot[key] === null || (typeof snapshot[key] === 'number' && Number.isFinite(snapshot[key]) && snapshot[key] >= 0), 'Invalid balance');
  }
  assert(typeof snapshot.killed === 'boolean', 'Invalid pause state');
  assert(snapshot.last_cycle_at === null || (typeof snapshot.last_cycle_at === 'string' && snapshot.last_cycle_at.length <= 40 && Number.isFinite(Date.parse(snapshot.last_cycle_at))), 'Invalid cycle time');
  assert(typeof snapshot.ai_model === 'string' && /^[a-zA-Z0-9._-]{1,80}$/.test(snapshot.ai_model) && !snapshot.ai_model.startsWith('sk-'), 'Invalid model');
  if(snapshot.installed_version!==undefined&&snapshot.installed_version!==null){
    assert(typeof snapshot.installed_version==='string'&&/^\d+\.\d+\.\d+$/.test(snapshot.installed_version),'Invalid installed version');
  }
  assert(['manual_signed_install_only','signed_rollout'].includes(snapshot.update_state), 'Invalid update state');
  if(snapshot.bot_update!=null){
    const b=snapshot.bot_update;
    assert(object(b)&&Object.keys(b).every(k=>['release_id','version','sequence','expires','commit','enabled'].includes(k)),'Invalid bot release');
    assert(HASH.test(b.release_id)&&/^\d+\.\d+\.\d+$/.test(b.version)&&/^[a-f0-9]{40}$/.test(b.commit)&&Number.isSafeInteger(b.sequence)&&b.sequence>0&&Number.isInteger(b.expires)&&typeof b.enabled==='boolean','Invalid bot release');
  }
  if(snapshot.bot_restore!=null){
    const b=snapshot.bot_restore;
    assert(object(b)&&Object.keys(b).sort().join(',')==='current_release_id,current_version,enabled,restore_id,version','Invalid restore offer');
    assert(HASH.test(b.restore_id)&&HASH.test(b.current_release_id)&&/^\d+\.\d+\.\d+$/.test(b.version)&&/^\d+\.\d+\.\d+$/.test(b.current_version)&&b.enabled===true,'Invalid restore offer');
  }
  assert(Array.isArray(snapshot.positions) && snapshot.positions.length <= 100, 'Invalid positions');
  for (const p of snapshot.positions) {
    assert(object(p) && Object.keys(p).length === 5 && /^[A-Z0-9]{2,30}$/.test(p.symbol), 'Invalid position');
    for (const key of ['quantity','entry_price','stop_price','take_profit']) assert(typeof p[key] === 'number' && Number.isFinite(p[key]) && p[key] > 0, 'Invalid position value');
  }
  if (snapshot.dashboard !== undefined) {
    const d = snapshot.dashboard;
    assert(object(d) && object(d.status) && d.status.mode === snapshot.mode, 'Invalid dashboard');
    if(d.status.spot_cycle!=null){
      const c=d.status.spot_cycle;
      const counts=['universe','evaluated','signals','candidates','reviews','opened'];
      const codes=['BELOW_SCORE','ALREADY_HELD','MISSING_CANDLES','QUOTE_UNAVAILABLE','PRICE_OUTSIDE_RANGE',
        'POSITION_COUNT_LIMIT','TOTAL_EXPOSURE_LIMIT','EQUITY_LIMIT','AI_CYCLE_LIMIT','AI_DAILY_LIMIT',
        'CANDLE_ALREADY_CHECKED','AI_REJECTED','AI_UNAVAILABLE','SIZE_LIMIT','PAUSED','LOSS_LIMIT',
        'EXCHANGE_RULES_UNAVAILABLE','EXCHANGE_FILTER_PREFLIGHT','POSITION_SIZE_LIMIT','PER_TRADE_RISK_LIMIT',
        'LOCAL_ALLOCATION_LIMIT','LOCAL_CASH_LIMIT','PRICE_MOVED_OUTSIDE_SIGNAL_RANGE','EXCHANGE_FILTER_REJECTED',
        'TESTNET_BALANCE_LIMIT','NATIVE_PROTECTION_BLOCKED','CYCLE_ERROR'];
      const errors=['ORDER_RECONCILIATION_PENDING','BTC_REGIME_UNAVAILABLE','FRESH_PRICES_UNAVAILABLE',
        'INVALID_SPOT_QUOTE','HELD_QUOTE_MISSING','HELD_QUOTE_INVALID','UNEXPECTED_VALUE_ERROR',
        'TESTNET_EXECUTION_ERROR','UNEXPECTED_ERROR'];
      const h=c.risk_halt;
      const validRiskHalt=h===undefined||h===null||(object(h)
        &&Object.keys(h).every(k=>['periods','daily_return_pct','weekly_return_pct','daily_limit_pct','weekly_limit_pct','resets_at'].includes(k))
        &&Array.isArray(h.periods)&&h.periods.length>=1&&h.periods.length<=2
        &&new Set(h.periods).size===h.periods.length&&h.periods.every(p=>['daily','weekly'].includes(p))
        &&['daily_return_pct','weekly_return_pct','daily_limit_pct','weekly_limit_pct'].every(k=>Number.isFinite(h[k]))
        &&typeof h.resets_at==='string'&&h.resets_at.length<=40&&Number.isFinite(Date.parse(h.resets_at)));
      assert(object(c)&&Object.keys(c).every(k=>['state','at',...counts,'reasons','minimum_score','btc_bullish','error_code','risk_halt','age_seconds','fresh'].includes(k))
        &&['RUNNING','NO_OPPORTUNITIES','FILTERED','LIMITED','OPENED','PAUSED','RISK_HALT','ATTENTION','ERROR'].includes(c.state)
        &&typeof c.at==='string'&&c.at.length<=40&&Number.isFinite(Date.parse(c.at))
        &&counts.every(k=>Number.isInteger(c[k])&&c[k]>=0&&c[k]<=10000)
        &&Number.isInteger(c.minimum_score)&&c.minimum_score>=0&&c.minimum_score<=100
        &&(c.btc_bullish===null||typeof c.btc_bullish==='boolean')
        &&(c.error_code===null||errors.includes(c.error_code))
        &&validRiskHalt
        &&typeof c.fresh==='boolean'&&Number.isFinite(c.age_seconds)&&c.age_seconds>=0
        &&object(c.reasons)&&Object.entries(c.reasons).every(([k,v])=>codes.includes(k)&&Number.isInteger(v)&&v>0&&v<=10000)
        &&JSON.stringify(c).length<2400,'Invalid Spot cycle diagnostic');
    }
    assert(Object.keys(d).every(k=>['status','positions','equity','trades','reviews','events','risk','research','research_state','testnet','testnet_execution','updates','paper_scorecard','futures_forward','market_pulse','portfolio_guardian','quant','engine_catalog'].includes(k)), 'Unknown dashboard field');
    if(d.market_pulse!==undefined)validateMarketPulse(d.market_pulse);
    if(d.portfolio_guardian!==undefined)validatePortfolioGuardian(d.portfolio_guardian);
    if(d.quant!==undefined)validateQuantArbitrage(d.quant);
    if(d.engine_catalog!==undefined)validateEngineCatalog(d.engine_catalog,d.status.mode);
    if(d.testnet_execution!==undefined){
      const x=d.testnet_execution;
      assert(object(x)&&x.mode==='SPOT_TESTNET'&&Array.isArray(x.orders)&&x.orders.length<=5&&
        typeof x.next_step==='string'&&x.next_step.length<200&&JSON.stringify(x).length<2400,
        'Invalid Testnet execution');
    }
    if(d.futures_forward!==undefined){
      const f=d.futures_forward;
      if(f.leverage_trials!==undefined){
        const t=f.leverage_trials;
        assert(object(t)&&Object.keys(t).every(k=>['levels','next_leverage','fixed_notional','notional_limit_usdt','started_at','results'].includes(k))
          &&Array.isArray(t.levels)&&t.levels.length>=1&&t.levels.length<=3
          &&t.levels.every(l=>Number.isInteger(l)&&[1,2,3].includes(l))&&new Set(t.levels).size===t.levels.length
          &&t.levels.includes(t.next_leverage)&&t.fixed_notional===true
          &&Number.isFinite(t.notional_limit_usdt)&&t.notional_limit_usdt>=5&&t.notional_limit_usdt<=100
          &&(t.started_at===null||(typeof t.started_at==='string'&&t.started_at.length<=40&&Number.isFinite(Date.parse(t.started_at))))
          &&Array.isArray(t.results)&&t.results.length===t.levels.length
          &&t.results.every((r,i)=>object(r)&&Object.keys(r).every(k=>['leverage','closed_trades','gross_pnl_usdt'].includes(k))
            &&r.leverage===t.levels[i]&&Number.isInteger(r.closed_trades)&&r.closed_trades>=0&&Number.isFinite(r.gross_pnl_usdt)),
          'Invalid Futures leverage trials');
      }
      if(f.portfolio_budget!==undefined&&f.portfolio_budget!==null){
        const b=f.portfolio_budget;
        assert(object(b)&&Object.keys(b).every(k=>['notional_limit_usdt','stop_loss_limit_usdt','cost_buffer_pct','notional_usdt','stop_loss_usdt','at'].includes(k))
          &&Number.isFinite(b.notional_limit_usdt)&&b.notional_limit_usdt>=5&&b.notional_limit_usdt<=300
          &&Number.isFinite(b.stop_loss_limit_usdt)&&b.stop_loss_limit_usdt>0&&b.stop_loss_limit_usdt<=7.5
          &&Number.isFinite(b.cost_buffer_pct)&&b.cost_buffer_pct>=.005&&b.cost_buffer_pct<=.02
          &&['notional_usdt','stop_loss_usdt'].every(k=>Number.isFinite(b[k])&&b[k]>=0)
          &&typeof b.at==='string'&&b.at.length<=40&&Number.isFinite(Date.parse(b.at)), 'Invalid Futures portfolio budget');
      }
      if(f.cycle_diagnostic!==undefined&&f.cycle_diagnostic!==null){
        const x=f.cycle_diagnostic;
        const states=['WAITING_CANDLE','NO_OPPORTUNITIES','FILTERED','LIMITED','OPENED','ATTENTION','RISK_HALT','ACTIVE'];
        const statusCodes=['NO_NEW_CANDLE','FLAT','OPEN','OPENED','CLOSED','POSITION_LIMIT','KILLED','PENDING_RECONCILIATION','RISK_HALT','OFF','ASSET_UNAVAILABLE',
          'BUDGET_LIMIT','MARGIN_LIMIT','TRIAL_MARGIN_RISK_LIMIT','AI_BUDGET','AI_REJECTED','PRICE_OUTSIDE_RANGE','BLOCKED','NO_DATA','ERROR'];
        const validIssues=x.issues===undefined||(Array.isArray(x.issues)&&x.issues.length<=15
          &&x.issues.every(row=>object(row)
            &&Object.keys(row).every(k=>['symbol','status','reason'].includes(k))
            &&typeof row.symbol==='string'&&/^[A-Z0-9]{2,20}$/.test(row.symbol)
            &&['BLOCKED','ASSET_UNAVAILABLE','NO_DATA'].includes(row.status)
            &&typeof row.reason==='string'&&row.reason.length<=180));
        assert(object(x)&&Object.keys(x).every(k=>['state','at','timeframe','minimum_score','symbols','evaluated','signals','reviews','opened','statuses','issues'].includes(k))
          &&states.includes(x.state)&&typeof x.at==='string'&&x.at.length<=40&&Number.isFinite(Date.parse(x.at))
          &&typeof x.timeframe==='string'&&x.timeframe.length<=4
          &&Number.isInteger(x.minimum_score)&&x.minimum_score>=0&&x.minimum_score<=100
          &&['symbols','evaluated','signals','reviews','opened'].every(k=>Number.isInteger(x[k])&&x[k]>=0&&x[k]<=100)
          &&object(x.statuses)&&Object.entries(x.statuses).every(([k,v])=>statusCodes.includes(k)&&Number.isInteger(v)&&v>0&&v<=100)
          &&validIssues
          &&JSON.stringify(x).length<6000,'Invalid Futures cycle diagnostic');
      }
      const oldShape=f.symbol==='BTCUSDT'&&(f.position===null||object(f.position));
      const newShape=Array.isArray(f.symbols)&&f.symbols.length>=1&&f.symbols.length<=15
        &&f.symbols.every(s=>typeof s==='string'&&/^[A-Z0-9]{2,30}$/.test(s))
        &&Array.isArray(f.positions)&&f.positions.length<=10
        &&f.positions.every(p=>object(p)&&typeof p.symbol==='string'&&/^[A-Z0-9]{2,30}$/.test(p.symbol));
      if(f.latest_signals!==undefined){
        const allowed=['symbol','timeframe','candle_close_time','direction','score','long_score','short_score',
          'price','atr','rsi','ema_fast','ema_slow','volume_ratio','at'];
        assert(object(f.latest_signals)&&Object.keys(f.latest_signals).length<=15
          &&Object.entries(f.latest_signals).every(([symbol,s])=>/^[A-Z0-9]{2,30}$/.test(symbol)
            &&(s===null||(object(s)&&Object.keys(s).every(k=>allowed.includes(k))
              &&['score','long_score','short_score'].every(k=>Number.isInteger(s[k])&&s[k]>=0&&s[k]<=100)
              &&['price','atr','rsi','ema_fast','ema_slow','volume_ratio'].every(k=>typeof s[k]==='number'&&Number.isFinite(s[k]))
              &&(s.direction===null||['LONG','SHORT'].includes(s.direction))
              &&(s.symbol===undefined||s.symbol===symbol)
              &&(s.timeframe===undefined||(typeof s.timeframe==='string'&&s.timeframe.length<=4))
              &&(s.candle_close_time===undefined||(Number.isSafeInteger(s.candle_close_time)&&s.candle_close_time>0))
              &&typeof s.at==='string'&&s.at.length<=40&&Number.isFinite(Date.parse(s.at)))))
          &&JSON.stringify(f.latest_signals).length<12000,'Invalid Futures latest signals');
      }
      if(f.pause_diagnostics!==undefined){
        const p=f.pause_diagnostics;
        const validLastError=p.last_error===null||(object(p.last_error)
          &&Object.keys(p.last_error).every(k=>['message','at'].includes(k))
          &&typeof p.last_error.message==='string'&&p.last_error.message.length<=240
          &&(p.last_error.at===null||(typeof p.last_error.at==='string'&&p.last_error.at.length<=40&&Number.isFinite(Date.parse(p.last_error.at)))));
        const incident=p.incident;
        const validIncident=incident===undefined||incident===null||(object(incident)
          &&Object.keys(incident).every(k=>['id','source','message','repetitions','first_at','last_at','resolved_at'].includes(k))
          &&(incident.id===null||(typeof incident.id==='string'&&/^FUT-\d{4,}$/.test(incident.id)&&incident.id.length<=32))
          &&(incident.source===null||['cycle','protection'].includes(incident.source))
          &&typeof incident.message==='string'&&incident.message.length<=240
          &&Number.isInteger(incident.repetitions)&&incident.repetitions>=1&&incident.repetitions<=1000000
          &&['first_at','last_at','resolved_at'].every(k=>incident[k]===null||(typeof incident[k]==='string'&&incident[k].length<=40&&Number.isFinite(Date.parse(incident[k])))));
        assert(object(p)&&Object.keys(p).every(k=>['active','label','detail','source','paused_at','last_error','consecutive_errors','incident','pending_reconciliation'].includes(k))
          &&typeof p.active==='boolean'
          &&(p.label===null||(typeof p.label==='string'&&p.label.length<=240))
          &&(p.detail===null||(typeof p.detail==='string'&&p.detail.length<=240))
          &&(p.source===null||['manual','automatic_safety'].includes(p.source))
          &&(p.paused_at===null||(typeof p.paused_at==='string'&&p.paused_at.length<=40&&Number.isFinite(Date.parse(p.paused_at))))
          &&Number.isInteger(p.consecutive_errors)&&p.consecutive_errors>=0&&p.consecutive_errors<=100000
          &&typeof p.pending_reconciliation==='boolean'&&validLastError&&validIncident,
          'Invalid Futures pause diagnostics');
      }
      assert(object(f)&&typeof f.enabled==='boolean'&&typeof f.killed==='boolean'
        &&(oldShape||newShape)&&f.automatic_leverage===1
        &&Array.isArray(f.trades)&&f.trades.length<=50
        &&Array.isArray(f.equity)&&f.equity.length<=120
        &&Number.isInteger(f.closed_trades)&&f.closed_trades>=0
        &&typeof f.gross_pnl==='number'&&Number.isFinite(f.gross_pnl)
        &&JSON.stringify(f).length<120000,'Invalid Futures forward status');
    }
    if(d.paper_scorecard!==undefined){
      const s=d.paper_scorecard;
      assert(object(s)&&s.mode===snapshot.mode&&['INSUFFICIENT_EVIDENCE','REVIEW_REQUIRED'].includes(s.status),'Invalid financial scorecard');
      assert(Object.keys(s).length<=36&&Array.isArray(s.by_asset)&&s.by_asset.length<=50
        &&(!s.attribution||(object(s.attribution)&&Array.isArray(s.attribution.exit_reasons)
          &&s.attribution.exit_reasons.length<=4&&Array.isArray(s.attribution.research_symbols)
          &&s.attribution.research_symbols.length<=30))
        &&JSON.stringify(s).length<13000,'Oversized PAPER scorecard');
    }
    for(const key of ['positions','equity','trades','reviews','events'])assert(Array.isArray(d[key]) && d[key].length<=300,'Dashboard rows exceeded');
    assert(object(d.research) && Array.isArray(d.research.assets) && d.research.assets.length<=30
      &&JSON.stringify(d.research).length<=240000,'Invalid research report');
    if(d.research.joint_portfolios!==undefined){
      const r=d.research;
      assert(r.mode==='RESEARCH_ONLY'&&r.auto_promotion===false
        &&Array.isArray(r.futures_assets)&&r.futures_assets.length<=15
        &&Array.isArray(r.joint_portfolios)&&r.joint_portfolios.length<=18
        &&Array.isArray(r.history)&&r.history.length<=12,'Invalid research report');
      for(const p of r.joint_portfolios){
        assert(object(p)&&p.method==='joint_execution_shared_cash'&&['SPOT','FUTURES'].includes(p.market)
          &&['prudente','base','agresivo'].includes(p.profile)&&[1,2,3,5,10].includes(p.leverage)
          &&p.automatic_promotion===false&&Array.isArray(p.curve)&&p.curve.length<=120
          &&object(p.limits)&&Number.isInteger(p.limits.positions)&&p.limits.positions<=5
          &&['net_return_pct','max_drawdown_pct','closed_trades','fees','funding_cost','liquidations'].every(k=>Number.isFinite(p[k]))
          &&!('trades' in p),'Invalid research report');
      }
    }
    if(d.testnet!==undefined){
      const t=d.testnet;
      assert(object(t)&&Object.keys(t).every(k=>['mode','order_submission_enabled','planner','next_step'].includes(k))
        &&t.mode==='READ_ONLY_DRY_RUN'&&t.order_submission_enabled===false
        &&typeof t.planner==='string'&&t.planner.length<=120
        &&typeof t.next_step==='string'&&t.next_step.length<=240,'Invalid Testnet status');
    }
  }
  return snapshot;
}
function statement(db, sql, ...args) { return db.prepare(sql).bind(...args); }
// The production jobs table accepts only its original actions. Encode a
// restoration distinctly in its existing release_id column, then expose the
// original action and exact hash to both Windows and the authenticated owner.
const restoreStored = "action='update_install' AND substr(release_id,1,8)='restore:'";
// D1's existing jobs ledger also holds the two strictly validated PAPER actions.
// Prefixes distinguish them from real research jobs without a schema change.
const closeStored = "action='research' AND substr(COALESCE(release_id,''),1,12)='paper_close:'";
const riskStored = "action='research' AND substr(COALESCE(release_id,''),1,13)='risk_profile:'";
const modelStored = "action='research' AND substr(COALESCE(release_id,''),1,9)='ai_model:'";
const restartStored = "action='research' AND substr(COALESCE(release_id,''),1,15)='restart_engine:'";
const executionModeStored = "action='research' AND substr(COALESCE(release_id,''),1,15)='execution_mode:'";
const testnetSmokeStored = "action='research' AND substr(COALESCE(release_id,''),1,14)='testnet_smoke:'";
const futuresCheckStored = "action='research' AND substr(COALESCE(release_id,''),1,length('futures_testnet_check:'))='futures_testnet_check:'";
const futuresSmokeStored = "action='research' AND substr(COALESCE(release_id,''),1,length('futures_testnet_smoke:'))='futures_testnet_smoke:'";
const futuresReconcileStored = "action='research' AND substr(COALESCE(release_id,''),1,length('futures_testnet_reconcile:'))='futures_testnet_reconcile:'";
const futuresForwardPauseStored = "action='research' AND substr(COALESCE(release_id,''),1,length('futures_forward_pause:'))='futures_forward_pause:'";
const futuresForwardResumeStored = "action='research' AND substr(COALESCE(release_id,''),1,length('futures_forward_resume:'))='futures_forward_resume:'";
const marketPulsePauseStored = "action='research' AND substr(COALESCE(release_id,''),1,length('market_pulse_pause:'))='market_pulse_pause:'";
const marketPulseResumeStored = "action='research' AND substr(COALESCE(release_id,''),1,length('market_pulse_resume:'))='market_pulse_resume:'";
const testBuyStored = "action='research' AND substr(COALESCE(release_id,''),1,12)='testnet_buy:'";
const testCloseStored = "action='research' AND substr(COALESCE(release_id,''),1,14)='testnet_close:'";
const testReconcileStored = "action='research' AND substr(COALESCE(release_id,''),1,18)='testnet_reconcile:'";
const testAuditStored = "action='research' AND substr(COALESCE(release_id,''),1,14)='testnet_audit:'";
const paperStored = `(${closeStored} OR ${riskStored} OR ${modelStored} OR ${restartStored} OR ${executionModeStored} OR ${testnetSmokeStored} OR ${futuresCheckStored} OR ${futuresSmokeStored} OR ${futuresReconcileStored} OR ${futuresForwardPauseStored} OR ${futuresForwardResumeStored} OR ${marketPulsePauseStored} OR ${marketPulseResumeStored} OR ${testBuyStored} OR ${testCloseStored} OR ${testReconcileStored} OR ${testAuditStored})`;
const jobAction = `CASE WHEN ${closeStored} THEN 'paper_close' WHEN ${riskStored} THEN 'risk_profile' WHEN ${modelStored} THEN 'ai_model' WHEN ${restartStored} THEN 'restart_engine' WHEN ${executionModeStored} THEN 'execution_mode' WHEN ${testnetSmokeStored} THEN 'testnet_smoke' WHEN ${futuresCheckStored} THEN 'futures_testnet_check' WHEN ${futuresSmokeStored} THEN 'futures_testnet_smoke' WHEN ${futuresReconcileStored} THEN 'futures_testnet_reconcile' WHEN ${futuresForwardPauseStored} THEN 'futures_forward_pause' WHEN ${futuresForwardResumeStored} THEN 'futures_forward_resume' WHEN ${marketPulsePauseStored} THEN 'market_pulse_pause' WHEN ${marketPulseResumeStored} THEN 'market_pulse_resume' WHEN ${testBuyStored} THEN 'testnet_buy' WHEN ${testCloseStored} THEN 'testnet_close' WHEN ${testReconcileStored} THEN 'testnet_reconcile' WHEN ${testAuditStored} THEN 'testnet_audit' WHEN ${restoreStored} THEN 'update_restore' ELSE action END`;
const jobRelease = `CASE WHEN ${restoreStored} THEN substr(release_id,9) ELSE release_id END`;
function results(batch, index) { return batch[index]?.results || []; }
function newerVersion(candidate,installed){
  if(!/^\d+\.\d+\.\d+$/.test(candidate||'')||!/^\d+\.\d+\.\d+$/.test(installed||''))return false;
  const a=candidate.split('.').map(Number),b=installed.split('.').map(Number);
  for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]>b[i];}
  return false;
}
function cookie(request) {
  const values = (request.headers.get('cookie') || '').split(';').map(p => p.trim()).filter(p => p.startsWith('__Host-session='));
  return values.length === 1 ? values[0].slice('__Host-session='.length) : '';
}
function sessionCookie(token, age = 3600) { return `__Host-session=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${age}`; }
async function passwordBudget(db,now){
  const budget=await statement(db,`INSERT INTO login_budget VALUES(1,?,1)
    ON CONFLICT(id) DO UPDATE SET attempts=CASE WHEN window_start<=? THEN 1 ELSE attempts+1 END,
    window_start=CASE WHEN window_start<=? THEN excluded.window_start ELSE window_start END
    WHERE attempts<10 OR window_start<=? RETURNING attempts`,now,now-300,now-300,now-300).all();
  if(!budget.results.length)throw new HttpError(429,'Espera cinco minutos antes de volver a intentarlo');
}
async function matchesPassword(value,credential,bootstrap){
  if(typeof value!=='string'||value.length>128)return false;
  if(!credential)return TOKEN.test(value)&&same(await sha256(value),bootstrap);
  if(!validPassword(value)||credential.iterations!==PASSWORD_ITERATIONS)return false;
  return same(await passwordDigest(value,credential.salt),credential.digest);
}

export async function handle(request, env, now = Math.floor(Date.now() / 1000)) {
  const url = new URL(request.url);
  const method = request.method, path = url.pathname;
  // No inferred Host, forwarded origin, or fallback credentials in production.
  if (!env.PORTAL_ORIGIN || new URL(env.PORTAL_ORIGIN).origin !== env.PORTAL_ORIGIN || !env.PORTAL_ORIGIN.startsWith('https://') || env.PORTAL_ORIGIN.endsWith('.invalid')) return json({ error: 'Portal not provisioned' }, 503);
  if (url.origin !== env.PORTAL_ORIGIN) return json({ error: 'Origin not allowed' }, 403);
  if (url.search) {
    if (method === 'GET' && path === '/' && url.searchParams.size === 1 && url.searchParams.has('v')) {
      return Response.redirect(env.PORTAL_ORIGIN + '/', 302);
    }
    return json({ error: 'Query parameters not accepted' }, 400);
  }
  if (!['GET', 'POST'].includes(method)) return json({ error: 'Method not allowed' }, 405, { Allow: 'GET, POST' });
  if(path==='/v1/health' && method==='GET'){
    await statement(env.DB,'SELECT id FROM jobs LIMIT 1').all();
    return json({status:'ok',commit:/^[a-f0-9]{40}$/.test(env.PORTAL_COMMIT||'')?env.PORTAL_COMMIT:null});
  }
  if (method === 'GET' && ['/', '/app.js', '/style.css','/styles.css','/monitoring.css','/portal-bridge.js','/portal.css','/crypto-ai-trader-icon.png','/manifest.webmanifest','/service-worker.js'].includes(path)) {
    const asset = await env.ASSETS.fetch(request);
    const headers = new Headers(asset.headers);
    for (const [name, value] of Object.entries(security)) headers.set(name, value);
    headers.set('Cache-Control','no-store, max-age=0');
    headers.set('Pragma','no-cache');
    return new Response(asset.body, { status: asset.status, headers });
  }
  if (!HASH.test(env.OWNER_KEY_HASH || '') || !HASH.test(env.DEVICE_KEY_HASH || '') || env.OWNER_KEY_HASH === env.DEVICE_KEY_HASH) return json({ error: 'Portal not provisioned' }, 503);
  const db = env.DB;
  if(path==='/v1/releases/sign'&&method==='POST'){
    const body=await readBody(request,LIMIT);
    try{return json(await signRelease(env,(request.headers.get('authorization')||'').replace(/^Bearer /,''),body,now));}
    catch(error){return json({error:'Publisher authorization or signed release validation failed',code:releaseFailureCode(error)},403);}
  }
  if(path==='/v1/releases/latest'&&method==='GET'){
    const row=await statement(db,'SELECT envelope FROM bot_releases ORDER BY sequence DESC LIMIT 1').first();
    return row?json(JSON.parse(row.envelope)):json({error:'No signed bot release published'},404);
  }
  if (path === '/v1/device/sync' && method === 'POST') {
    const auth = request.headers.get('authorization') || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
    if (!TOKEN.test(token) || !same(await sha256(token), env.DEVICE_KEY_HASH)) return json({ error: 'Unauthorized device' }, 401);
    const body = await readBody(request, LIMIT);
    assert(Object.keys(body).every(k => ['snapshot','acks','job_results','control_results'].includes(k)), 'Unknown field');
    const snapshot = validateSnapshot(body.snapshot);
    const acks = body.acks || [];
    assert(Array.isArray(acks) && acks.length <= 50 && acks.every(id => Number.isSafeInteger(id) && id > 0), 'Invalid acknowledgements');
    const queries = [statement(db, 'INSERT INTO snapshots(id,payload,received_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,received_at=excluded.received_at', JSON.stringify(snapshot), now)];
    if (acks.length) queries.push(statement(db, `UPDATE commands SET status='applied' WHERE id IN (${acks.map(() => '?').join(',')}) AND status IN ('pending','expired') AND delivered_at IS NOT NULL`, ...acks));
    queries.push(statement(db, "UPDATE commands SET status='expired' WHERE status='pending' AND expires<=?", now));
    queries.push(statement(db, "UPDATE commands SET delivered_at=? WHERE status='pending' AND delivered_at IS NULL", now));
    queries.push(statement(db, "SELECT id,action,expires FROM commands WHERE status='pending' ORDER BY id LIMIT 50"));
    const commandIndex = queries.length-1;
    const jobResults=body.job_results||[];
    assert(Array.isArray(jobResults)&&jobResults.length<=20,'Invalid job results');
    const jq=[];
    for(const job of jobResults){
      assert(object(job)&&Object.keys(job).every(key=>['id','action','status','message'].includes(key))&&
        Number.isSafeInteger(job.id)&&job.id>0&&['research','update_check','update_install','update_restore'].includes(job.action)&&
        ['running','completed','failed'].includes(job.status),'Invalid job result');
      assert(typeof job.message==='string'&&job.message.length<=300,'Invalid job message');
      jq.push(statement(db,`UPDATE jobs SET status=?,message=? WHERE id=? AND ${jobAction}=? AND delivered_at IS NOT NULL AND status IN ('pending','running')`,job.status,job.message,job.id,job.action));
    }
    jq.push(statement(db,"UPDATE jobs SET status='expired' WHERE status='pending' AND expires<=?",now));
    jq.push(statement(db,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS));
    if(snapshot.update_state==='signed_rollout'&&snapshot.installed_version){
      const latest=await statement(db,'SELECT release_id,envelope FROM bot_releases ORDER BY sequence DESC LIMIT 1').first();
      if(latest){
        let latestVersion=null;
        try{latestVersion=JSON.parse(latest.envelope)?.manifest?.version||null;}catch{}
        if(HASH.test(latest.release_id)&&newerVersion(latestVersion,snapshot.installed_version)){
          const autoRequest='auto_rollout_'+latest.release_id.slice(0,40);
          jq.push(statement(db,`UPDATE jobs SET status='pending',created=?,expires=?,delivered_at=NULL,message='' WHERE request_id=? AND action='update_install' AND release_id=? AND status='expired'`,
            now,now+300,autoRequest,latest.release_id));
          jq.push(statement(db,`INSERT INTO jobs(request_id,action,status,created,expires,release_id)
            SELECT ?,'update_install','pending',?,?,? WHERE NOT EXISTS(
              SELECT 1 FROM jobs WHERE request_id=? OR status IN ('pending','running')
            )`,autoRequest,now,now+300,latest.release_id,autoRequest));
        }
      }
    }
    jq.push(statement(db,"UPDATE jobs SET delivered_at=COALESCE(delivered_at,?) WHERE status='pending' AND expires>?",now,now));
    jq.push(statement(db,`SELECT id,${jobAction} AS action,expires,${jobRelease} AS release_id FROM jobs WHERE status='pending' AND expires>? AND NOT ${paperStored} ORDER BY id LIMIT 1`,now));
    const controlResults=body.control_results||[];
    assert(Array.isArray(controlResults)&&controlResults.length<=20,'Invalid PAPER results');
    const cq=[];
    for(const item of controlResults){
      assert(object(item)&&Object.keys(item).sort().join(',')==='id,message,status'&&
        Number.isSafeInteger(item.id)&&item.id>0&&['completed','failed'].includes(item.status)&&
        typeof item.message==='string'&&item.message.length<=300,'Invalid PAPER result');
      cq.push(statement(db,`UPDATE jobs SET status=?,message=? WHERE id=? AND ${paperStored} AND status='pending' AND delivered_at IS NOT NULL`,item.status,item.message,item.id));
    }
    cq.push(statement(db,`SELECT id,${jobAction} AS action,substr(release_id,instr(release_id,':')+1) AS payload,expires FROM jobs WHERE status='pending' AND expires>? AND ${paperStored} ORDER BY id LIMIT 1`,now));
    const batch=await db.batch([...queries,...jq,...cq]);
    const controls=results(batch,batch.length-1).map(row=>({...row,payload:JSON.parse(row.payload)}));
    return json({ commands: results(batch, commandIndex), jobs:results(batch,queries.length+jq.length-1), paper_controls:controls, poll_seconds: 30 });
  }
  if (method === 'POST' && request.headers.get('origin') !== env.PORTAL_ORIGIN) return json({ error: 'Origin not allowed' }, 403);
  const credential=await statement(db,'SELECT version,salt,digest,iterations FROM owner_password WHERE id=1 AND bootstrap_hash=?',env.OWNER_KEY_HASH).first();
  const ownerVersion=credential?.version||env.OWNER_KEY_HASH;
  if(path==='/v1/auth-parameters'&&method==='GET')return json(credential?
    {scheme:'pbkdf2-sha256',salt:credential.salt,iterations:PASSWORD_ITERATIONS}:
    {scheme:'initial-key'});
  if (path === '/v1/login' && method === 'POST') {
    const body = await readBody(request);
    await passwordBudget(db,now);
    if (!await matchesPassword(body.password,credential,env.OWNER_KEY_HASH)) return json({ error: 'Clave incorrecta' }, 401);
    const token = randomToken(), csrf = randomToken();
    await db.batch([
      statement(db, 'DELETE FROM sessions WHERE expires<=?', now),
      statement(db, 'INSERT INTO sessions(token,csrf,owner_version,expires) VALUES(?,?,?,?)', await sha256(token), csrf, ownerVersion, now+3600),
      statement(db, 'DELETE FROM sessions WHERE token NOT IN (SELECT token FROM sessions ORDER BY expires DESC,rowid DESC LIMIT 10)'),
    ]);
    return json({ csrf }, 200, { 'Set-Cookie': sessionCookie(token) });
  }
  const token = cookie(request);
  if (!TOKEN.test(token)) return json({ error: 'Session required' }, 401);
  const session = await statement(db, 'SELECT token,csrf FROM sessions WHERE token=? AND expires>? AND owner_version=?', await sha256(token), now, ownerVersion).first();
  if (!session) return json({ error: 'Session expired' }, 401);
  if (method === 'POST' && !same(request.headers.get('x-csrf-token') || '', session.csrf)) return json({ error: 'Invalid CSRF token' }, 403);
  if(path==='/v1/password'&&method==='POST'){
    const body=await readBody(request,2048);
    assert(Object.keys(body).every(k=>['current_password','new_password','salt'].includes(k)),'Unknown field');
    assert(validPassword(body.new_password)&&TOKEN.test(body.salt||''),'Invalid password proof');
    await passwordBudget(db,now);
    if(!await matchesPassword(body.current_password,credential,env.OWNER_KEY_HASH))return json({error:'Contraseña actual incorrecta'},400);
    assert(body.new_password!==body.current_password,'Elige una contraseña diferente');
    assert(!same(await sha256(body.new_password),env.DEVICE_KEY_HASH),'Usa una contraseña distinta de las credenciales técnicas');
    assert(body.salt!==credential?.salt,'Use a new password salt');
    const version=randomToken(),salt=body.salt,digest=await passwordDigest(body.new_password,salt);
    const update=await db.batch([
      statement(db,`INSERT INTO owner_password(id,bootstrap_hash,version,salt,digest,iterations) VALUES(1,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET bootstrap_hash=excluded.bootstrap_hash,version=excluded.version,
        salt=excluded.salt,digest=excluded.digest,iterations=excluded.iterations
        WHERE owner_password.version=? OR owner_password.bootstrap_hash<>? RETURNING version`,env.OWNER_KEY_HASH,version,salt,digest,PASSWORD_ITERATIONS,ownerVersion,env.OWNER_KEY_HASH),
      statement(db,'DELETE FROM sessions WHERE owner_version=? AND EXISTS(SELECT 1 FROM owner_password WHERE version=?)',ownerVersion,version)
    ]);
    if(!results(update,0).length)return json({error:'La contraseña cambió en otra sesión; vuelve a entrar'},409);
    return json({ok:true},200,{'Set-Cookie':sessionCookie('',0)});
  }
  if(path==='/v1/futures-pause-diagnostics' && method==='GET'){
    const row=await statement(db,'SELECT payload,received_at FROM snapshots WHERE id=1').first();
    if(!row)return json({installed_version:null,killed:null,has_pause_diagnostics:false,pause_diagnostics:null,received_at:null,stale:true});
    let snapshot=null;
    try{snapshot=JSON.parse(row.payload);}catch{throw new HttpError(503,'Stored snapshot unavailable');}
    const futures=snapshot?.dashboard?.futures_forward;
    const diagnostics=futures?.pause_diagnostics;
    return json({
      installed_version:typeof snapshot?.installed_version==='string'?snapshot.installed_version:null,
      killed:typeof futures?.killed==='boolean'?futures.killed:null,
      has_pause_diagnostics:!!(diagnostics&&typeof diagnostics==='object'&&!Array.isArray(diagnostics)),
      pause_diagnostics:(diagnostics&&typeof diagnostics==='object'&&!Array.isArray(diagnostics))?diagnostics:null,
      received_at:row.received_at??null,
      stale:!row.received_at||now-row.received_at>120
    });
  }
  if(path==='/v1/updates' && method==='GET')return json(await githubUpdates(env).list());
  const historyPage=path.match(/^\/v1\/activity\/(0|[1-9][0-9]{0,1})$/);
  if(historyPage && method==='GET'){
    const page=Number(historyPage[1]);
    const rows=await statement(db,`SELECT id,kind,action,status,message,created FROM (
      SELECT id,'command' AS kind,action,
        CASE WHEN status='pending' AND expires<=? THEN 'expired' ELSE status END AS status,
        '' AS message,created FROM commands
      UNION ALL
      SELECT id,CASE WHEN ${paperStored} THEN 'paper' ELSE 'job' END AS kind,${jobAction} AS action,status,message,created FROM jobs
    ) ORDER BY created DESC,kind DESC,id DESC LIMIT 26 OFFSET ?`,now,page*25).all();
    const items=rows.results||[];
    return json({items:items.slice(0,25),next_page:items.length>25&&page<99?page+1:null,retention_days:90});
  }
  if (path === '/v1/status' && method === 'GET') {
    const batch = await db.batch([
      statement(db, 'SELECT payload,received_at FROM snapshots WHERE id=1'),
      statement(db, "SELECT id,action,CASE WHEN status='pending' AND expires<=? THEN 'expired' ELSE status END AS status,expires FROM commands ORDER BY id DESC LIMIT 20", now),
      statement(db,`SELECT id,${jobAction} AS action,status,message FROM jobs WHERE NOT ${paperStored} ORDER BY id DESC LIMIT 20`),
      statement(db,`SELECT id,${jobAction} AS action,status,message FROM jobs WHERE ${paperStored} ORDER BY id DESC LIMIT 20`),
      statement(db,`SELECT id,kind,action,status,message,created FROM (
        SELECT id,'command' AS kind,action,
          CASE WHEN status='pending' AND expires<=? THEN 'expired' ELSE status END AS status,
          '' AS message,created FROM commands
        UNION ALL
        SELECT id,CASE WHEN ${paperStored} THEN 'paper' ELSE 'job' END AS kind,${jobAction} AS action,status,message,created FROM jobs
      ) ORDER BY created DESC,kind DESC,id DESC LIMIT 3`,now),
    ]);
    const snapshot = results(batch, 0)[0];
    return json({ csrf: session.csrf, snapshot: snapshot ? JSON.parse(snapshot.payload) : null,
      received_at: snapshot?.received_at ?? null, stale: !snapshot || now-snapshot.received_at > 120,
      commands: results(batch, 1), jobs:results(batch,2), paper_controls:results(batch,3), activity:results(batch,4) });
  }
  if(path==='/v1/jobs'&&method==='POST'){
    const body=await readBody(request);
    assert(Object.keys(body).every(k=>['action','request_id','release_id'].includes(k)),'Unknown job field');
    assert(['research','update_check','update_install','update_restore'].includes(body.action)&&typeof body.request_id==='string'&&/^[A-Za-z0-9_-]{16,100}$/.test(body.request_id),'Invalid job');
    assert(['update_install','update_restore'].includes(body.action)?HASH.test(body.release_id||''):body.release_id===undefined,'Exact release or restore approval required');
    const storedAction=body.action==='update_restore'?'update_install':body.action;
    const storedRelease=body.action==='update_restore'?'restore:'+body.release_id:(body.release_id??null);
    const batch=await db.batch([
      statement(db,"UPDATE jobs SET status='expired' WHERE status='pending' AND expires<=?",now),
      statement(db,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS),
      statement(db,`INSERT INTO jobs(request_id,action,status,created,expires,release_id) SELECT ?,?,'pending',?,?,?
        WHERE EXISTS(SELECT 1 FROM snapshots WHERE received_at>=? AND
          (?!='update_install' OR (json_extract(payload,'$.bot_update.enabled')=1 AND json_extract(payload,'$.bot_update.release_id')=? AND json_extract(payload,'$.bot_update.expires')>?))
          AND (?!='update_restore' OR (json_extract(payload,'$.bot_restore.enabled')=1 AND json_extract(payload,'$.bot_restore.restore_id')=?)))
        AND NOT EXISTS(SELECT 1 FROM jobs WHERE status IN ('pending','running') OR created>?)
        ON CONFLICT(request_id) DO NOTHING`,body.request_id,storedAction,now,now+300,storedRelease,now-120,body.action,body.release_id??null,now,body.action,body.release_id??null,now-60),
      statement(db,`SELECT id,${jobAction} AS action,status,${jobRelease} AS release_id FROM jobs WHERE request_id=?`,body.request_id),
    ]);
    const job=results(batch,3)[0];
    if(!job)return json({error:'Windows no disponible, trabajo en curso o espera de un minuto'},409);
    if(job.action!==body.action||job.release_id!==(body.release_id??null))return json({error:'Idempotency conflict'},409);
    return json(job,202);
  }
  if (path === '/v1/commands' && method === 'POST') {
    const body = await readBody(request);
    assert(Object.keys(body).every(k => ['action','request_id'].includes(k)), 'Unknown field');
    assert(['kill','resume'].includes(body.action) && typeof body.request_id === 'string' && /^[A-Za-z0-9_-]{16,100}$/.test(body.request_id), 'Invalid command');
    const batch = await db.batch([
      statement(db, `INSERT INTO commands(request_id,action,expires,status,created)
        SELECT ?,?,?,'pending',? WHERE (?='kill' OR EXISTS(SELECT 1 FROM snapshots WHERE id=1 AND received_at>=?))
        ON CONFLICT(request_id) DO NOTHING`, body.request_id, body.action, now+120, now, body.action, now-120),
      statement(db, `UPDATE commands SET status='superseded' WHERE status='pending' AND id <
        (SELECT id FROM commands WHERE request_id=? AND action=?)`, body.request_id, body.action),
      statement(db, 'SELECT id,action,status,expires FROM commands WHERE request_id=?', body.request_id),
    ]);
    const command = results(batch, 2)[0];
    if (!command) return json({ error: 'Windows sin conexión reciente; reanudación bloqueada' }, 409);
    if (command.action !== body.action) return json({ error: 'Idempotency conflict' }, 409);
    return json({ id: command.id, status: command.expires<=now && command.status==='pending' ? 'expired' : command.status }, 202);
  }
  if(path==='/v1/paper-controls'&&method==='POST'){
    const body=await readBody(request,1024);
    assert(Object.keys(body).sort().join(',')==='action,payload,request_id'&&
      ['risk_profile','paper_close','ai_model','restart_engine','execution_mode','testnet_smoke','futures_testnet_check','futures_testnet_smoke','futures_testnet_reconcile','futures_forward_pause','futures_forward_resume','market_pulse_pause','market_pulse_resume'].includes(body.action)&&
      typeof body.request_id==='string'&&/^[A-Za-z0-9_-]{16,100}$/.test(body.request_id)&&object(body.payload),'Invalid PAPER request');
    if(body.action==='risk_profile'){
      assert(Object.keys(body.payload).join(',')==='profile'&&
        ['minimo','leve','prudente','moderado','alto','normal'].includes(body.payload.profile),'Invalid risk profile');
    }else if(body.action==='ai_model'){
      assert(Object.keys(body.payload).join(',')==='model'&&
        ['gpt-5.6-luna','gpt-6-luna'].includes(body.payload.model),'Invalid model selection');
    }else if(body.action==='execution_mode'){
      assert(Object.keys(body.payload).join(',')==='mode'&&['paper','testnet'].includes(body.payload.mode),'Invalid execution mode');
    }else if(['restart_engine','testnet_smoke','futures_testnet_check','futures_testnet_reconcile','futures_forward_pause','futures_forward_resume','market_pulse_pause','market_pulse_resume'].includes(body.action)){
      assert(Object.keys(body.payload).length===0,'Invalid operational request');
    }else if(body.action==='futures_testnet_smoke'){
      assert(Object.keys(body.payload).sort().join(',')==='direction,leverage'&&
        ['LONG','SHORT'].includes(body.payload.direction)&&[1,2,3].includes(body.payload.leverage),
        'Invalid Futures Testnet request');
    }else{
      const p=body.payload;
      assert(Object.keys(p).sort().join(',')==='opened_at,reference_price,symbol'&&
        typeof p.symbol==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(p.symbol)&&
        typeof p.opened_at==='string'&&p.opened_at.length>0&&p.opened_at.length<=64&&
        typeof p.reference_price==='number'&&Number.isFinite(p.reference_price)&&p.reference_price>0,
        'Invalid PAPER position');
    }
    const serialized=JSON.stringify(body.payload);
    const storedRelease=body.action+':'+serialized;
    const batch=await db.batch([
      statement(db,"UPDATE jobs SET status='expired' WHERE status='pending' AND expires<=?",now),
      statement(db,`INSERT INTO jobs(request_id,action,release_id,status,created,expires)
        SELECT ?,'research',?,'pending',?,? WHERE EXISTS(
          SELECT 1 FROM snapshots WHERE id=1 AND received_at>=? AND
          json_extract(payload,'$.paper_controls')=1 AND
          (? IN ('risk_profile','paper_close') OR json_extract(payload,'$.operations_controls')=1) AND
          (?!='paper_close' OR json_extract(payload,'$.mode') IN ('PAPER','TESTNET')) AND
          (?!='testnet_smoke' OR json_extract(payload,'$.mode')='TESTNET') AND
          (? NOT IN ('futures_testnet_check','futures_testnet_smoke','futures_testnet_reconcile','futures_forward_pause','futures_forward_resume') OR json_extract(payload,'$.mode')='TESTNET') AND
          (? NOT IN ('market_pulse_pause','market_pulse_resume') OR (json_extract(payload,'$.dashboard.market_pulse.enabled')=1 AND json_extract(payload,'$.dashboard.market_pulse.controls_available')=1 AND json_extract(payload,'$.dashboard.market_pulse.mode')='SHADOW')) AND
          (?!='paper_close' OR EXISTS(SELECT 1 FROM json_each(payload,'$.dashboard.positions')
           WHERE json_extract(value,'$.symbol')=? AND json_extract(value,'$.opened_at')=?)))
        AND NOT EXISTS(SELECT 1 FROM jobs WHERE status IN ('pending','running'))
        ON CONFLICT(request_id) DO NOTHING`,body.request_id,storedRelease,now,now+300,now-120,
          body.action,body.action,body.action,body.action,body.action,body.action,body.payload.symbol??'',body.payload.opened_at??''),
      statement(db,`SELECT id,${jobAction} AS action,release_id,status FROM jobs WHERE request_id=?`,body.request_id),
    ]);
    const row=results(batch,2)[0];
    if(!row)return json({error:'Windows no disponible, entorno incompatible o existe otra operación pendiente'},409);
    if(row.action!==body.action||row.release_id!==storedRelease)return json({error:'Idempotency conflict'},409);
    return json({id:row.id,action:row.action,status:row.status},202);
  }
  if (path === '/v1/logout' && method === 'POST') {
    await statement(db, 'DELETE FROM sessions WHERE token=?', session.token).run();
    return json({ ok: true }, 200, { 'Set-Cookie': sessionCookie('', 0) });
  }
  return json({ error: 'Not found' }, 404);
}

export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) { const known=error instanceof HttpError || error instanceof UpdateError; return json({ error: known ? error.message : 'Service temporarily unavailable' }, known ? error.status : 503); }
  },
  async scheduled(_event, env) {
    const now = Math.floor(Date.now()/1000);
    await env.DB.batch([
      statement(env.DB, 'DELETE FROM sessions WHERE expires<=?', now),
      statement(env.DB, "DELETE FROM commands WHERE created<? AND status!='pending'", now-90*86400),
      statement(env.DB, "UPDATE commands SET status='expired' WHERE status='pending' AND expires<=?", now),
      statement(env.DB,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS),
      statement(env.DB,"DELETE FROM jobs WHERE created<? AND status IN ('completed','failed','expired')",now-90*86400),
    ]);
  },
};
