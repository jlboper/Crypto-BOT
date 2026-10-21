(function () {
  'use strict';
  const names={SPOT:'Spot',FUTURES:'Futures',AI_MARKET_PULSE:'Market Pulse',QUANT_ARBITRAGE:'Quant'};
  const states={NOT_STARTED:'NO INICIADO',IDLE:'ESPERANDO PROPUESTAS',OBSERVING:'OBSERVANDO',STALE:'DATOS ANTIGUOS',PARTIAL:'COBERTURA PARCIAL',UNAVAILABLE:'NO DISPONIBLE'};
  const stages={FINAL_ENTRY_INTENT:'Intención final',HYPOTHETICAL_ENTRY_INTENT:'Apertura hipotética',EXCHANGE_RESPONSE:'Respuesta del exchange',LEDGER_COMMIT:'Confirmación del ledger'};
  const hypotheses={RESERVED_UNVERIFIED:'Reserva hipotética condicionada',REJECTED_UNVERIFIED:'Hipótesis rechazada',UNKNOWN:'No evaluable'};
  let last=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const el=id=>document.getElementById(id);
  const set=(id,text)=>{const n=el(id);if(n)n.textContent=text;};
  const html=(id,value)=>{const n=el(id);if(n)n.innerHTML=value;};
  const count=v=>Number.isSafeInteger(v)&&v>=0?String(v):'Desconocido';
  const stamp=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('es-MX'):'Desconocida';
  const cash=v=>typeof v==='string'&&/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(v)?v+' USDT':'Desconocido';
  const metrics=rows=>rows.map(([a,b])=>'<div><dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd></div>').join('');
  function unknown(state,note){
    set('opportunityState',state);set('opportunityStatus',note);set('opportunityHealth','Salud del observador desconocida.');
    html('opportunityMetrics','');html('opportunityCoverage','');html('opportunityScopes','');
    html('opportunityRecords','<p class="empty">No hay un reporte compatible. Los valores desconocidos no se sustituyen por cero.</p>');
  }
  function render(platform){
    const v=platform?.opportunity_shadow;
    let valid=false;try{valid=window.CryptoOpportunityContract?.validOpportunityShadow(v)===true;}catch(_){}
    if(!valid){last=null;unknown('SIN EVIDENCIA','Observador no disponible en esta lectura. No permite inferir el estado de los motores.');return;}
    last=v;
    const historical=platform?.remote_sync_stale===true;
    set('opportunityState',historical?'LECTURA ANTERIOR':states[v.state]);
    set('opportunityStatus',(historical?'Sincronización antigua · ':'')+'Última intención o resultado: '+stamp(v.updated_at)+'. '+(v.state==='IDLE'?'Sin intenciones recibidas; no implica un error.':'Observación asíncrona por motor y entorno. Permisos financieros desactivados.'));
    set('opportunityHealth','Último informe · latido: '+stamp(v.health.heartbeat_at)+' · frescura del observador: '+v.freshness.state+' · capacidad: '+v.health.capacity_state+' · diagnóstico: '+(v.health.last_error||'Sin error registrado')+'.');
    html('opportunityMetrics','<dl class="pulse-metrics">'+metrics([['Registros',count(v.health.records)],['Observaciones descartadas',count(v.health.dropped)],['Cola',count(v.health.queue_depth)+' / '+count(v.health.queue_capacity)],['Errores del observador',count(v.health.errors)]])+'</dl>');
    html('opportunityCoverage',v.coverage.map(c=>'<article><h3>'+esc(names[c.engine])+'</h3><span class="badge neutral">'+esc(c.environment==='UNKNOWN'?'Ámbitos históricos múltiples':c.environment)+'</span><p>'+esc(c.state==='OBSERVED'?'Con evidencia recibida':'Sin intenciones recibidas')+'</p><dl class="pulse-metrics">'+metrics([['Intenciones',count(c.intents)],['Resultados observados',count(c.outcomes)],['Última observación',stamp(c.last_at)]])+'</dl></article>').join(''));
    html('opportunityScopes',v.scopes.map(s=>'<article><h3>'+esc(names[s.engine])+'</h3><span class="badge neutral">'+esc(s.environment)+'</span><dl class="pulse-metrics">'+metrics([['Cuenta','Identidad sin verificar'],['Reserva hipotética',cash(s.hypothetical_reserved)],['Nocional hipotético',cash(s.hypothetical_gross)],['Riesgo estimado con costes',cash(s.hypothetical_stop_risk)],['Intenciones inciertas',count(s.uncertain_intents)]])+'</dl></article>').join(''));
    const open=new Set(el('opportunityRecords')?Array.from(el('opportunityRecords').querySelectorAll('details[open]')).map(n=>n.id):[]);
    const selected=v.recent_records.length,total=v.health.records;
    const selection='<p class="platform-note">'+esc(Number.isSafeInteger(total)&&total>=selected
      ?'Selección reciente: '+selected+' de '+total+' registros del journal.'
      :'Selección reciente: '+selected+' registros; total del journal desconocido en esta lectura.')+'</p>';
    const emptyRecords=total===0?'Sin propuestas recibidas. Se conserva la inactividad como estado válido, sin crear oportunidades.'
      :Number.isSafeInteger(total)&&total>0?'El journal registra '+total+' eventos, pero esta lectura no incluye detalle reciente. La ausencia de detalle no permite concluir que no hubo propuestas.'
      :'No hay detalle reciente disponible en esta lectura. La actividad total del journal no está confirmada.';
    html('opportunityRecords',selection+(selected?v.recent_records.map(r=>{
      const a=r.assessment, symbols=(r.legs||[]).map(l=>l.symbol).join(' / ')||'Activo no disponible en este resultado';
      const stage=stages[r.stage]||r.stage||r.kind;
      const legs=(r.legs||[]).map(l=>'<li>'+esc(l.symbol+' · '+l.direction+' · '+l.venue)+'<dl class="pulse-metrics">'+metrics([['Cantidad',l.quantity??'Desconocida'],['Referencia',cash(l.reference_price)],['Stop',cash(l.stop_price)],['Objetivo',cash(l.take_profit)]])+'</dl></li>').join('');
      return '<article class="opportunity-record"><div class="panel-title"><h3>'+esc(names[r.engine]+' · '+symbols)+'</h3><span class="badge neutral">'+esc(r.environment)+'</span></div><p>'+esc(stage)+' · '+esc(r.state)+' · '+esc(stamp(r.at))+'</p><p>'+esc(hypotheses[a.hypothetical_state]||'No evaluable')+' · admisión efectiva no evaluable.</p><details id="opportunity-record-'+esc(r.id)+'" '+(open.has('opportunity-record-'+r.id)?'open':'')+'><summary>Evidencia y evaluación congelada</summary><dl class="pulse-metrics">'+metrics([['Nocional',cash(a.gross_notional)],['Capital estimado',cash(a.committed_capital)],['Costes estimados',cash(a.estimated_costs)],['Riesgo nominal al stop',cash(a.nominal_stop_risk)],['Riesgo estimado con costes',cash(a.stop_risk)],['Motivo del cálculo',a.reason],['Registrado el',stamp(r.recorded_at)],['Revisión del registro',String(r.revision)],['Identidad de cuenta','Desconocida'],['Registro',r.id],['Origen',r.origin_digest]])+'</dl><ul class="opportunity-legs">'+legs+'</ul><p class="platform-note">Las referencias y cantidades reflejan los datos capturados. No acreditan fills, margen, cobertura eficaz o protección nativa. No se atribuye rentabilidad a esta recomendación.</p></details></article>';
    }).join(''):'<p class="empty">'+esc(emptyRecords)+'</p>'));
  }
  function disconnected(){
    if(last){set('opportunityState','LECTURA ANTERIOR');set('opportunityStatus','Portal sin conexión · último reporte recibido. Frescura y actividad actuales desconocidas.');}
    else unknown('SIN CONEXIÓN','Portal sin conexión; evidencia del observador desconocida.');
  }
  window.OpportunityShadowPortal=Object.freeze({render,disconnected});
})();
