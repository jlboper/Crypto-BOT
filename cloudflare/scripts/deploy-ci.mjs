// Runs only in the approved GitHub environment; no owner/device keys in CI.
import {spawn} from 'node:child_process';
import {readFile,writeFile,readdir} from 'node:fs/promises';
import {configure} from './configure.mjs';
import {checkMigrations} from './check-migrations.mjs';
if(process.env.GITHUB_REPOSITORY!=='jlboper/Crypto-BOT'||process.env.GITHUB_REF!=='refs/heads/main'||!/^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA||''))throw Error('Unexpected release source');
if(!process.env.CLOUDFLARE_API_TOKEN)throw Error('Environment deployment credential not configured');
if(process.env.DEPLOYMENT_ENABLED!=='portal-production-v1')throw Error('Protected environment gate not configured');
const template=JSON.parse(await readFile('wrangler.jsonc','utf8'));
const config=configure(template,{accountId:process.env.CLOUDFLARE_ACCOUNT_ID,databaseId:process.env.PORTAL_D1_ID,origin:process.env.PORTAL_ORIGIN});
config.vars.PORTAL_COMMIT=process.env.GITHUB_SHA;
await writeFile('wrangler.ci.json',JSON.stringify(config));
async function wrangler(args,{capture=false}={}){
  const child=spawn(process.execPath,['node_modules/wrangler/bin/wrangler.js',...args,'--config','wrangler.ci.json'],{shell:false,stdio:capture?['ignore','pipe','pipe']:'inherit',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
  let output='';if(capture){child.stdout.on('data',part=>output+=part);child.stderr.on('data',part=>output+=part);}
  await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(Error('Deployment command failed')));});
  return output;
}
const migrationNames=(await readdir('migrations')).filter(name=>name.endsWith('.sql')).sort();
const migrationOptions={accountId:config.account_id,databaseId:config.d1_databases[0].database_id,
  token:process.env.CLOUDFLARE_API_TOKEN,expected:migrationNames};
const addPaperControls='0005_paper_controls.sql';
const applied=await checkMigrations({...migrationOptions,allowPending:[addPaperControls]});
if(!applied.includes(addPaperControls)){
  // Additive table only. The protected publication gate covers the schema and
  // code together; Wrangler captures a D1 backup before applying the migration.
  await wrangler(['d1','migrations','apply',config.d1_databases[0].database_name,'--remote']);
}
await checkMigrations(migrationOptions);
await wrangler(['deploy','--dry-run']);
let deployed=false;
try{
  await wrangler(['deploy','--strict']);deployed=true;
  let healthy=false;
  for(let attempt=0;attempt<8&&!healthy;attempt++){
    if(attempt)await new Promise(resolve=>setTimeout(resolve,5000));
    try{const response=await fetch(config.vars.PORTAL_ORIGIN+'/v1/health',{redirect:'error',signal:AbortSignal.timeout(15000)});const health=response.ok?await response.json():{};healthy=health.commit===process.env.GITHUB_SHA&&health.status==='ok';}catch{}
  }
  if(!healthy)throw Error('Post-deployment health failed');
}catch(error){
  if(deployed)await wrangler(['rollback','--message',`Automatic rollback after health failure for ${process.env.GITHUB_SHA}`]);
  throw error;
}
console.log('Approved portal commit published and health verified. Windows bot was not installed.');
