/* Shared cached audits: no account queries, simulation runs or admission controls. */
(function(root){
  'use strict';
  const authority=['execution_enabled','controls_enabled','reservations_enabled','promotion_allowed','financial_authorization','automatic_activation','can_veto','accounts_linked','complete_exchange_inventory','history_complete'];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,list)=>object(x)&&Object.keys(x).length===list.length&&list.every(k=>Object.hasOwn(x,k));
  const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(x)&&Number.isFinite(Date.parse(x))&&new Date(x).getUTCFullYear()>0&&new Date(x).toISOString()===x;
  const integer=(x,max)=>Number.isInteger(x)&&x>=0&&x<=max;
  const count=(x,max)=>x===null||integer(x,max);
  const decimal=x=>typeof x==='string'&&x.length<=13&&/^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/.test(x)
    &&(x.split('.')[1]||'').length<=2&&Number(x)>0&&Number(x)<=1000000000;
  function valid(value){
    try{
      if(!keys(value,['schema','engine','mode','at','autonomy_level','source_version',...authority,'qualified_days','accounts','checks','costs','cohort'])
        ||value.schema!==1||value.engine!=='MIGRATION_AUDIT'||value.mode!=='READ_ONLY'||value.autonomy_level!==0
        ||!stamp(value.at)||typeof value.source_version!=='string'||!/^(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})$/.test(value.source_version)
        ||!authority.every(key=>value[key]===false)||value.qualified_days!==null
        ||JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>8000
        ||!Array.isArray(value.accounts)||value.accounts.length!==2||!Array.isArray(value.checks)||value.checks.length!==3)return false;
      for(const [i,row] of value.accounts.entries()){
        if(!keys(row,['environment','state','at','identity','quantity_check','local_positions','exchange_positions','open_orders','conditional_orders'])
          ||row.environment!==['SPOT_TESTNET','FUTURES_DEMO'][i]||!['OBSERVED','PARTIAL','UNKNOWN'].includes(row.state)
          ||!(row.at===null||stamp(row.at)&&Date.parse(row.at)<=Date.parse(value.at))
          ||!['UNKNOWN','PRODUCT_ID_REPORTED_NOT_LINKED'].includes(row.identity)
          ||!['UNKNOWN','BALANCE_COVERS_LOCAL_AT_CUT','EXACT_QUANTITIES_AT_CUT','DIFFERENT_CUT_REQUIRES_RECONCILIATION'].includes(row.quantity_check)
          ||!['local_positions','exchange_positions','open_orders','conditional_orders'].every(key=>count(row[key],10000)))return false;
      }
      for(const [i,row] of value.checks.entries()){
        if(!keys(row,['id','state','passed','total'])||row.id!==['CAPITAL_FLOW','RISK_LATCHES','RECOVERY'][i]
          ||!['PASSED','FAILED','NOT_RUN','UNAVAILABLE'].includes(row.state))return false;
        if(['NOT_RUN','UNAVAILABLE'].includes(row.state)){
          if(row.passed!==null||row.total!==null)return false;
        }else if(!integer(row.passed,1000)||!integer(row.total,1000)||row.total<=0
          ||(row.state==='PASSED'?row.passed!==row.total:row.passed>=row.total))return false;
      }
      const c=value.costs;
      if(!keys(c,['state','scenarios','feasible','rejected','proposal_usd','hypothetical_usdt'])
        ||!['UNKNOWN','FEASIBLE_HYPOTHESIS','REJECTED_HYPOTHESIS','MIXED'].includes(c.state)
        ||!['scenarios','feasible','rejected'].every(key=>integer(c[key],100))||c.feasible+c.rejected!==c.scenarios
        ||!(c.proposal_usd===null||decimal(c.proposal_usd))||!(c.hypothetical_usdt===null||decimal(c.hypothetical_usdt))
        ||c.state!==(c.scenarios===0?'UNKNOWN':c.feasible&&c.rejected?'MIXED':c.feasible?'FEASIBLE_HYPOTHESIS':'REJECTED_HYPOTHESIS'))return false;
      const cohort=value.cohort;
      return keys(cohort,['state','receipt_days','missing_windows'])
        &&['NOT_REGISTERED','UNKNOWN','INCOMPLETE','SUPPLIED_RECEIPTS_ONLY'].includes(cohort.state)
        &&count(cohort.receipt_days,36500)&&count(cohort.missing_windows,50000000);
    }catch{return false;}
  }
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=x=>x===null?'Desconocido':new Date(x).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'});
  const number=x=>x===null?'Desconocido':String(x);
  const set=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.textContent=text;};
  const html=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.innerHTML=text;};
  const rows=fields=>`<dl>${fields.map(([a,b])=>`<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join('')}</dl>`;
  const state={OBSERVED:'Corte observado',PARTIAL:'Datos parciales',UNKNOWN:'Desconocido',PASSED:'Ensayo SIM aprobado',FAILED:'Ensayo SIM con fallos',NOT_RUN:'Sin ejecutar',UNAVAILABLE:'No disponible'};
  const quantity={UNKNOWN:'Sin contraste verificable',BALANCE_COVERS_LOCAL_AT_CUT:'Saldo cubre cantidad local al corte',EXACT_QUANTITIES_AT_CUT:'Cantidades coinciden al corte',DIFFERENT_CUT_REQUIRES_RECONCILIATION:'Diferencia entre cortes · conciliar'};
  function clear(note){
    set('migrationAuditState','SIN INFORME VERIFICABLE');set('migrationAuditNote',note);
    html('migrationAuditAccounts','');html('migrationAuditChecks','');
    set('migrationAuditCosts','Sin hipótesis verificables');set('migrationAuditCapital','Importes desconocidos; sin asignación.');
    set('migrationAuditCohort','Sin evidencia verificable');set('migrationAuditCoverage','Días válidos certificados: desconocidos.');
  }
  function disconnected(){
    clear('La lectura del panel se interrumpió. No permite inferir una caída de los motores ni de Binance. LIVE sigue bloqueado.');
  }
  function render(value,remoteStale=false){
    if(!valid(value)){
      clear(value?'Informe no compatible: sus cifras se han retirado. LIVE sigue bloqueado.':'Sin auditoría publicada. Este panel sólo lee informes preparados explícitamente; no consulta Binance ni ejecuta ensayos.');
      return;
    }
    const age=(Date.now()-Date.parse(value.at))/1000;
    const historical=age>90||age < -5;
    set('migrationAuditState',historical?'INFORME HISTÓRICO · SOLO LECTURA':'AUDITORÍA · SOLO LECTURA');
    set('migrationAuditNote',`Corte del informe ${date(value.at)} · fuente v${value.source_version}.${historical?' El corte es histórico; no describe el estado actual.':''}${remoteStale===true?' La sincronización remota no está vigente; su estado se distingue de la salud de los motores.':''} Abrir o actualizar esta pantalla no renueva la evidencia.`);
    html('migrationAuditAccounts',value.accounts.map((row,i)=>{
      const accountAge=row.at===null?null:(Date.now()-Date.parse(row.at))/1000;
      const label=row.at===null?'Frescura desconocida':accountAge>90||accountAge < -5?'Corte histórico':'Corte reciente';
      return `<article class="migration-audit-card"><div class="migration-audit-card-head"><h3>${i===0?'Spot Testnet':'Futures Demo'}</h3><span class="badge neutral">${esc(state[row.state])}</span></div>${rows([
        ['Fuente',`${date(row.at)} · ${label}`],['Identidad',row.identity==='UNKNOWN'?'Desconocida':'Identificador reportado · cuentas sin vincular'],
        ['Posiciones locales',number(row.local_positions)],['Posiciones del exchange',number(row.exchange_positions)],
        ['Órdenes estándar',number(row.open_orders)],['Órdenes condicionales',number(row.conditional_orders)],
        ['Contraste de cantidades',quantity[row.quantity_check]]])}</article>`;
    }).join(''));
    const checkNames=['Flujo de capital','Bloqueos persistentes de riesgo','Recuperación'];
    html('migrationAuditChecks',value.checks.map((row,i)=>`<article class="migration-audit-check"><h3>${checkNames[i]}</h3><p>${esc(state[row.state])}${row.passed===null?'':` · ${row.passed}/${row.total}`}</p></article>`).join(''));
    const c=value.costs;
    const costNames={UNKNOWN:'Viabilidad desconocida',FEASIBLE_HYPOTHESIS:'Hipótesis matemáticas compatibles',REJECTED_HYPOTHESIS:'Hipótesis rechazadas',MIXED:'Resultados mixtos'};
    set('migrationAuditCosts',c.state==='UNKNOWN'?costNames[c.state]:`${costNames[c.state]} · ${c.feasible}/${c.scenarios} compatibles · ${c.rejected} rechazadas`);
    set('migrationAuditCapital',`Propuesta: ${c.proposal_usd===null?'desconocida':c.proposal_usd+' USD'}. Escenario hipotético: ${c.hypothetical_usdt===null?'desconocido':c.hypothetical_usdt+' USDT'}. Importes separados; sin conversión, saldo ni asignación.`);
    const cohort=value.cohort;
    const cohortNames={NOT_REGISTERED:'Cohorte prospectiva sin registrar',UNKNOWN:'Cobertura desconocida',INCOMPLETE:'Cobertura de recibos incompleta',SUPPLIED_RECEIPTS_ONLY:'Sólo recibos suministrados'};
    set('migrationAuditCohort',cohortNames[cohort.state]);
    set('migrationAuditCoverage',`Días completos con recibos suministrados: ${number(cohort.receipt_days)}. Ventanas faltantes: ${number(cohort.missing_windows)}. Días válidos certificados: desconocidos.`);
  }
  root.CryptoMigrationAudit=Object.freeze({valid,render,disconnected});
})(globalThis);
