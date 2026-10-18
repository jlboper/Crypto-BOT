// Optional SHADOW observation; this validator grants no execution capability.
const engines=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
const flags=['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'];
const obj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const text=(v,n=120)=>typeof v==='string'&&v.length<=n;
const code=v=>typeof v==='string'&&/^[A-Z][A-Z0-9_]{0,100}$/.test(v);
const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const stamp=v=>v===null||(text(v,40)&&/T.+(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v)));
const num=v=>v===null||typeof v==='number'&&Number.isFinite(v);
const nonneg=v=>num(v)&&(v===null||v>=0);
const count=v=>Number.isSafeInteger(v)&&v>=0;
const maybeCount=v=>v===null||count(v);
const codes=(v,max)=>Array.isArray(v)&&v.length<=max&&v.every(code);
const authority=v=>obj(v)&&v.schema===1&&v.engine==='GUARDIAN_INTELLIGENCE'&&v.mode==='SHADOW'&&v.autonomy_level===0&&flags.every(k=>v[k]===false);
const states=['NORMAL','CAUTION','RISK_REDUCED','ENTRY_HALTED','RECOVERY_REQUIRED'];
const regimes=['BULLISH','BEARISH','SIDEWAYS','HIGH_VOLATILITY','LIQUIDITY_STRESS','INSUFFICIENT_DATA'];
const method='BTC_SPOT_CLOSED_1M_60M_DESCRIPTIVE_PROXY';
const scopeKeys=['id','source_id','environment','risk_state','assessment','authoritative','reasons','source_at','available_at','captured_at','inventory_complete','data_state','position_count','current_caps','observed_gross_usdt','allocation','reported_engine_state','liveness','latest_original_review','evidence_id'];
const reportKeys=['schema','engine','mode','autonomy_level',...flags,'assessment_id','policy','at','captured_at','cutoff_at','state','regime','scopes','conflicts','correlation','counterfactual','evidence','limitations','truncation'];
function validReport(r){
  if(!authority(r)||!exact(r,reportKeys)||!hash(r.assessment_id)||!['OBSERVING','PARTIAL'].includes(r.state)
    ||!['at','captured_at','cutoff_at'].every(k=>stamp(r[k])&&r[k]!==null))return false;
  const p=r.policy;
  if(!exact(p,['id','calibrated','regime_method','window_minutes','minimum_closed_bars','maximum_bar_age_seconds','direction_return_pct','high_realized_volatility_pct','liquidity_max_spread_bps','liquidity_min_partial_depth_usdt','liquidity_drop_pct','source_maximum_age_seconds'])
    ||p.id!=='guardian-intelligence-shadow-v1'||p.calibrated!==false||p.regime_method!==method
    ||p.window_minutes!==60||p.minimum_closed_bars!==61||p.maximum_bar_age_seconds!==90
    ||p.direction_return_pct!==1||p.high_realized_volatility_pct!==1.5||p.liquidity_max_spread_bps!==20
    ||p.liquidity_min_partial_depth_usdt!==10000||p.liquidity_drop_pct!==-50
    ||!exact(p.source_maximum_age_seconds,engines)||engines.some((id,i)=>p.source_maximum_age_seconds[id]!==[600,600,30,90][i]))return false;
  const g=r.regime;
  if(!exact(g,['state','method','window_minutes','observation_count','return_pct','realized_volatility_pct','first_market_at','last_market_at','latest_available_at','evidence_cutoff','reason','liquidity'])
    ||!regimes.includes(g.state)||g.method!==method||g.window_minutes!==60||!count(g.observation_count)||g.observation_count>61
    ||!num(g.return_pct)||!nonneg(g.realized_volatility_pct)||!code(g.reason)
    ||!['first_market_at','last_market_at','latest_available_at','evidence_cutoff'].every(k=>stamp(g[k])))return false;
  const l=g.liquidity;
  if(!exact(l,['state','at','spread_bps','partial_depth_usdt','liquidity_change_pct'])||!['UNKNOWN','OBSERVED','STRESS'].includes(l.state)
    ||!stamp(l.at)||!nonneg(l.spread_bps)||!nonneg(l.partial_depth_usdt)||!num(l.liquidity_change_pct))return false;
  if(!Array.isArray(r.scopes)||r.scopes.length!==4||new Set(r.scopes.map(s=>s?.id)).size!==4||!r.scopes.every(s=>{
    const review=s.latest_original_review;
    return exact(s,scopeKeys)&&engines.includes(s.id)&&s.source_id===['spot','futures','pulse','quant'][engines.indexOf(s.id)]
      &&['SPOT_TESTNET','FUTURES_DEMO','PAPER','SHADOW','UNKNOWN'].includes(s.environment)&&states.includes(s.risk_state)
      &&s.assessment==='WOULD_REVIEW'&&s.authoritative===false&&codes(s.reasons,30)
      &&['source_at','available_at','captured_at'].every(k=>stamp(s[k]))&&typeof s.inventory_complete==='boolean'
      &&['FRESH','UNKNOWN'].includes(s.data_state)&&maybeCount(s.position_count)&&nonneg(s.observed_gross_usdt)
      &&exact(s.current_caps,['gross_usdt','stop_risk_usdt'])&&Object.values(s.current_caps).every(nonneg)
      &&['KEEP_UNASSIGNED','REVIEW_PROTECTION_AND_RECONCILIATION','REVIEW_CURRENT_BUDGET_EXCESS','REVIEW_EXISTING_PAUSE','REVIEW_NO_OBSERVED_GROSS_HEADROOM'].includes(s.allocation)
      &&(s.reported_engine_state===null||['RUNNING','PAUSED','WAITING','STOPPED','NOT_STARTED','DEGRADED','SHADOW'].includes(s.reported_engine_state))
      &&s.liveness==='NOT_ASSERTED_BY_DATA_AGE'&&hash(s.evidence_id)
      &&exact(review,['state','id','at','verdict','confidence','model'])
      &&['NOT_APPLICABLE_OR_NOT_PROJECTED','UNAVAILABLE','OBSERVED_METADATA_ONLY'].includes(review.state)
      &&(review.id===null||text(review.id,100))&&stamp(review.at)
      &&(review.verdict===null||(s.id==='SPOT'?['ALLOW','REJECT','REDUCE']:['ALLOW','REJECT']).includes(review.verdict))
      &&num(review.confidence)&&(review.confidence===null||review.confidence>=0&&review.confidence<=1)
      &&(review.model===null||text(review.model,100));
  }))return false;
  if(!Array.isArray(r.conflicts)||r.conflicts.length>10||!r.conflicts.every(c=>exact(c,['symbol','members','classification','hedge_verified','allocation_action'])
    &&/^[A-Z0-9]{2,24}USDT$/.test(c.symbol)&&['OPPOSING_CROSS_SCOPE_OBSERVATION','SAME_ASSET_CROSS_SCOPE_OBSERVATION'].includes(c.classification)
    &&c.hedge_verified===false&&c.allocation_action==='REVIEW_CROSS_SCOPE_OVERLAP'&&Array.isArray(c.members)&&c.members.length>=2&&c.members.length<=8
    &&c.members.every(m=>exact(m,['engine','direction'])&&engines.includes(m.engine)&&['LONG','SHORT','UNKNOWN'].includes(m.direction))))return false;
  return exact(r.correlation,['state','reason'])&&r.correlation.state==='UNKNOWN'&&code(r.correlation.reason)
    &&exact(r.counterfactual,['state','losses_avoided','without_ai_pnl','reason'])&&r.counterfactual.state==='UNKNOWN'
    &&r.counterfactual.losses_avoided===null&&r.counterfactual.without_ai_pnl===null&&code(r.counterfactual.reason)
    &&exact(r.evidence,['source_digest','source_ids','original_decision_completeness','input_valid'])&&hash(r.evidence.source_digest)
    &&JSON.stringify(r.evidence.source_ids)===JSON.stringify(['spot','futures','pulse','quant'])
    &&r.evidence.original_decision_completeness==='NOT_PRE_SUBMIT_COMPLETE'&&typeof r.evidence.input_valid==='boolean'
    &&codes(r.limitations,20)&&exact(r.truncation,['conflicts_omitted'])&&count(r.truncation.conflicts_omitted);
}
function validAI(ai){
  if(ai===null)return true;
  if(!obj(ai)||ai.advisory_only!==true||ai.execution_enabled!==false||ai.controls_enabled!==false)return false;
  if(ai.state==='UNAVAILABLE')return exact(ai,['state','reason','advisory_only','execution_enabled','controls_enabled'])&&text(ai.reason,100);
  const keys=['state','at','assessment_id','model','advisory_only','execution_enabled','controls_enabled','commentary','usage'];
  if(ai.state==='CACHED_HISTORICAL')keys.push('cache_age_seconds');
  if(!['COMPLETED','CACHED_HISTORICAL'].includes(ai.state)||!exact(ai,keys)||!stamp(ai.at)||ai.at===null||!hash(ai.assessment_id)
    ||ai.model!=='gpt-6-luna'||(ai.state==='CACHED_HISTORICAL'&&(!nonneg(ai.cache_age_seconds)||ai.cache_age_seconds===null||ai.cache_age_seconds>900)))return false;
  const c=ai.commentary,u=ai.usage;
  return exact(c,['summary','posture','cautions','evidence_ids'])&&text(c.summary,280)&&c.summary.length>0
    &&['OBSERVE','REVIEW_DATA','REVIEW_CONCENTRATION','REVIEW_PROTECTION'].includes(c.posture)
    &&Array.isArray(c.cautions)&&c.cautions.length<=4&&c.cautions.every(v=>text(v,120))
    &&Array.isArray(c.evidence_ids)&&c.evidence_ids.length>=1&&c.evidence_ids.length<=4&&c.evidence_ids.every(id=>id===ai.assessment_id)
    &&exact(u,['input_tokens','output_tokens','cached_tokens','estimated_cost_usd','pricing_verified_at'])
    &&['input_tokens','output_tokens','cached_tokens'].every(k=>maybeCount(u[k])&&(u[k]===null||u[k]<=100000))
    &&(u.cached_tokens===null||u.input_tokens!==null&&u.cached_tokens<=u.input_tokens)
    &&nonneg(u.estimated_cost_usd)&&(u.estimated_cost_usd===null||u.estimated_cost_usd<=1)&&u.pricing_verified_at==='2026-10-18';
}
export function validGuardianIntelligence(v){
  try{
    if(!authority(v)||!exact(v,['schema','engine','mode','autonomy_level',...flags,'state','at','updated_at','freshness','report','ai','health','journal'])
      ||!['NOT_STARTED','INITIALIZED','OBSERVING','PARTIAL','DEGRADED','RETENTION_FULL','STALE','STOPPED'].includes(v.state)
      ||!stamp(v.at)||v.at===null||!stamp(v.updated_at)||!exact(v.freshness,['state','age_seconds'])
      ||!['FRESH','STALE','UNAVAILABLE'].includes(v.freshness.state)||!nonneg(v.freshness.age_seconds)
      ||v.report!==null&&!validReport(v.report)||!validAI(v.ai))return false;
    const h=v.health;
    if(!exact(h,['last_error','errors','heartbeat_at','lease_state','lease_expires_at','records','compressed_corpus_bytes','max_records','max_corpus_bytes','capacity_state','capacity_fraction','ai_calls_today','ai_daily_limit'])
      ||!(h.last_error===null||code(h.last_error))||!maybeCount(h.errors)||!stamp(h.heartbeat_at)||!stamp(h.lease_expires_at)
      ||!['UNKNOWN','OWNED','EXPIRED','RELEASED','NONE','UNAVAILABLE','ACTIVE','STOPPED','HELD','STALE'].includes(h.lease_state)
      ||!['records','compressed_corpus_bytes','max_records','max_corpus_bytes','ai_calls_today','ai_daily_limit'].every(k=>maybeCount(h[k]))
      ||['ai_calls_today','ai_daily_limit'].some(k=>h[k]!==null&&h[k]>2)
      ||!['UNKNOWN','AVAILABLE','WARNING','FULL','NORMAL','NEAR_CAPACITY','RETENTION_FULL'].includes(h.capacity_state)
      ||!nonneg(h.capacity_fraction)||h.capacity_fraction!==null&&h.capacity_fraction>1)return false;
    if(!Array.isArray(v.journal)||v.journal.length>3||!v.journal.every(j=>exact(j,['id','cutoff_at','committed_at','report_digest'])
      &&hash(j.id)&&stamp(j.cutoff_at)&&stamp(j.committed_at)&&hash(j.report_digest)))return false;
    // Python producer serializes escaped ASCII; use the same byte budget here.
    return JSON.stringify(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length<=12000;
  }catch{return false;}
}
