/* One bounded, read-only research evidence contract for browser and Worker. */
(function(root){
  'use strict';
  const engines=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
  const names=['Spot','Futures','AI Market Pulse','Quant Arbitrage'];
  const requirements=['VERIFIED_ACCOUNT_IDENTITY_AND_STARTING_INVENTORY','FULL_ENTRY_EXIT_PARTIAL_CANCEL_AND_UNKNOWN_ORDER_RECONCILIATION','COMMON_TRANSACTIONAL_RESERVATION_PROTOCOL','APPROVED_GLOBAL_RISK_LIMITS_AND_PROTECTION_COVERAGE','RESTART_AND_SIGNED_ROLLBACK_RECOVERY','INDEPENDENT_FORWARD_AND_OUT_OF_SAMPLE_REVIEW','EXPLICIT_OWNER_AUTHORIZATION_FOR_EACH_AUTONOMY_TRANSITION'];
  const requirementNames=['Identidad de cuenta e inventario inicial','Entradas, cierres, parciales y órdenes inciertas','Protocolo común de reservas transaccionales','Límites globales y cobertura de protecciones','Reinicio y recuperación de versión firmada','Revisión forward y fuera de muestra independiente','Autorización del propietario para cada nivel'];
  const limitations=['PUBLIC_MARKET_MODELS_NOT_OPERATING_FILLS_OR_AI_FILTER_REPLAY','REPEATED_HOLDOUT_INSPECTION_IS_NOT_NEW_INDEPENDENT_EVIDENCE','UNIVERSE_AND_MODEL_SELECTION_MULTIPLICITY_REMAIN','LIQUIDATION_STRESS_NOT_CONTRACT_CALIBRATED','CONTEMPORANEOUS_HISTORICAL_NEWS_AND_TICKS_INCOMPLETE','FROZEN_SCORE_REPLAY_NOT_PORTFOLIO_OR_FILL_REPLAY','FORWARD_OBSERVATION_NOT_INDEPENDENT_OOS','TWO_LEGS_ARE_NOT_AN_ATOMIC_EXCHANGE_HEDGE','PER_LEG_FEES_SLIPPAGE_FUNDING_BASIS_AND_LEGGING_STRESS_ARE_HYPOTHESES','MODEL_REPLAY_IS_A_BOUNDED_SAMPLE_NOT_EXECUTION_OR_OOS_VALIDATION','STATISTICAL_ENTRIES_REMAIN_BLOCKED_CORRELATION_IS_INSUFFICIENT','METHODOLOGY_PRESENCE_DOES_NOT_CERTIFY_A_VALID_RESULT','NO_AUTOMATIC_PROMOTION_OR_EFFECTIVE_CONTROL','NO_LIVE_IMPLEMENTATION_OR_AUTHORIZATION'];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,list)=>object(x)&&Object.keys(x).length===list.length&&list.every(k=>Object.hasOwn(x,k));
  const count=x=>Number.isSafeInteger(x)&&x>=0&&x<=1e9;
  const stamp=x=>typeof x==='string'&&x.length<=40&&/T.+(?:Z|[+-]\d{2}:\d{2})$/.test(x)&&Number.isFinite(Date.parse(x));
  const before=(x,cutoff)=>x===null||stamp(x)&&Date.parse(x)<=Date.parse(cutoff);
  const strings=x=>Array.isArray(x)&&x.length<=5&&new Set(x).size===x.length&&x.every(v=>limitations.includes(v));
  function valid(value){
    try{
      if(!keys(value,['schema','mode','autonomy_level','captured_at','source_generated_at','freshness','state','execution_enabled','controls_enabled','reservations_enabled','promotion_allowed','engines','comparison','control_preconditions','limitations'])
        ||value.schema!==1||value.mode!=='SHADOW'||value.autonomy_level!==0
        ||!['execution_enabled','controls_enabled','reservations_enabled','promotion_allowed'].every(k=>value[k]===false)
        ||!stamp(value.captured_at)||!before(value.source_generated_at,value.captured_at)
        ||value.freshness!=='ARCHIVED_RESEARCH_NOT_ENGINE_HEARTBEAT'||!['EVIDENCE_PARTIAL','NOT_REPORTED'].includes(value.state)
        ||(value.state==='NOT_REPORTED')!==(value.source_generated_at===null)
        ||!Array.isArray(value.engines)||value.engines.length!==4||!strings(value.limitations)
        ||JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>12000)return false;
      for(const [i,row] of value.engines.entries()){
        if(!keys(row,['engine','evidence_environment','state','evidence_at','strategies_or_assets','operating_signal_reference','execution_validated','operational_profitability_evaluated','walk_forward','reserved_holdout','cost_stress','forward_state','replay','attribution','limitations'])
          ||row.engine!==engines[i]||row.evidence_environment!==(i<2?'PUBLIC_MARKET_RESEARCH':'SHADOW')
          ||!(i<2?['EXPLORATORY_RESEARCH_PRESENT','NOT_REPORTED']:i===2?['FORWARD_SHADOW_ONLY','NOT_REPORTED']:['NOT_STARTED','AVAILABLE','PARTIAL','UNAVAILABLE','NOT_REPORTED']).includes(row.state)
          ||!before(row.evidence_at,value.source_generated_at||value.captured_at)||!(row.strategies_or_assets===null||count(row.strategies_or_assets)&&row.strategies_or_assets<=30)
          ||!['SIGNAL_PARITY_ONLY','NOT_REPORTED','NOT_APPLICABLE'].includes(row.operating_signal_reference)
          ||row.execution_validated!==false||row.operational_profitability_evaluated!==false
          ||!['walk_forward','reserved_holdout'].every(k=>['NOT_REPORTED','METHODOLOGY_PRESENT_NOT_EXECUTION_VALIDATED'].includes(row[k]))
          ||!['NOT_REPORTED','METHODOLOGY_PRESENT_NOT_EXECUTION_VALIDATED','SIMULATION_HYPOTHESES_NOT_EXECUTION_VALIDATED'].includes(row.cost_stress)
          ||!['OBSERVING','WAITING_NEW_DATA','DATA_UNAVAILABLE','HISTORY_GAP','NOT_REPORTED','OBSERVED_JOURNAL'].includes(row.forward_state)
          ||!strings(row.limitations))return false;
        const a=row.attribution;
        if(!keys(a,['individual_ai','guardian','estimated_pnl_without_ai','estimated_losses_avoided','causal_claim_allowed'])
          ||a.individual_ai!=='NOT_EVALUABLE_NO_MATCHED_COUNTERFACTUAL_COHORT'||a.guardian!=='NOT_EVALUABLE_LEVEL_0_NO_CONTROL_COHORT'
          ||a.estimated_pnl_without_ai!==null||a.estimated_losses_avoided!==null||a.causal_claim_allowed!==false)return false;
        const replay=row.replay;
        if(i<2&&replay!==null)return false;
        // Pulse counts invalid timestamps and rule versions before incrementing
        // checked. These counters are independent, bounded by its 1000-row sample.
        if(i===2&&replay!==null&&(!keys(replay,['checked','mismatches','invalid_timestamps'])||!Object.values(replay).every(x=>count(x)&&x<=1000)))return false;
        if(i===3&&replay!==null&&(!keys(replay,['checked','matches','mismatches','unavailable','sampled'])||!Object.values(replay).every(x=>count(x)&&x<=16)||replay.checked!==replay.matches+replay.mismatches||replay.sampled!==replay.checked+replay.unavailable))return false;
      }
      const c=value.comparison;
      return keys(c,['state','aggregate_capital','best_strategy','reason'])&&c.state==='NOT_COMPARABLE_NO_MATCHED_EXECUTION_COHORT'&&c.aggregate_capital===null&&c.best_strategy===null&&c.reason==='ENVIRONMENTS_PERIODS_METHODS_AND_EXECUTION_EVIDENCE_DIFFER'
        &&Array.isArray(value.control_preconditions)&&value.control_preconditions.length===7&&value.control_preconditions.every((row,i)=>keys(row,['id','state'])&&row.id===requirements[i]&&row.state===(i===6?'SEPARATE_AUTHORIZATION_REQUIRED':'NOT_CERTIFIED_BY_THIS_REPORT'));
    }catch{return false;}
  }
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=x=>x===null?'Sin fecha disponible':new Date(x).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'});
  const label=x=>({NOT_REPORTED:'Sin evidencia incluida',METHODOLOGY_PRESENT_NOT_EXECUTION_VALIDATED:'Metodología presente; ejecución sin validar',SIMULATION_HYPOTHESES_NOT_EXECUTION_VALIDATED:'Hipótesis de simulación; ejecución sin validar',SIGNAL_PARITY_ONLY:'Coincidencia de señales; no rentabilidad ejecutada',NOT_APPLICABLE:'No corresponde',EXPLORATORY_RESEARCH_PRESENT:'Investigación exploratoria',FORWARD_SHADOW_ONLY:'Observación Shadow',NOT_STARTED:'Sin registros',AVAILABLE:'Evidencia disponible',PARTIAL:'Evidencia parcial',UNAVAILABLE:'Evidencia no disponible',OBSERVING:'Cohorte en observación',WAITING_NEW_DATA:'Esperando datos posteriores',DATA_UNAVAILABLE:'Datos no disponibles',HISTORY_GAP:'Historial con huecos',OBSERVED_JOURNAL:'Journal observado'})[x]||'Sin evidencia';
  function render(value){
    const set=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.textContent=text;};
    const html=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.innerHTML=text;};
    if(!valid(value)){
      set('researchValidationState',value?'MATRIZ NO COMPATIBLE':'SIN MATRIZ ARCHIVADA');
      set('researchValidationNote','El próximo estudio podrá adjuntar esta matriz. La ausencia de informe no implica que los motores estén detenidos.');
      html('researchValidationEngines','');html('researchControlReadiness','');return;
    }
    set('researchValidationState','EVIDENCIA PARCIAL · SOLO LECTURA');
    set('researchValidationNote',`Estudio archivado ${date(value.source_generated_at)} · matriz ${date(value.captured_at)}. Estas fechas no son un heartbeat. Los períodos, entornos y métodos no permiten clasificar un motor como ganador.`);
    html('researchValidationEngines',value.engines.map((row,i)=>{
      const fields=[['Evidencia',label(row.state)],['Entorno del estudio',i<2?'Mercado público · modelo de investigación':'SHADOW · ledger hipotético'],['Corte de evidencia',date(row.evidence_at)],['Walk-forward',label(row.walk_forward)],['Ventana reservada',label(row.reserved_holdout)],['Costes bajo estrés',label(row.cost_stress)],['Observación posterior',label(row.forward_state)]];
      const r=row.replay;
      if(r)fields.push(['Replay numérico',`${r.checked} comprobados · ${r.mismatches} divergencias${i===3?' · '+r.unavailable+' no disponibles en muestra de '+r.sampled:' · '+r.invalid_timestamps+' tiempos inválidos'}`]);
      return `<article class="guardian-scope"><h3>${names[i]}</h3><dl>${fields.map(([a,b])=>`<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join('')}</dl><p class="platform-note">Ejecución y rentabilidad operativa sin validar. Un replay coincidente verifica el cálculo; no demuestra ventaja fuera de muestra.</p></article>`;
    }).join(''));
    html('researchControlReadiness',`<p class="platform-note">Efecto atribuible a IA o Guardian: desconocido. Pérdidas evitadas y resultado sin IA no evaluables sin cohortes comparables. No se suman capitales de los entornos.</p>${value.control_preconditions.map((row,i)=>`<p class="settings-help">${esc(requirementNames[i])}: <strong>${i===6?'autorización separada requerida':'no certificado por este informe'}</strong>.</p>`).join('')}`);
  }
  root.CryptoResearchValidation=Object.freeze({valid,render});
})(globalThis);
