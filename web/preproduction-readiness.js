/* Shared closed preproduction evidence. No API, command or credential input. */
(function(root){
  'use strict';
  const packageIds=['EVIDENCE','ACCOUNT','CAPITAL','RISK','EXECUTION'];
  const packageStates=['IMPLEMENTED_NOT_VALIDATED','TESTED_PREPARED','WAITING_OWNER','WAITING_EVIDENCE','UNAVAILABLE'];
  const blockers=['OWNER_ACTIVATION_REQUIRED','READ_ONLY_CONNECTION_UNVERIFIED','FORWARD_COHORT_INCOMPLETE','ACCOUNT_RECONCILIATION_INCOMPLETE','CAPITAL_PROTOCOL_UNVALIDATED','RISK_PROTOCOL_UNVALIDATED','EXECUTION_RECOVERY_UNVALIDATED','TECHNICAL_REPORT_UNAVAILABLE','SOURCE_CHANGED','LEGACY_AUDIT_REQUIRED','NO_AUTOMATIC_THIRTY_DAY_APPROVAL'];
  const scopes=[['SPOT','SPOT_TESTNET'],['FUTURES','FUTURES_DEMO'],['AI_MARKET_PULSE','SHADOW'],['QUANT_ARBITRAGE','SHADOW']];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,names)=>object(x)&&Object.keys(x).length===names.length&&names.every(name=>Object.hasOwn(x,name));
  const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(x)&&Number.isFinite(Date.parse(x))&&new Date(x).getUTCFullYear()>0&&new Date(x).toISOString()===x;
  const number=(x,max=50000000)=>x===null||Number.isInteger(x)&&x>=0&&x<=max;
  const nullableTime=(x,at)=>x===null||stamp(x)&&x<=at;
  function valid(value){
    try{
      if(!keys(value,['schema','engine','mode','at','source_version','execution_enabled','controls_enabled','owner_authorization','connection','cohort','packages','blockers'])||value.schema!==1||value.engine!=='PREPRODUCTION'||value.mode!=='READ_ONLY'||!stamp(value.at)
        ||typeof value.source_version!=='string'||!/^(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})$/.test(value.source_version)
        ||!['execution_enabled','controls_enabled','owner_authorization'].every(name=>value[name]===false)
        ||JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>8000)return false;
      const c=value.connection;
      if(!keys(c,['schema','state','at','scopes'])||c.schema!==1||!['NOT_CONFIGURED','CONFIGURED_UNVERIFIED','READ_ONLY_VERIFIED','UNAVAILABLE'].includes(c.state)||!nullableTime(c.at,value.at)||!Array.isArray(c.scopes)||c.scopes.length!==2)return false;
      for(const [i,row] of c.scopes.entries()){
        if(!keys(row,['environment','identity','permissions','at'])||row.environment!==['SPOT_LIVE','FUTURES_LIVE'][i]||!['UNKNOWN','REPORTED'].includes(row.identity)||!['UNKNOWN','VERIFIED'].includes(row.permissions)||!nullableTime(row.at,value.at))return false;
        if(row.permissions==='VERIFIED'&&(row.identity!=='REPORTED'||row.at===null))return false;
      }
      if(c.state==='READ_ONLY_VERIFIED'&&(c.at===null||c.scopes.some(row=>row.identity!=='REPORTED'||row.at===null)))return false;
      if(c.state==='NOT_CONFIGURED'&&(c.at!==null||c.scopes.some(row=>row.at!==null||row.identity!=='UNKNOWN'||row.permissions!=='UNKNOWN')))return false;
      const cohort=value.cohort;
      if(!keys(cohort,['state','scopes'])||!['NOT_REGISTERED','OBSERVING','PARTIAL','UNAVAILABLE'].includes(cohort.state)||!Array.isArray(cohort.scopes)||cohort.scopes.length>4)return false;
      const seen=new Set();
      for(const row of cohort.scopes){
        if(!keys(row,['engine','environment','state','registered_at','starts_at','last_capture_at','source_at','source_complete','stale','operational_days','qualified_days','missing_windows']))return false;
        const scope=row.engine+':'+row.environment;
        if(!scopes.some(([engine,environment])=>engine===row.engine&&environment===row.environment)||seen.has(scope)||!['OBSERVING_LOCAL','STALE','NOT_CAPTURED','INCOMPLETE'].includes(row.state))return false;
        seen.add(scope);
        if(!stamp(row.registered_at)||row.registered_at>value.at||!stamp(row.starts_at)||row.starts_at<row.registered_at||typeof row.source_complete!=='boolean'||typeof row.stale!=='boolean'
          ||!nullableTime(row.last_capture_at,value.at)||!nullableTime(row.source_at,value.at)||!number(row.operational_days,36500)||!number(row.qualified_days,36500)||!number(row.missing_windows))return false;
        if(row.qualified_days!==null&&(row.operational_days===null||row.qualified_days>row.operational_days))return false;
      }
      if(cohort.state==='NOT_REGISTERED'&&cohort.scopes.length)return false;
      if(!Array.isArray(value.packages)||value.packages.length!==5||value.packages.some((row,i)=>!keys(row,['id','state'])||row.id!==packageIds[i]||!packageStates.includes(row.state)))return false;
      return Array.isArray(value.blockers)&&value.blockers.length>=1&&value.blockers.length<=blockers.length&&new Set(value.blockers).size===value.blockers.length&&value.blockers.every(code=>typeof code==='string'&&blockers.includes(code))&&value.blockers.includes('OWNER_ACTIVATION_REQUIRED');
    }catch{return false;}
  }
  const set=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.textContent=text;};
  const html=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.innerHTML=text;};
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=x=>x===null?'Sin corte verificable':new Date(x).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'});
  const count=x=>x===null?'Desconocidos':String(x);
  const packageNames={EVIDENCE:'Evidencia y continuidad',ACCOUNT:'Cuenta y conciliación',CAPITAL:'Reservas y capital',RISK:'Riesgo persistente',EXECUTION:'Ejecución y recuperación'};
  const stateNames={IMPLEMENTED_NOT_VALIDATED:'Implementado · validación pendiente',TESTED_PREPARED:'Pruebas documentadas · preparado',WAITING_OWNER:'Pendiente de autorización final',WAITING_EVIDENCE:'Pendiente de evidencia',UNAVAILABLE:'No disponible'};
  const blockerNames={OWNER_ACTIVATION_REQUIRED:'Aprobación final de activación',READ_ONLY_CONNECTION_UNVERIFIED:'Conexión de solo lectura sin verificar',FORWARD_COHORT_INCOMPLETE:'Cobertura financiera forward incompleta',ACCOUNT_RECONCILIATION_INCOMPLETE:'Conciliación completa de cuenta pendiente',CAPITAL_PROTOCOL_UNVALIDATED:'Protocolo conjunto de capital sin validar',RISK_PROTOCOL_UNVALIDATED:'Admisión conjunta de riesgo sin validar',EXECUTION_RECOVERY_UNVALIDATED:'Ejecución y recuperación sin validar',TECHNICAL_REPORT_UNAVAILABLE:'Sin informe técnico compatible',SOURCE_CHANGED:'El código cambió respecto del informe técnico',LEGACY_AUDIT_REQUIRED:'Revisión de evidencia histórica',NO_AUTOMATIC_THIRTY_DAY_APPROVAL:'Los 30 días no activan operaciones automáticamente'};
  const engineNames={SPOT:'Spot Testnet',FUTURES:'Futures Demo',AI_MARKET_PULSE:'Market Pulse · SHADOW',QUANT_ARBITRAGE:'Quant · SHADOW'};
  function clear(note){set('preproductionState','PREPARACIÓN SIN VERIFICAR');set('preproductionNote',note);set('preproductionConnection','Sin corte verificable.');html('preproductionPackages','');html('preproductionCohorts','');html('preproductionBlockers','');}
  function disconnected(){clear('No se pudo leer el panel. Esto no demuestra una caída de los motores ni de Binance. No se ha activado LIVE.');}
  function render(value,remoteStale=false){
    if(!valid(value)){clear(value?'Informe incompatible; se retiraron sus cifras. No se ha activado LIVE.':'Sin informe de preparación. Consultar este panel no conecta cuentas ni envía órdenes.');return;}
    set('preproductionState','PREPARACIÓN · LIVE BLOQUEADO');
    set('preproductionNote',`Lectura del panel ${date(value.at)} · v${value.source_version}. Las fechas de cada fuente se conservan.${remoteStale===true?' Sincronización remota atrasada; no equivale a una caída del motor.':''}`);
    const connectionNames={NOT_CONFIGURED:'Conexión LIVE sin configurar',CONFIGURED_UNVERIFIED:'Configurada; lectura sin verificar',READ_ONLY_VERIFIED:'Lectura de cuenta observada; sin autorización de órdenes',UNAVAILABLE:'Conexión no verificable'};
    const c=value.connection;
    const old=c.at!==null&&(Date.now()-Date.parse(c.at)>90000||Date.parse(c.at)>Date.now()+5000);
    set('preproductionConnection',`${connectionNames[c.state]} · ${date(c.at)}${old?' · corte histórico':''}. Spot y Futures mantienen cuentas separadas. Los permisos desconocidos no se interpretan como permiso de trading.`);
    html('preproductionPackages',value.packages.map(row=>`<article class="preproduction-card"><h3>${packageNames[row.id]}</h3><p>${stateNames[row.state]}</p></article>`).join(''));
    html('preproductionCohorts',value.cohort.scopes.length?value.cohort.scopes.map(row=>`<article class="preproduction-card"><div class="preproduction-card-heading"><h3>${engineNames[row.engine]}</h3><span class="badge neutral">${row.stale?'Datos incompletos o atrasados':'Observación local'}</span></div><dl><div><dt>Registro prospectivo</dt><dd>${esc(date(row.registered_at))}</dd></div><div><dt>Última captura</dt><dd>${esc(date(row.last_capture_at))}</dd></div><div><dt>Corte de la fuente</dt><dd>${esc(date(row.source_at))}</dd></div><div><dt>Días de cobertura operativa local</dt><dd>${count(row.operational_days)}</dd></div><div><dt>Días de recibos financieros completos</dt><dd>${count(row.qualified_days)}</dd></div><div><dt>Ventanas locales faltantes</dt><dd>${count(row.missing_windows)}</dd></div></dl></article>`).join(''):'<p class="empty">Sin cohorte prospectiva registrada. El historial previo se conserva y requiere una auditoría independiente.</p>');
    html('preproductionBlockers',value.blockers.map(code=>`<li>${blockerNames[code]}</li>`).join(''));
  }
  root.CryptoPreproduction=Object.freeze({valid,render,disconnected});
})(globalThis);
