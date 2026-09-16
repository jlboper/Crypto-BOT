/* One UI, local APIs or authenticated remote snapshots. No credentials in URLs. */
const remotePortal = !['127.0.0.1','localhost','[::1]','::1'].includes(location.hostname);
let portalCsrf = '', portalPending, portalCache, portalCacheAt = 0, portalEpoch=0;
const portalRoute = {'/api/status':'status','/api/positions':'positions','/api/trades':'trades','/api/ai-reviews':'reviews','/api/equity':'equity','/api/events':'events','/api/research':'research','/api/research/status':'research_state','/api/updates':'updates'};
function portalLocked(){
  portalEpoch++;
  portalCsrf='';portalPending=null;portalCache=null;portalCacheAt=0;
  document.getElementById('portalLogin').hidden=false;
  document.querySelector('.shell').hidden=true;
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
async function portalState(){
  if(portalCache && Date.now()-portalCacheAt<5000)return portalCache;
  const epoch=portalEpoch;
  if(!portalPending)portalPending=portalRequest('/v1/status').then(state=>{
    if(epoch!==portalEpoch)throw new Error('Sesión finalizada');
    portalCsrf=state.csrf;portalCache=state;portalCacheAt=Date.now();
    document.getElementById('portalConnection').textContent=state.stale?'Windows sin conexión reciente':'Windows conectado · sincronización HTTPS';
    const commands=document.getElementById('portalCommands');commands.replaceChildren();
    const labels={pending:'Pendiente',applied:'Confirmado por Windows',expired:'Vencido',superseded:'Sustituido',running:'En curso',completed:'Completado',failed:'Falló'};
    for(const item of state.commands||[]){const row=document.createElement('li');row.textContent=`#${item.id} ${item.action==='kill'?'Pausar':'Reanudar'} · ${labels[item.status]||item.status}`;commands.append(row);}
    const actions={research:'Research Lab',update_check:'Verificar bot',update_install:'Actualizar bot'};
    for(const item of state.jobs||[]){const row=document.createElement('li');row.textContent=`#${item.id} ${actions[item.action]||item.action} · ${labels[item.status]||item.status} · ${item.message||''}`;commands.append(row);}
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
  return structuredClone(data[portalRoute[path]]);
};
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('portalLogin').hidden=!remotePortal;
  document.querySelector('.shell').hidden=remotePortal;
  document.getElementById('portalLogout').hidden=!remotePortal;
  document.getElementById('portalConnection').textContent=remotePortal?'Conectando al portal':'Conexión local · datos directos de Windows';
  document.getElementById('portalLogin').onsubmit=async e=>{
    e.preventDefault();const button=document.getElementById('portalLoginButton');button.disabled=true;
    try{const result=await portalRequest('/v1/login',{password:document.getElementById('portalPassword').value.trim()});portalCsrf=result.csrf;document.getElementById('portalPassword').value='';portalCacheAt=0;await portalState();window.dispatchEvent(new Event('portal-ready'));}
    catch(error){document.getElementById('portalLoginMessage').textContent=error.message;}
    finally{button.disabled=false;}
  };
  document.getElementById('portalLogout').onclick=async()=>{await portalRequest('/v1/logout',{});portalLocked();};
  let updatePending=false,lastUpdatesAt=0;
  async function checkUpdates(){
    if(!remotePortal){
      const output=document.getElementById('updateMessage');output.replaceChildren();
      const link=document.createElement('a');link.href='https://crypto-paper-private-portal.jlboper.workers.dev/';
      link.textContent='Abrir el portal privado para revisar y autorizar con tu sesión segura';
      link.rel='noopener';link.target='_blank';output.append(link);return;
    }
    if(updatePending || Date.now()-lastUpdatesAt<30000)return;
    updatePending=true;const button=document.getElementById('checkUpdates');button.disabled=true;
    const output=document.getElementById('updateMessage'), releases=document.getElementById('updateReleases');
    releases.replaceChildren();output.textContent='Consultando versiones y pruebas en GitHub…';
    const epoch=portalEpoch;
    try{
      await portalState();const data=await portalRequest('/v1/updates');
      if(epoch!==portalEpoch)return;
      output.textContent=data.message;lastUpdatesAt=Date.now();
      for(const run of data.runs){
        const card=document.createElement('article'),title=document.createElement('h3'),detail=document.createElement('p'),link=document.createElement('a');
        title.textContent=run.title;
        detail.textContent=`Portal Cloudflare · commit ${run.sha} · autor ${run.actor} · intento ${run.attempt} · ${run.conclusion||run.status}`;
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
    }catch(error){output.textContent=error.message;}
    finally{updatePending=false;button.disabled=false;}
  }
  function showUpdateCenter(){
    const panel=document.getElementById('updatePanel');panel.hidden=false;
    if(remotePortal&&document.querySelector('.shell').hidden)document.getElementById('updateMessage').textContent='Inicia sesión para revisar las versiones disponibles.';
    else checkUpdates();
    if(!document.querySelector('.shell').hidden)panel.scrollIntoView({behavior:'smooth',block:'start'});
  }
  document.getElementById('checkUpdates').onclick=checkUpdates;
  document.getElementById('updateButton').onclick=async()=>{
    showUpdateCenter();
  };
  if(location.hash==='#updates')showUpdateCenter();
  window.addEventListener('hashchange',()=>{if(location.hash==='#updates')showUpdateCenter();});
  window.addEventListener('portal-ready',()=>{if(location.hash==='#updates'){lastUpdatesAt=0;checkUpdates();document.getElementById('updatePanel').scrollIntoView({behavior:'smooth',block:'start'});}});
});
