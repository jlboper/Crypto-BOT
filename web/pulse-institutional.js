/* Institutional filings and delayed positioning are context, never commands. */
(function(root){
  'use strict';
  const providers={cftc_tff:['CFTC · CME institutional positioning','https://publicreporting.cftc.gov/stories/s/r4w3-av2u'],sec_edgar:['SEC EDGAR · public disclosures','https://www.sec.gov/search-filings/edgar-application-programming-interfaces']};
  const metrics=['open_interest_contracts','dealer_long_contracts','dealer_short_contracts','asset_manager_long_contracts','asset_manager_short_contracts','leveraged_fund_long_contracts','leveraged_fund_short_contracts','asset_manager_net_contracts','leveraged_fund_net_contracts','open_interest_change_contracts','asset_manager_net_change_contracts','leveraged_fund_net_change_contracts'];
  const limitations=['DELAYED_CONTEXT_NOT_ENTRY_SIGNAL','FIRST_OBSERVED_NOT_ORIGINAL_RELEASE','CONTRACTS_NOT_USD_CAPITAL','SHORT_MAY_BE_HEDGE','NOT_ALL_MARKET_POSITIONS','FILING_CONTENT_NOT_PARSED','NO_DIRECTION_FROM_FILING_METADATA','INSIDER_EQUITY_NOT_DIRECT_CRYPTO','THIRTEEN_F_NO_SHORTS_DELAYED','ETF_NET_FLOWS_UNAVAILABLE','ETF_HOLDINGS_NOT_FLOWS','SEC_CONTACT_REQUIRED','NO_NONPUBLIC_INFORMATION','NO_PROVEN_TRADING_EDGE','STALE_CONTEXT'];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,names)=>object(x)&&Object.keys(x).length===names.length&&names.every(name=>Object.hasOwn(x,name));
  const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(x)&&Number.isFinite(Date.parse(x))&&new Date(x).getUTCFullYear()>0&&new Date(x).toISOString()===x;
  const hash=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x);
  const size=x=>JSON.stringify(x).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length;
  const limits=x=>Array.isArray(x)&&x.length>=1&&x.length<=8&&new Set(x).size===x.length&&x.every(code=>limitations.includes(code));
  function valid(value){
    try{
      if(!keys(value,['schema','mode','execution_enabled','at','providers','observations','limitations'])||value.schema!==1||value.mode!=='CONTEXT_ONLY'||value.execution_enabled!==false||!stamp(value.at)||size(value)>8000||!limits(value.limitations)||!Array.isArray(value.providers)||value.providers.length>2||!Array.isArray(value.observations)||value.observations.length>6)return false;
      const seen=new Set();
      for(const row of value.providers){
        if(!keys(row,['id','name','url','state','last_update','last_error'])||!Object.hasOwn(providers,row.id)||seen.has(row.id)||row.name!==providers[row.id][0]||row.url!==providers[row.id][1]||!['STANDBY','READY','ERROR','DISABLED'].includes(row.state)||![null,'SEC_CONTACT_REQUIRED','INSTITUTIONAL_HTTP_ERROR','INSTITUTIONAL_UNAVAILABLE'].includes(row.last_error)||!(row.last_update===null||stamp(row.last_update)&&row.last_update<=value.at))return false;
        seen.add(row.id);
      }
      const ids=new Set(),proofs=new Set();
      for(const row of value.observations){
        if(!keys(row,['id','provider','symbol','category','as_of','available_at','received_at','availability_basis','title','url','metrics','limitations','evidence_digest'])||!hash(row.id)||!hash(row.evidence_digest)||ids.has(row.id)||!Object.hasOwn(providers,row.provider)||!['BTCUSDT','ETHUSDT','MARKET'].includes(row.symbol)||!['CFTC_POSITIONING','SEC_ETF_FILING','SEC_INSIDER_FILING','SEC_INSTITUTIONAL_FILING'].includes(row.category)||typeof row.title!=='string'||row.title.length<1||row.title.length>180||/[\u0000-\u001f<>]/.test(row.title)||!limits(row.limitations)||!['as_of','available_at','received_at'].every(key=>stamp(row[key]))||!(row.as_of<=row.available_at&&row.available_at<=row.received_at&&row.received_at<=value.at)||!object(row.metrics)||!Object.keys(row.metrics).every(key=>metrics.includes(key))||!Object.values(row.metrics).every(number=>Number.isInteger(number)&&Math.abs(number)<=1e12)||size(row)>2500)return false;
        if(row.category==='CFTC_POSITIONING'){
          if(row.provider!=='cftc_tff'||row.availability_basis!=='FIRST_OBSERVED'||row.url!==providers.cftc_tff[1]||row.available_at!==row.received_at||!keys(row.metrics,metrics))return false;
        }else if(row.provider!=='sec_edgar'||row.availability_basis!=='SEC_ACCEPTANCE'||Object.keys(row.metrics).length||!/^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/\d{1,10}\/\d{18}\/\d{10}-\d{2}-\d{6}-index\.html$/.test(row.url))return false;
        const proof=[row.provider,row.symbol,row.evidence_digest].join(':');if(proofs.has(proof))return false;proofs.add(proof);ids.add(row.id);
      }
      return true;
    }catch{return false;}
  }
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const set=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.textContent=text;};
  const html=(id,text)=>{const node=root.document?.getElementById(id);if(node)node.innerHTML=text;};
  const date=x=>x===null?'Sin fecha verificable':new Date(x).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'});
  const number=x=>Number.isInteger(x)?x.toLocaleString('es-MX'):'Desconocido';
  const categoryNames={CFTC_POSITIONING:'Posicionamiento CFTC · contratos CME',SEC_ETF_FILING:'Publicación de documento ETF',SEC_INSIDER_FILING:'Declaración pública de insider · acciones',SEC_INSTITUTIONAL_FILING:'Declaración institucional publicada'};
  function clear(note){set('pulseInstitutionalState','SIN CONTEXTO VERIFICABLE');set('pulseInstitutionalNote',note);html('pulseInstitutionalProviders','');html('pulseInstitutionalObservations','');}
  function render(value,remoteStale=false){
    if(!valid(value)){clear(value?'Contexto incompatible; se retiraron sus cifras. Market Pulse conserva sus límites y SHADOW.':'Todavía no hay contexto institucional publicado. La ausencia de documentos nuevos no implica un error.');return;}
    const old=remoteStale===true||Date.now()-Date.parse(value.at)>120000||Date.parse(value.at)>Date.now()+5000;
    set('pulseInstitutionalState',old?'CONTEXTO HISTÓRICO':'CONTEXTO PÚBLICO · SIN ÓRDENES');
    set('pulseInstitutionalNote',`Corte ${date(value.at)}.${old?' Proyección antigua; no describe el estado actual de las fuentes.':''} Datos públicos con retraso; no son una instrucción de compra o venta.`);
    const states={STANDBY:'En espera',READY:'Consulta disponible',ERROR:'Fuente no disponible',DISABLED:'Deshabilitada'};
    html('pulseInstitutionalProviders',value.providers.map(row=>`<article class="pulse-source"><strong><a href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">${esc(row.name)} ↗</a></strong><span>${states[row.state]}${row.last_error==='SEC_CONTACT_REQUIRED'?' · requiere contacto real del propietario para SEC Fair Access':''}</span><small>Última consulta: ${esc(date(row.last_update))}</small></article>`).join(''));
    html('pulseInstitutionalObservations',value.observations.map(row=>{
      const m=row.metrics,cftc=row.category==='CFTC_POSITIONING';
      const values=cftc?`<dl class="pulse-metrics"><div><dt>Open interest</dt><dd>${number(m.open_interest_contracts)} contratos</dd></div><div><dt>Asset managers · long / short</dt><dd>${number(m.asset_manager_long_contracts)} / ${number(m.asset_manager_short_contracts)} contratos</dd></div><div><dt>Asset managers · neto / cambio neto</dt><dd>${number(m.asset_manager_net_contracts)} / ${number(m.asset_manager_net_change_contracts)} contratos</dd></div><div><dt>Leveraged funds · long / short</dt><dd>${number(m.leveraged_fund_long_contracts)} / ${number(m.leveraged_fund_short_contracts)} contratos</dd></div><div><dt>Leveraged funds · neto / cambio neto</dt><dd>${number(m.leveraged_fund_net_contracts)} / ${number(m.leveraged_fund_net_change_contracts)} contratos</dd></div></dl><p class="platform-note">Contratos, no flujos en USD. Un short puede ser cobertura. Primera recepción observada; no se reconstruye la hora original de publicación.</p>`:`<p class="platform-note">La publicación confirma un documento; no se ha interpretado su contenido transaccional.${row.category==='SEC_ETF_FILING'?' Flujos netos de ETF: no disponibles.':''}${row.category==='SEC_INSIDER_FILING'?' Una declaración sobre acciones de una empresa no equivale a una operación directa sobre criptomonedas.':''}${row.category==='SEC_INSTITUTIONAL_FILING'?' Los 13F llegan con retraso y no acreditan posiciones cortas.':''}</p>`;
      return `<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(row.symbol)} · ${categoryNames[row.category]}</strong><span class="badge">${row.limitations.includes('STALE_CONTEXT')?'CONTEXTO ANTIGUO':'SOLO CONTEXTO'}</span></div><h4>${esc(row.title)}</h4><p><a href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">Ver fuente oficial ↗</a></p><dl class="pulse-times"><div><dt>Fecha de los datos</dt><dd>${esc(date(row.as_of))}</dd></div><div><dt>${cftc?'Disponible por primera observación':'Publicado / aceptado por SEC'}</dt><dd>${esc(date(row.available_at))}</dd></div><div><dt>Recibido</dt><dd>${esc(date(row.received_at))}</dd></div></dl>${values}</article>`;
    }).join('')||'<p class="empty">Sin observaciones verificables nuevas. No se infieren compras, ventas ni flujos inexistentes.</p>');
  }
  function disconnected(){clear('No se pudo actualizar el panel. No demuestra una caída del motor ni de las fuentes.');}
  root.CryptoInstitutionalContext=Object.freeze({valid,render,disconnected});
})(globalThis);
