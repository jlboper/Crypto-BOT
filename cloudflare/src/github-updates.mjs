// Read-only release discovery. Approval remains on GitHub's protected
// environment so no GitHub write credential exists inside deployable code.
const repo='jlboper/Crypto-BOT';
const workflow='.github/workflows/portal-release.yml';
export class UpdateError extends Error {
  constructor(status,message){super(message);this.status=status;}
}
export function githubUpdates(env={},transport=fetch){
  async function api(path){
    const response=await transport('https://api.github.com/repos/'+repo+path,{
      method:'GET',redirect:'error',signal:AbortSignal.timeout(10000),
      headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'CryptoPaperPortal'}});
    if(!response.ok)throw new UpdateError(response.status===403||response.status===429?429:502,'GitHub no pudo completar la consulta; inténtalo más tarde');
    const content=await response.text();
    if(content.length>500000)throw new UpdateError(502,'Respuesta de GitHub demasiado grande');
    try{return content?JSON.parse(content):null;}
    catch{throw new UpdateError(502,'Respuesta de GitHub inválida');}
  }
  function valid(run,head){return run.path===workflow&&run.head_branch==='main'&&run.event==='push'&&run.head_repository?.full_name===repo&&run.head_sha===head&&/^[a-f0-9]{40}$/.test(run.head_sha);}
  function display(run){return {id:run.id,attempt:run.run_attempt,sha:run.head_sha,title:String(run.display_title||'Actualización del portal').slice(0,200),actor:String(run.actor?.login||'desconocido').slice(0,80),created_at:run.created_at,status:run.status,conclusion:run.conclusion,url:`https://github.com/${repo}/actions/runs/${run.id}`,commit_url:`https://github.com/${repo}/commit/${run.head_sha}`,target:'portal',review_on_github:false};}
  return {async list(){
    const [data,ref]=await Promise.all([api('/actions/workflows/portal-release.yml/runs?branch=main&event=push&per_page=10'),api('/git/ref/heads/main')]);
    const head=ref?.object?.sha;
    if(!/^[a-f0-9]{40}$/.test(head||''))throw new UpdateError(502,'GitHub no informó la revisión actual');
    const runs=[];
    for(const run of data.workflow_runs.filter(item=>valid(item,head)).slice(0,3)){
      const item=display(run);
      if(run.status==='waiting'){
        const jobs=await api(`/actions/runs/${run.id}/attempts/${run.run_attempt}/jobs?per_page=100`);
        item.review_on_github=jobs.total_count<=100&&jobs.jobs.some(job=>job.name==='validate'&&job.status==='completed'&&job.conclusion==='success');
      }
      item.published=env.PORTAL_COMMIT===run.head_sha;
      runs.push(item);
    }
    return {configured:true,runs,message:'El portal muestra únicamente la ejecución del commit actual de main. La autorización final se realiza en el entorno protegido de GitHub.'};
  }};
}
