/* Shared, bounded evidence for a future migration. No admission or execution. */
(function(root){
  'use strict';
  const ids=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
  const names=['Spot','Futures','AI Market Pulse','Quant Arbitrage'];
  const globalCodes=['OWNER_POLICY_INCOMPLETE','OWNER_LIVE_AUTHORIZATION_REQUIRED','VERIFIED_ACCOUNT_IDENTITY_MISSING','COMPLETE_EXCHANGE_INVENTORY_MISSING','ACCOUNT_BASELINE_AND_CASHFLOWS_MISSING','COMMON_CAPITAL_PROTOCOL_NOT_INTEGRATED','PERSISTENT_GLOBAL_RISK_NOT_INTEGRATED','RECOVERY_AND_DISCONNECT_VALIDATION_REQUIRED','FROZEN_COHORT_AND_QUALIFIED_DAYS_MISSING','INDEPENDENT_OOS_EVIDENCE_MISSING'];
  const globalNames=['Política del propietario por definir','Autorización LIVE específica pendiente','Identidad de cuenta sin verificar','Inventario de órdenes y posiciones sin completar','Capital inicial y movimientos de fondos sin conciliar','Reservas compartidas sin integrar','Riesgo global persistente sin integrar','Reinicio, desconexión y recuperación por validar','Cohorte homogénea y días válidos sin certificar','Prueba independiente fuera de muestra pendiente'];
  const engineNames={QUALIFIED_OBSERVATION_UNKNOWN:'Días válidos sin certificar',OBSERVATION_SPAN_UNKNOWN:'Intervalo de observación desconocido',OBSERVATION_SPAN_INSUFFICIENT:'Intervalo registrado inferior a 30 días',SOURCE_STALE:'Fuente atrasada',SOURCE_UNKNOWN:'Frescura de fuente desconocida',NATIVE_PROTECTION_UNCONFIRMED:'Protección nativa sin confirmar',NATIVE_PROTECTION_UNKNOWN:'Cobertura de protección desconocida',ENGINE_BUDGET_EXCEEDED:'Riesgo observado supera el presupuesto nativo',ENGINE_BUDGET_UNKNOWN:'Presupuesto no verificado por esta evaluación',SHADOW_PROMOTION_NOT_AUTHORIZED:'Promoción desde Shadow sin autorizar'};
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,list)=>object(x)&&Object.keys(x).length===list.length&&list.every(k=>Object.hasOwn(x,k));
  const same=(a,b)=>Array.isArray(a)&&a.length===b.length&&a.every((x,i)=>x===b[i]);
  const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(x)&&Number.isFinite(Date.parse(x))&&new Date(x).toISOString()===x;
  const units=x=>{const [whole,fraction='']=x.split('.');return BigInt(whole)*1000000000000n+BigInt(fraction.padEnd(12,'0'));};
  function decimal(x,places,maximum,positive=false){
    if(typeof x!=='string'||x.length>26||!/^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/.test(x))return false;
    const fraction=x.split('.')[1]||'';
    return fraction.length<=places&&units(x)<=units(maximum)&&(!positive||units(x)>0n);
  }
  function expectedBlockers(row,i){
    const result=['QUALIFIED_OBSERVATION_UNKNOWN'];
    if(row.span_gate!=='SPAN_ONLY')result.push(row.reported_span_days===null?'OBSERVATION_SPAN_UNKNOWN':'OBSERVATION_SPAN_INSUFFICIENT');
    if(row.freshness!=='FRESH')result.push(row.freshness==='STALE'?'SOURCE_STALE':'SOURCE_UNKNOWN');
    if(['UNKNOWN','UNCONFIRMED'].includes(row.protection))result.push(row.protection==='UNKNOWN'?'NATIVE_PROTECTION_UNKNOWN':'NATIVE_PROTECTION_UNCONFIRMED');
    if(row.budget.state!=='WITHIN_OBSERVED_LIMIT')result.push(row.budget.state==='EXCEEDED'?'ENGINE_BUDGET_EXCEEDED':'ENGINE_BUDGET_UNKNOWN');
    if(i>=2)result.push('SHADOW_PROMOTION_NOT_AUTHORIZED');
    return result;
  }
  function valid(value){
    try{
      if(!keys(value,['schema','engine','mode','at','state','autonomy_level','controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed','observation_days_required','automatic_activation','capital_proposal','blockers','engines'])
        ||value.schema!==1||value.engine!=='LIVE_PREPARATION'||value.mode!=='READ_ONLY'||value.state!=='BLOCKED'||value.autonomy_level!==0||value.observation_days_required!==30
        ||!['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed','automatic_activation'].every(k=>value[k]===false)
        ||!stamp(value.at)||!same(value.blockers,globalCodes)||!Array.isArray(value.engines)||value.engines.length!==4
        ||JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>8000)return false;
      const p=value.capital_proposal;
      if(!keys(p,['amount_usd','status','daily_loss_limit_usd','max_drawdown_pct'])||p.daily_loss_limit_usd!==null||p.max_drawdown_pct!==null
        ||!(p.status==='NOT_PROVIDED'&&p.amount_usd===null||p.status==='PROPOSED_NOT_ALLOCATED'&&decimal(p.amount_usd,2,'1000000000',true)))return false;
      for(const [i,row] of value.engines.entries()){
        if(!keys(row,['id','environment','state','reported_span_days','span_gate','qualified_days','qualified_state','freshness','protection','budget','blockers'])
          ||row.id!==ids[i]||row.state!=='BLOCKED'||row.qualified_days!==null||row.qualified_state!=='UNKNOWN'
          ||!(i===0?['SPOT_TESTNET','PAPER','UNKNOWN']:i===1?['FUTURES_DEMO']:['SHADOW']).includes(row.environment)
          ||!(row.reported_span_days===null||typeof row.reported_span_days==='number'&&Number.isFinite(row.reported_span_days)&&row.reported_span_days>=0&&row.reported_span_days<=36500)
          ||row.span_gate!==(row.reported_span_days===null?'UNKNOWN':row.reported_span_days>=30?'SPAN_ONLY':'BELOW_30_DAYS')
          ||!['FRESH','STALE','UNKNOWN'].includes(row.freshness)||!['ARMED','UNCONFIRMED','NOT_APPLICABLE','UNKNOWN'].includes(row.protection)
          ||((i>=2||row.environment==='PAPER')&&row.protection!=='NOT_APPLICABLE'))return false;
        const b=row.budget;
        if(!keys(b,['state','inclusive_stop_risk_usdt','stop_risk_limit_usdt','at']))return false;
        if(b.state==='UNKNOWN'){
          if(b.inclusive_stop_risk_usdt!==null||b.stop_risk_limit_usdt!==null||b.at!==null)return false;
        }else if(i!==1||!['EXCEEDED','WITHIN_OBSERVED_LIMIT'].includes(b.state)
          ||!decimal(b.inclusive_stop_risk_usdt,12,'1000000000000')||!decimal(b.stop_risk_limit_usdt,12,'1000000000000',true)
          ||!stamp(b.at)||Date.parse(b.at)>Date.parse(value.at)
          ||(b.state==='EXCEEDED')!==(units(b.inclusive_stop_risk_usdt)>units(b.stop_risk_limit_usdt)))return false;
        if(!same(row.blockers,expectedBlockers(row,i)))return false;
      }
      return true;
    }catch{return false;}
  }
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=x=>new Date(x).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'});
  // Display only: bounded precision, without optional Intl number formatting.
  // Truncate so an interval of 29.999 days cannot display as 30.
  const observedDays=x=>String(Math.trunc(x*100)/100);
  const labels={SPOT_TESTNET:'Spot Testnet',PAPER:'Paper',FUTURES_DEMO:'Futures Demo',SHADOW:'Shadow',UNKNOWN:'Desconocido',FRESH:'Fuente reciente en su ventana',STALE:'Fuente atrasada',ARMED:'Cobertura nativa observada',UNCONFIRMED:'Protección sin confirmar',NOT_APPLICABLE:'No corresponde a esta observación'};
  const set=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.textContent=text;};
  const html=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.innerHTML=text;};
  function clear(note){
    set('livePreparationState','LIVE BLOQUEADO · SIN EVALUACIÓN');
    set('livePreparationNote',note);
    set('livePreparationCapital','Sin propuesta verificable');
    set('livePreparationCapitalNote','Una propuesta no constituye saldo, reserva ni asignación.');
    set('livePreparationBlockers','Desconocidas');
    html('livePreparationEngines','');html('livePreparationGates','');
  }
  function disconnected(){
    clear('Lectura interrumpida: no hay una evaluación vigente en este panel. Esto no permite inferir una caída de los motores. LIVE permanece bloqueado.');
  }
  function render(value,remoteStale=false){
    if(!valid(value)){
      clear(value?'Evaluación no compatible: sus cifras se han retirado. LIVE permanece bloqueado.':'Sin evaluación de preparación disponible. LIVE permanece bloqueado.');
      return;
    }
    const age=(Date.now()-Date.parse(value.at))/1000;
    const historical=remoteStale===true||age>90||age < -5;
    set('livePreparationState',historical?'LIVE BLOQUEADO · CORTE NO VIGENTE':'LIVE BLOQUEADO · SOLO LECTURA');
    set('livePreparationNote',`Corte ${date(value.at)}${historical?' · lectura histórica o sincronización sin vigencia; las cifras no describen el estado actual':''}. La frescura de cada fuente se informa por separado. Un intervalo de 30 días no certifica evidencia ni autoriza LIVE.`);
    const proposal=value.capital_proposal;
    set('livePreparationCapital',proposal.amount_usd===null?'Sin propuesta verificable':`${proposal.amount_usd} USD propuestos`);
    set('livePreparationCapitalNote',proposal.amount_usd===null?'No se ha recibido una propuesta explícita válida. No hay capital asignado.':'Propuesta sin asignar. No es saldo, reserva, autorización ni equivalencia garantizada en USDT. Pérdida diaria y drawdown aún sin definir.');
    set('livePreparationBlockers',`${value.blockers.length} pendientes`);
    const openConditions=new Set(ids.filter(id=>root.document?.getElementById('livePreparationConditions'+id)?.open===true));
    html('livePreparationEngines',value.engines.map((row,i)=>{
      const fields=[['Entorno observado',labels[row.environment]],['Intervalo registrado',row.reported_span_days===null?'Desconocido':`${observedDays(row.reported_span_days)} días · ${row.span_gate==='SPAN_ONLY'?'solo intervalo, sin certificar':'inferior a 30 días'}`],['Días válidos certificados','Desconocidos'],['Frescura de la fuente',labels[row.freshness]],['Protección',labels[row.protection]]];
      const b=row.budget;
      if(b.state==='UNKNOWN')fields.push(['Presupuesto de riesgo','Sin verificación en esta evaluación']);
      else fields.push(['Presupuesto nativo Demo',`${b.state==='EXCEEDED'?'Superado':'Dentro del límite observado'} · ${b.inclusive_stop_risk_usdt} / ${b.stop_risk_limit_usdt} USDT`],['Corte del presupuesto',date(b.at)]);
      return `<article class="guardian-scope live-preparation-engine"><div class="live-preparation-engine-head"><h3>${names[i]}</h3><span class="badge neutral">SIN CERTIFICAR</span></div>${historical?'<p class="live-preparation-history">Corte no vigente · observaciones históricas</p>':''}<dl>${fields.map(([a,b])=>`<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join('')}</dl><details id="livePreparationConditions${ids[i]}"${openConditions.has(row.id)?' open':''}><summary>${row.blockers.length} condiciones pendientes</summary><ul>${row.blockers.map(code=>`<li>${esc(engineNames[code])}</li>`).join('')}</ul></details></article>`;
    }).join(''));
    html('livePreparationGates',value.blockers.map((code,i)=>`<article><h3>${esc(globalNames[i])}</h3><p>Pendiente · no certificado por esta evaluación.</p></article>`).join(''));
  }
  root.CryptoLivePreparation=Object.freeze({valid,render,disconnected});
})(globalThis);
