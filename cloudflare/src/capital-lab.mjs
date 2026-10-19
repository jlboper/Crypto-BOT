// Closed synthetic protocol evidence. Grants no account or trading capability.
const obj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const sim=v=>typeof v==='string'&&/^SIM_[A-Za-z0-9_-]{1,80}$/.test(v);
const run=v=>typeof v==='string'&&/^SIM_[a-f0-9]{32}$/.test(v);
const money=v=>Number.isSafeInteger(v)&&Math.abs(v)<=9000000000000000;
const stamp=v=>typeof v==='string'&&v.length<=40&&/T.+(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
const equal=(a,b)=>typeof a===typeof b&&a===b;
const U=1000000;
const bookKeys=['book_equity_units','reserved_units','committed_units','free_units_signed','available_units','shortfall_units','fees_paid_units','realized_pnl_units'];
const recipes=[
 ['SIM_ATOMIC_PAIR','Reserva atómica de dos patas','RESERVED',[["TWO_LEGS_ATOMIC",204*U],["TWO_LEGS_PRESENT",2]],[1000*U,204*U,0,796*U,796*U,0,0,0]],
 ['SIM_ACCOUNT_CONFLICT','Conflicto de activo en una cuenta simulada','RESERVED',[["SAME_ACCOUNT_ASSET_REJECTED","ACCOUNT_ASSET_ALREADY_RESERVED"],["ONE_RESERVATION",102*U]],[1000*U,102*U,0,898*U,898*U,0,0,0]],
 ['SIM_CONCURRENT_BUDGET','Dos participantes compiten por el mismo presupuesto','RESERVED',[["ONE_PARENT_BUDGET_WINNER",1],["NO_DOUBLE_ALLOCATION",402*U]],[1000*U,402*U,0,598*U,598*U,0,0,0]],
 ['SIM_RESTART_UNKNOWN_TTL','Reinicio y TTL conservan una intención incierta','UNKNOWN',[["TTL_RELEASES_NOTHING",102*U],["INTENTION_UNKNOWN","UNKNOWN"]],[1000*U,102*U,0,898*U,898*U,0,0,0]],
 ['SIM_PARTIAL_CANCEL','Cancelación parcial conserva principal y costes','RECOVERY_REQUIRED',[["ONLY_UNUSED_PRINCIPAL_RELEASED",60*U],["OPEN_COMMITMENT_PRESERVED",40*U],["EXIT_COST_BUFFER_RETAINED",1600000]],[999600000,1600000,40*U,958*U,958*U,0,400000,0]],
 ['SIM_MULTILEG_UNWIND','Fallo de una pata exige cierre simulado explícito','CLOSED',[["RESIDUAL_REQUIRES_UNWIND",100*U],["EXPLICIT_CLOSE_RELEASES_CAPITAL",0],["BOTH_COSTS_BOOKED",1500000]],[998*U,0,0,998*U,998*U,0,1500000,-500000]],
 ['SIM_LOSS_SHORTFALL','Fees y pérdida confirmada no ocultan déficit','RECOVERY_REQUIRED',[["NEGATIVE_EQUITY_NOT_HIDDEN",-204*U],["SHORTFALL_VISIBLE",204*U]],[-204*U,0,0,-204*U,0,204*U,4*U,-1200*U]],
];
const limitations=['SYNTHETIC_PROTOCOL_SCENARIOS_ONLY','NO_EXISTING_FUNDS_OR_ACCOUNT_READ','NO_ENGINE_CANDIDATE_OR_ORDER_HOOK','NOT_OWNER_FINANCIAL_AUTHORIZATION','BOOK_CAPITAL_NOT_MARKET_EQUITY_OR_GROSS_NOTIONAL','SCENARIO_VALIDATION_NOT_JOURNAL_REPLAY','NO_STATISTICAL_EDGE_OR_PROMOTION'];
const topKeys=['schema','engine','mode','synthetic','execution_enabled','autonomy_level','real_account_adapter','state','at','report_id','report_digest','source_version','policy_id','policy','unit','units_per_usdt','scenarios','limitations'];
function validPolicy(p){
  const expected={policy_id:'SIM_CAPITAL_LAB_POLICY_V1',approved_actor:'SIM_RECIPE_AUTHOR',approved_at:1792281600,
    funding_source:'EXPLICIT_NEW_SIMULATION_COHORT',initial_balance_units:1000*U,total_allocated_limit_units:600*U,
    reserved_limit_units:600*U,committed_limit_units:600*U,stop_risk_limit_units:20*U,
    strategy_limits:[['SIM_SPOT',600*U,20*U],['SIM_PULSE',600*U,20*U]],balance_max_age_seconds:120,max_active_requests:10};
  return exact(p,Object.keys(expected))&&Object.entries(expected).every(([k,v])=>k==='strategy_limits'
    ?JSON.stringify(p[k])===JSON.stringify(v):equal(p[k],v));
}
function conserved(b){
  if(!exact(b,bookKeys)||!Object.values(b).every(money)
    ||['reserved_units','committed_units','available_units','shortfall_units','fees_paid_units'].some(k=>b[k]<0))return false;
  const n=k=>BigInt(b[k]);
  return n('book_equity_units')===1000000000n+n('realized_pnl_units')-n('fees_paid_units')
    &&n('book_equity_units')===n('free_units_signed')+n('reserved_units')+n('committed_units')
    &&b.available_units===Math.max(0,b.free_units_signed)&&b.shortfall_units===Math.max(0,-b.free_units_signed);
}
function validScenario(s,recipe){
  const [id,label,expected,checks,book]=recipe;
  if(!exact(s,['id','label','scope','state','actual_state','expected_state','matches','conservation_matches','book','checks','record_id','record_digest'])
    ||s.id!==id||s.label!==label||s.expected_state!==expected||!['PASSED','FAILED'].includes(s.state)
    ||!['RESERVED','SUBMITTING','PARTIAL','FILLED','UNKNOWN','CANCEL_PENDING','CANCELLED','CLOSED','RECOVERY_REQUIRED','SCENARIO_ERROR'].includes(s.actual_state)
    ||typeof s.matches!=='boolean'||typeof s.conservation_matches!=='boolean'
    ||!exact(s.scope,['scenario_environment','simulated_account_id','currency'])||s.scope.scenario_environment!=='SHADOW'
    ||s.scope.simulated_account_id!==id||s.scope.currency!=='USDT'
    ||!Array.isArray(s.checks)||s.checks.length!==checks.length)return false;
  if(!s.checks.every((c,i)=>exact(c,['code','actual','expected','matches'])&&c.code===checks[i][0]&&equal(c.expected,checks[i][1])
    &&(['string','boolean'].includes(typeof c.actual)||money(c.actual))&&String(c.actual).length<=100
    &&typeof c.matches==='boolean'&&c.matches===equal(c.actual,c.expected)))return false;
  if(s.book!==null&&!conserved(s.book)||s.conservation_matches!==conserved(s.book))return false;
  const matches=s.actual_state===expected&&s.checks.every(c=>c.matches)&&s.book!==null&&bookKeys.every((k,i)=>s.book[k]===book[i]);
  if(s.matches!==matches||(s.state==='PASSED')!==(matches&&s.conservation_matches))return false;
  return s.book===null?s.actual_state==='SCENARIO_ERROR'&&s.record_id===null&&s.record_digest===null
    :sim(s.record_id)&&hash(s.record_digest);
}
export function validCapitalLab(v){
  try{
    if(!exact(v,topKeys)||v.schema!==1||v.engine!=='CAPITAL_PROTOCOL_LAB'||v.mode!=='RESEARCH_ONLY'
      ||v.synthetic!==true||v.execution_enabled!==false||v.autonomy_level!==0||v.real_account_adapter!==false
      ||!stamp(v.at)||v.unit!=='MICRO_USDT'||v.units_per_usdt!==U||v.policy_id!=='SIM_CAPITAL_LAB_POLICY_V1'
      ||JSON.stringify(v.limitations)!==JSON.stringify(limitations)
      ||JSON.stringify(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>8000)return false;
    if(['NOT_RUN','UNAVAILABLE'].includes(v.state))return v.report_id===null&&v.report_digest===null&&v.source_version===null
      &&v.policy===null&&Array.isArray(v.scenarios)&&v.scenarios.length===0;
    if(!['PASSED','FAILED'].includes(v.state)||!run(v.report_id)||!hash(v.report_digest)||!validPolicy(v.policy))return false;
    const source=v.source_version;
    return exact(source,['protocol','protocol_sha256','lab_sha256','recipe_version','recipe_sha256'])
      &&source.protocol==='CAPITAL_MANAGER_SHADOW_SIMULATION_V1'&&source.recipe_version==='capital-protocol-lab-v1'
      &&source.recipe_sha256==='794994c2035a4813c6985970d04ef2d1d308565af752acf74e546157de7aacc4'
      &&['protocol_sha256','lab_sha256','recipe_sha256'].every(k=>hash(source[k]))
      &&Array.isArray(v.scenarios)&&v.scenarios.length===recipes.length&&v.scenarios.every((s,i)=>validScenario(s,recipes[i]))
      &&(v.state==='PASSED')===v.scenarios.every(s=>s.state==='PASSED');
  }catch{return false;}
}
