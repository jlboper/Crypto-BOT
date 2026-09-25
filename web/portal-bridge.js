/* One UI, local APIs or authenticated remote snapshots. No credentials in URLs. */
const remotePortal = !['127.0.0.1','localhost','[::1]','::1'].includes(location.hostname);
let portalCsrf = '', portalPending, portalCache, portalCacheAt = 0, portalEpoch=0;
const portalRoute = {'/api/status':'status','/api/positions':'positions','/api/trades':'trades','/api/ai-reviews':'reviews','/api/equity':'equity','/api/events':'events','/api/research':'research','/api/research/status':'research_state','/api/updates':'updates','/api/paper-scorecard':'paper_scorecard','/api/testnet/execution':'testnet_execution'};
async function portalPasswordProof(password,parameters){
  if(parameters.scheme==='initial-key')return password;
  if(parameters.scheme!=='pbkdf2-sha256'||parameters.iterations!==600000||!/^[A-Za-z0-9_-]{43}$/.test(parameters.salt||''))throw new Error('Parámetros de acceso inválidos');
  const encoder=new TextEncoder();
  const key=await crypto.subtle.importKey('raw',encoder.encode(password),'PBKDF2',false,['deriveBits']);
  const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',iterations:600000,salt:encoder.encode(parameters.salt)},key,256);
  return Array.from(new Uint8Array(bits),b=>b.toString(16).padStart(2,'0')).join('');
}
function portalLocked(){
  portalEpoch++;
  portalCsrf='';portalPending=null;portalCache=null;portalCacheAt=0;
  const menu=document.getElementById('optionsMenu');menu.hidden=true;
  document.getElementById('optionsButton').setAttribute('aria-expanded','false');
  document.getElementById('portalLogin').hidden=false;
  document.querySelector('.shell').hidden=true;
  document.getElementById('passwordPanel').hidden=true;
  document.getElementById('historyPanel').hidden=true;
  document.getElementById('historyRows').replaceChildren();
  for(const id of ['currentPassword','newPassword','confirmPassword'])document.getElementById(id).value='';
}
async function portalRequest(path,body){
  const headers={Accept:'application/json'};
  if(body!==undefined){headers['Content-Type']='application/json';headers['X-CSRF-Token']=portalCsrf;}
  const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
  let data;
  try{data=await response.json();}catch{throw new Error(response.ok?'Respuesta inválida del portal':'Error de conexión');}
  if(!response.ok){if(response.status===401)portalLocked();throw new Error(data.error||'Error de conexión');}
  return data;
}
const activityActions={research:'Evaluar estrategias',update_check:'Buscar actualización',update_install:'Actualizar bot',update_restore:'Restaurar bot',kill:'Pausar bot',resume:'Reanudar bot',risk_profile:'Perfil de riesgo PAPER',paper_close:'Cerrar posición PAPER',ai_model:'Cambiar modelo IA',restart_engine:'Reiniciar motor',testnet_buy:'Comprar Testnet',testnet_close:'Cerrar Testnet',testnet_reconcile:'Conciliar Testnet'};
const activityStatuses={pending:'Pendiente',applied:'Confirmado por Windows',expired:'Vencido',superseded:'Sustituido',running:'En curso',completed:'Completado',failed:'Falló'};
function renderActivity(list,items){
  for(const item of items){
    const row=document.createElement('li');
    row.className=item.status==='failed'?'failed':'';
    row.textContent=`${activityActions[item.action]||item.action} · ${activityStatuses[item.status]||item.status}`;
    if(item.message){const detail=document.createElement('small');detail.textContent=item.message;row.append(detail);}
    if(item.created){const time=document.createElement('small');time.textContent=new Date(item.created*1000).toLocaleString('es-MX');row.append(time);}
    list.append(row);
  }
}
async function portalState(){
  if(portalCache && Date.now()-portalCacheAt<5000)return portalCache;
  const epoch=portalEpoch;
  if(!portalPending)portalPending=portalRequest('/v1/status').then(state=>{
    if(epoch!==portalEpoch)throw new Error('Sesión finalizada');
    portalCsrf=state.csrf;portalCache=state;portalCacheAt=Date.now();
    document.getElementById('portalConnection').textContent=state.stale?'Windows sin conexión reciente':'Windows conectado · sincronización HTTPS';
    const commands=document.getElementById('portalCommands');commands.replaceChildren();
    const recent=(state.activity||[...(state.jobs||[]),...(state.paper_controls||[]),...(state.commands||[])]).slice(0,3);
    renderActivity(commands,recent);
    if(!recent.length){const row=document.createElement('li');row.textContent='Sin solicitudes recientes.';commands.append(row);}
    const candidate=state.snapshot?.bot_update;
    const activeJob=(state.jobs||[]).some(j=>['pending','running'].includes(j.status));
    const usable=candidate&&!state.stale&&candidate.expires>Date.now()/1000;
    document.getElementById('installBotUpdate').disabled=!(usable&&candidate.enabled&&!activeJob);
    const restore=state.snapshot?.bot_restore;
    document.getElementById('restoreBotVersion').disabled=!(restore?.enabled&&!state.stale&&!activeJob);
    document.getElementById('botUpdateMessage').textContent=usable?
      `Bot ${candidate.version} · revisión ${candidate.commit} · firma verificada en Windows.${candidate.enabled?'':' Instalación pendiente de preparar en Windows.'}`:
      'Busca una actualización firmada; la verificación se realizará en Windows.';
    document.getElementById('portalLogin').hidden=true;document.querySelector('.shell').hidden=false;
    return state;
  }).finally(()=>{portalPending=null;});
  return portalPending;
}
window.portalApi=async(path,options={})=>{
  if(!remotePortal){
    const response=await fetch(path,{...options,cache:'no-store'});
    if(!response.ok)throw new Error(`API local: ${response.status}`);
    return response.json();
  }
  if(options.method==='POST'){
    if(['/api/paper/risk-profile','/api/paper/close-position','/api/operations/model','/api/operations/restart','/api/testnet/buy','/api/testnet/close','/api/testnet/reconcile'].includes(path)){
      const state=await portalState();
      if(state.stale||state.snapshot?.paper_controls!==true)throw new Error('Controles PAPER pendientes de conexión de Windows');
      if((path.startsWith('/api/operations/')||path.startsWith('/api/testnet/'))&&state.snapshot?.operations_controls!==true)throw new Error('Actualiza y repara el agente de Windows antes de usar esta opción');
      let payload;
      try{payload=JSON.parse(options.body);}catch{throw new Error('Solicitud PAPER inválida');}
      const result=await portalRequest('/v1/paper-controls',{
        action:({
          '/api/paper/risk-profile':'risk_profile','/api/paper/close-position':'paper_close',
          '/api/operations/model':'ai_model','/api/operations/restart':'restart_engine',
          '/api/testnet/buy':'testnet_buy','/api/testnet/close':'testnet_close',
          '/api/testnet/reconcile':'testnet_reconcile'
        })[path],payload,request_id:crypto.randomUUID()});
      portalCacheAt=0;return result;
    }
    if(path==='/api/research/run'){
      const state=await portalState();
      if(state.stale)throw new Error('Windows sin conexión reciente');
      const result=await portalRequest('/v1/jobs',{action:'research',request_id:crypto.randomUUID()});
      portalCacheAt=0;return result;
    }
    if(path==='/api/kill'||path==='/api/resume'){
      const state=await portalState();
      if(state.stale && path==='/api/resume')throw new Error('Windows sin conexión reciente');
      const result=await portalRequest('/v1/commands',{action:path==='/api/kill'?'kill':'resume',request_id:crypto.randomUUID()});
      portalCacheAt=0;return result;
    }
    throw new Error('Esta acción aún requiere el servicio supervisado de Windows');
  }
  const state=await portalState();
  if(path==='/api/research/status'){
    const job=(state.jobs||[]).find(item=>item.action==='research');
    const error=job?.status==='failed'?job.message:(job?.status==='expired'?'La solicitud venció antes de llegar a Windows':null);
    return {running:!!job&&['pending','running'].includes(job.status),error};
  }
  const data=state.snapshot?.dashboard;
  if(!data)throw new Error('Esperando la primera sincronización del panel completo');
  if(!portalRoute[path])throw new Error('Ruta no disponible');
  return structuredClone(data[portalRoute[path]]??{});
};
window.paperControlsAvailable=()=>!remotePortal || !!(portalCache&&!portalCache.stale&&portalCache.snapshot?.paper_controls===true);
document.addEventListener('DOMContentLoaded',()=>{
  if(!remotePortal)document.getElementById('installBotUpdate').disabled=false;
  if(!remotePortal)document.getElementById('restoreBotVersion').disabled=false;
  document.getElementById('portalLogin').hidden=!remotePortal;
  document.querySelector('.shell').hidden=remotePortal;
  document.getElementById('portalLogout').hidden=!remotePortal;
  if(!remotePortal)document.querySelector('.activity-strip').hidden=true;
  document.getElementById('portalConnection').textContent=remotePortal?'Conectando al portal':'Conexión local · datos directos de Windows';
  const optionsButton=document.getElementById('optionsButton'),optionsMenu=document.getElementById('optionsMenu');
  function showOptions(open){optionsMenu.hidden=!open;optionsButton.setAttribute('aria-expanded',String(open));}
  optionsButton.onclick=()=>showOptions(optionsMenu.hidden);
  document.getElementById('diagnosticsButton').onclick=()=>{
    showOptions(false);
    const panel=document.getElementById('diagnosticsPanel');
    panel.open=true;
    panel.scrollIntoView({behavior:'smooth',block:'start'});
  };
  document.getElementById('modelSettingsButton').onclick=()=>{
    showOptions(false);
    const panel=document.getElementById('modelSettingsPanel');panel.hidden=false;
    panel.scrollIntoView({behavior:'smooth',block:'start'});
  };
  document.getElementById('closeModelSettings').onclick=()=>document.getElementById('modelSettingsPanel').hidden=true;
  document.getElementById('testnetOptionsButton').onclick=()=>{
    showOptions(false);const panel=document.getElementById('testnetPanel');panel.hidden=false;
    panel.scrollIntoView({behavior:'smooth',block:'start'});
    window.dispatchEvent(new Event('testnet-open'));
  };
  document.getElementById('closeTestnetPanel').onclick=()=>document.getElementById('testnetPanel').hidden=true;
  async function operationalAction(path,payload,question){
    if(!confirm(question))return;
    const startedAt=Date.now()/1000;
    const button=document.getElementById(path.endsWith('model')?'applyAiModel':'restartMotor');
    const message=document.getElementById('modelSettingsMessage');
    button.disabled=true;message.textContent='Esperando la comprobación de Windows…';
    try{
      const result=await window.portalApi(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      message.textContent=result.status==='pending'?'Solicitud enviada. Revisa el resultado en Actividad y el modelo efectivo en el panel.':'Windows confirmó la operación.';
      if(!remotePortal)setTimeout(async()=>{
        try{const state=await window.portalApi('/api/operations/last');
          if(state.at&&state.at>startedAt)message.textContent=state.status==='completed'?'Windows confirmó la operación.':
            `Windows no completó la acción (${state.reason||'revisar estado'}).`;}
        catch{}
      },4500);
    }catch(error){message.textContent=error.message;}
    finally{button.disabled=false;portalCacheAt=0;}
  }
  document.getElementById('applyAiModel').onclick=()=>operationalAction('/api/operations/model',
    {model:document.getElementById('aiModelChoice').value},'¿Verificar el modelo seleccionado y reiniciar el motor PAPER?');
  document.getElementById('restartMotor').onclick=()=>operationalAction('/api/operations/restart',{},
    '¿Reiniciar el motor PAPER? Puede interrumpir la vigilancia durante unos segundos.');
  let nextHistoryPage=0,historyBusy=false;
  async function loadHistory(reset=false){
    if(historyBusy)return;
    if(reset){nextHistoryPage=0;document.getElementById('historyRows').replaceChildren();}
    if(nextHistoryPage===null)return;
    historyBusy=true;
    const more=document.getElementById('loadMoreHistory'),message=document.getElementById('historyMessage');
    more.disabled=true;message.textContent='Cargando historial…';
    try{
      const page=nextHistoryPage,epoch=portalEpoch;
      const data=await portalRequest(`/v1/activity/${page}`);
      if(epoch!==portalEpoch)return;
      renderActivity(document.getElementById('historyRows'),data.items);
      nextHistoryPage=data.next_page;
      more.hidden=nextHistoryPage===null;
      message.textContent=page===0&&!data.items.length?'Aún no hay actividad.':`Historial disponible durante ${data.retention_days} días.`;
    }catch(error){message.textContent=error.message;}
    finally{historyBusy=false;more.disabled=false;}
  }
  document.getElementById('historyButton').onclick=async()=>{
    showOptions(false);document.getElementById('passwordPanel').hidden=true;document.getElementById('updatePanel').hidden=true;
    if(!remotePortal){window.open('https://crypto-paper-private-portal.jlboper.workers.dev/','_blank','noopener');return;}
    document.getElementById('historyPanel').hidden=false;
    document.getElementById('historyPanel').scrollIntoView({behavior:'smooth',block:'start'});
    await loadHistory(true);
  };
  document.getElementById('loadMoreHistory').onclick=()=>loadHistory();
  document.getElementById('closeHistory').onclick=()=>{document.getElementById('historyPanel').hidden=true;};
  document.getElementById('portalLogin').onsubmit=async e=>{
    e.preventDefault();const button=document.getElementById('portalLoginButton');button.disabled=true;
    try{const parameters=await portalRequest('/v1/auth-parameters');const proof=await portalPasswordProof(document.getElementById('portalPassword').value,parameters);const result=await portalRequest('/v1/login',{password:proof});portalCsrf=result.csrf;document.getElementById('portalPassword').value='';portalCacheAt=0;await portalState();window.dispatchEvent(new Event('portal-ready'));}
    catch(error){document.getElementById('portalLoginMessage').textContent=error.message;}
    finally{button.disabled=false;}
  };
  document.getElementById('portalLogout').onclick=async()=>{showOptions(false);await portalRequest('/v1/logout',{});portalLocked();};
  document.getElementById('portalPasswordButton').onclick=()=>{
    showOptions(false);document.getElementById('updatePanel').hidden=true;
    if(!remotePortal){window.open('https://crypto-paper-private-portal.jlboper.workers.dev/#password','_blank','noopener');return;}
    document.getElementById('passwordPanel').hidden=false;
    document.getElementById('passwordMessage').textContent='';
  };
  document.getElementById('cancelPassword').onclick=()=>{
    document.getElementById('passwordPanel').hidden=true;
    for(const id of ['currentPassword','newPassword','confirmPassword'])document.getElementById(id).value='';
  };
  document.getElementById('passwordForm').onsubmit=async event=>{
    event.preventDefault();const button=document.getElementById('savePassword'),message=document.getElementById('passwordMessage');
    const current=document.getElementById('currentPassword'),next=document.getElementById('newPassword'),confirmation=document.getElementById('confirmPassword');
    if(next.value!==confirmation.value){message.textContent='Las contraseñas nuevas no coinciden';return;}
    if(next.value.length<16||next.value.length>128||next.value.trim()!==next.value){message.textContent='Usa de 16 a 128 caracteres, sin espacios al principio o al final';return;}
    if(next.value===current.value){message.textContent='Elige una contraseña diferente';return;}
    button.disabled=true;message.textContent='Guardando…';
    try{
      await portalState();const parameters=await portalRequest('/v1/auth-parameters');
      const salt=btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
      const currentProof=await portalPasswordProof(current.value,parameters);
      const newProof=await portalPasswordProof(next.value,{scheme:'pbkdf2-sha256',salt,iterations:600000});
      await portalRequest('/v1/password',{current_password:currentProof,new_password:newProof,salt});
      portalLocked();document.getElementById('portalLoginMessage').textContent='Contraseña cambiada. Entra con tu nueva contraseña.';
    }catch(error){message.textContent=error.message;}
    finally{current.value='';next.value='';confirmation.value='';button.disabled=false;}
  };
  window.addEventListener('portal-ready',()=>{if(location.hash==='#password')document.getElementById('passwordPanel').hidden=false;});
  let updatePending=false,lastUpdatesAt=0;
  async function checkAllUpdates(){
    if(!remotePortal){
      const output=document.getElementById('updateMessage');output.replaceChildren();
      const link=document.createElement('a');link.href='https://crypto-paper-private-portal.jlboper.workers.dev/#updates';
      link.textContent='Abrir el portal privado para revisar y autorizar con tu sesión segura';
      link.rel='noopener';link.target='_blank';output.append(link);return;
    }
    if(updatePending || Date.now()-lastUpdatesAt<30000)return;
    updatePending=true;const button=document.getElementById('checkAllUpdates');button.disabled=true;
    const output=document.getElementById('updateMessage'),releases=document.getElementById('updateReleases'),botOutput=document.getElementById('botUpdateMessage');
    releases.replaceChildren();output.textContent='Consultando versiones y pruebas en GitHub…';
    botOutput.textContent='Solicitando a Windows la verificación del paquete firmado…';
    const epoch=portalEpoch;
    try{
      const state=await portalState();
      const [portalResult,botResult]=await Promise.allSettled([
        portalRequest('/v1/updates'),
        state.stale?Promise.reject(new Error('Windows debe estar conectado')):
          portalRequest('/v1/jobs',{action:'update_check',request_id:crypto.randomUUID()}),
      ]);
      if(epoch!==portalEpoch)return;
      if(portalResult.status==='fulfilled'){
        const data=portalResult.value;output.textContent=data.message;
        for(const run of data.runs){
        const card=document.createElement('article'),title=document.createElement('h3'),detail=document.createElement('p'),link=document.createElement('a');
        title.textContent=run.title;
        detail.textContent=`Portal y paquete del bot · commit ${run.sha} · autor ${run.actor} · intento ${run.attempt} · ${run.conclusion||run.status}`;
        link.href=run.url;link.textContent='Ver cambios y pruebas en GitHub';link.target='_blank';link.rel='noopener';
        const commit=document.createElement('a');commit.href=run.commit_url;commit.textContent='Ver commit exacto';commit.target='_blank';commit.rel='noopener';
        card.append(title,detail,commit,link);
        if(run.blocked){const message=document.createElement('p');message.textContent=run.blocked;card.append(message);}
        if(run.published){const published=document.createElement('p');published.textContent='Esta revisión ya está publicada.';card.append(published);}
        if(run.review_on_github){
          const approve=document.createElement('a');approve.className='primary';approve.textContent='Revisar y autorizar publicación en GitHub';
          approve.href=run.url;approve.target='_blank';approve.rel='noopener';card.append(approve);
        }
          releases.append(card);
        }
      }else output.textContent=portalResult.reason.message;
      if(botResult.status==='fulfilled'){
        portalCacheAt=0;botOutput.textContent='Solicitud enviada. Windows verificará la firma y mostrará aquí la versión disponible.';
      }else botOutput.textContent=botResult.reason.message;
      if(portalResult.status==='fulfilled'||botResult.status==='fulfilled')lastUpdatesAt=Date.now();
    }catch(error){output.textContent=error.message;}
    finally{updatePending=false;button.disabled=false;}
  }
  function showUpdateCenter(){
    showOptions(false);document.getElementById('passwordPanel').hidden=true;document.getElementById('historyPanel').hidden=true;
    const panel=document.getElementById('updatePanel');panel.hidden=false;
    if(remotePortal&&document.querySelector('.shell').hidden)document.getElementById('updateMessage').textContent='Inicia sesión para revisar las versiones disponibles.';
    if(!document.querySelector('.shell').hidden)panel.scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function installBotUpdate(){
    if(!remotePortal){window.open('https://crypto-paper-private-portal.jlboper.workers.dev/#updates','_blank','noopener');return;}
    const output=document.getElementById('botUpdateMessage');
    const button=document.getElementById('installBotUpdate');
    let submitted=false;button.disabled=true;
    try{
      const state=await portalState();if(state.stale)throw new Error('Windows debe estar conectado');
      button.disabled=true;
      const candidate=state.snapshot?.bot_update;
      if(!candidate?.enabled||candidate.expires<=Date.now()/1000)throw new Error('Primero verifica una versión disponible');
      if(!confirm(`¿Instalar el bot ${candidate.version}, revisión ${candidate.commit}? El motor PAPER se reiniciará y se recuperará la versión anterior si falla el arranque.`))return;
      const body={action:'update_install',request_id:crypto.randomUUID(),release_id:candidate.release_id};
      await portalRequest('/v1/jobs',body);submitted=true;portalCacheAt=0;
      output.textContent='Solicitud enviada. El resultado aparecerá en las solicitudes remotas.';
    }catch(error){output.textContent=error.message;}
    finally{if(!submitted)button.disabled=false;}
  }
  async function restoreBotVersion(){
    showOptions(false);
    if(!remotePortal){window.open('https://crypto-paper-private-portal.jlboper.workers.dev/','_blank','noopener');return;}
    const button=document.getElementById('restoreBotVersion');
    button.disabled=true;
    let submitted=false;
    try{
      const state=await portalState();
      const offer=state.snapshot?.bot_restore;
      if(state.stale||!offer?.enabled||(state.jobs||[]).some(j=>['pending','running'].includes(j.status)))throw new Error('Windows aún no ofrece una versión anterior verificable');
      if(!confirm(`¿Restaurar el código del bot de ${offer.current_version} a ${offer.version}? El motor PAPER se reiniciará. Se conservarán los saldos y las operaciones actuales.`))return;
      await portalRequest('/v1/jobs',{action:'update_restore',request_id:crypto.randomUUID(),release_id:offer.restore_id});
      submitted=true;
      portalCacheAt=0;
      document.getElementById('botUpdateMessage').textContent='Restauración solicitada. Windows comprobará el arranque y conservará los datos financieros.';
    }catch(error){document.getElementById('botUpdateMessage').textContent=error.message;}
    finally{portalCacheAt=0;if(!submitted)button.disabled=false;}
  }
  document.getElementById('checkAllUpdates').onclick=checkAllUpdates;
  document.getElementById('installBotUpdate').onclick=installBotUpdate;
  document.getElementById('restoreBotVersion').onclick=restoreBotVersion;
  document.getElementById('updateButton').onclick=showUpdateCenter;
  document.getElementById('closeUpdatePanel').onclick=()=>{document.getElementById('updatePanel').hidden=true;};
  if(location.hash==='#updates')showUpdateCenter();
  window.addEventListener('hashchange',()=>{if(location.hash==='#updates')showUpdateCenter();});
  window.addEventListener('portal-ready',()=>{if(location.hash==='#updates'){lastUpdatesAt=0;showUpdateCenter();}});
});
