// Runs only in the protected GitHub environment. Never logs credentials/OIDC.
import {readFile,writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {requestReleaseSignature} from './retry_release_signature.mjs';
const origin='https://crypto-paper-private-portal.jlboper.workers.dev';
const repo='jlboper/Crypto-BOT';
const sha=process.env.GITHUB_SHA;
if(process.env.GITHUB_REPOSITORY!==repo||process.env.GITHUB_REF!=='refs/heads/main'||process.env.GITHUB_EVENT_NAME!=='push'||!/^[a-f0-9]{40}$/.test(sha||''))throw Error('Protected main push required');
const headers={Authorization:`Bearer ${process.env.GITHUB_TOKEN}`,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'};
async function api(path,method='GET',body){
  const response=await fetch('https://api.github.com/repos/'+repo+path,{method,headers,redirect:'error',...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(60000)});
  if(response.status===404&&method==='GET')return null;
  if(!response.ok)throw Error(`GitHub release operation failed (${response.status})`);
  return response.json();
}
const run=await api('/actions/runs/'+process.env.GITHUB_RUN_ID);
const expires=Math.floor(Date.parse(run.created_at)/1000)+14*86400;
const built=spawnSync('python',['scripts/build_bot_release.py','--commit',sha,'--sequence',process.env.GITHUB_RUN_ID,'--expires',String(expires),'--output','dist/bot.zip'],{stdio:'inherit'});
if(built.status!==0)throw Error('Package build failed');
const manifest=JSON.parse(await readFile('dist/bot.manifest.json','utf8'));
const current=await fetch(origin+'/v1/releases/latest',{redirect:'error'});
if(current.ok){
  const previous=(await current.json()).manifest;
  const parts=v=>v.split('.').map(Number);
  const a=parts(manifest.version),b=parts(previous.version);
  const comparison=a[0]-b[0]||a[1]-b[1]||a[2]-b[2];
  if(comparison===0){
    if(JSON.stringify(Object.entries(manifest.files).sort())!==JSON.stringify(Object.entries(previous.files).sort()))throw Error('Bot files changed without a version increment in pyproject.toml');
    console.log('Identical bot version already published.');process.exit(0);
  }
  if(comparison<0)throw Error('Bot version downgrade rejected');
}else if(current.status!==404)throw Error('Cannot verify current bot release');
// Upload the immutable-named package before publishing its signed manifest.
const ref=await api('/git/ref/heads/bot-releases');
const parent=ref?.object?.sha;
const previous=parent?await api('/git/commits/'+parent):null;
const blob=await api('/git/blobs','POST',{content:(await readFile('dist/bot.zip')).toString('base64'),encoding:'base64'});
const tree=await api('/git/trees','POST',{...(previous?{base_tree:previous.tree.sha}:{}),tree:[{path:`packages/${sha}.zip`,mode:'100644',type:'blob',sha:blob.sha}]});
const commit=await api('/git/commits','POST',{message:`Signed PAPER bot ${manifest.version} from ${sha}`,tree:tree.sha,parents:parent?[parent]:[]});
if(parent)await api('/git/refs/heads/bot-releases','PATCH',{sha:commit.sha,force:false});
else await api('/git/refs','POST',{ref:'refs/heads/bot-releases',sha:commit.sha});
const oidcURL=new URL(process.env.ACTIONS_ID_TOKEN_REQUEST_URL);
oidcURL.searchParams.set('audience',origin+'/bot-releases');
const oidcResponse=await fetch(oidcURL,{headers:{Authorization:`Bearer ${process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}`},redirect:'error'});
if(!oidcResponse.ok)throw Error('Publisher identity unavailable');
const oidc=await oidcResponse.json();
const envelope=await requestReleaseSignature(origin,oidc.value,manifest);
await writeFile('dist/bot.zip.manifest.json',JSON.stringify(envelope));
const verified=spawnSync('python',['-m','trader.update_manager','verify','--root','.', '--public-key','release-signing.pub','--package','dist/bot.zip','--manifest','dist/bot.zip.manifest.json'],{stdio:'inherit'});
if(verified.status!==0)throw Error('Published signature verification failed');
console.log(`Published signed PAPER bot ${manifest.version} (${sha})`);
