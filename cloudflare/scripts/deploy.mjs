// Run only after the owner has selected the Workers Free plan and authenticated.
// Never requests an upgrade, temporary account, paid product or custom domain.
import { spawn } from 'node:child_process';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { configure } from './configure.mjs';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const wrangler=resolve(root,'node_modules/wrangler/bin/wrangler.js');
async function run(args){
  const child=spawn(process.execPath,args,{cwd:root,stdio:'inherit',shell:false,env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
  await new Promise((done,fail)=>{child.once('error',fail);child.once('exit',code=>code===0?done():fail(new Error('Command failed; deployment stopped')));});
}
const template=JSON.parse(await readFile(resolve(root,'wrangler.jsonc'),'utf8'));
const config=JSON.parse(await readFile(resolve(root,'wrangler.production.json'),'utf8'));
const expected=configure(template,{accountId:config.account_id,databaseId:config.d1_databases?.[0]?.database_id,origin:config.vars?.PORTAL_ORIGIN});
if(JSON.stringify(config)!==JSON.stringify(expected))throw new Error('Production config differs from the reviewed minimal template');
const secrets=JSON.parse(await readFile(resolve(root,'.secrets/worker-secrets.json'),'utf8'));
if(Object.keys(secrets).sort().join(',')!=='DEVICE_KEY_HASH,OWNER_KEY_HASH' || !Object.values(secrets).every(v=>/^[a-f0-9]{64}$/.test(v)) || secrets.DEVICE_KEY_HASH===secrets.OWNER_KEY_HASH)throw new Error('Invalid or unseparated portal secrets');
const tests=(await readdir(resolve(root,'tests'))).filter(n=>n.endsWith('.test.mjs')).map(n=>'tests/'+n);
await run(['--test',...tests]);
await run([wrangler,'deploy','--dry-run','--config','wrangler.production.json']);
if(!process.argv.includes('--apply')){
  console.log('Checks passed. Nothing deployed. After confirming Workers Free, use --apply.');
}else{
  // Migration is additive and scoped to this dedicated database; it never touches trader.db.
  await run([wrangler,'d1','migrations','apply',config.d1_databases[0].database_name,'--remote','--config','wrangler.production.json']);
  await run([wrangler,'deploy','--strict','--config','wrangler.production.json','--secrets-file','.secrets/worker-secrets.json']);
  await writeFile(resolve(root,'deployment-state.json'),JSON.stringify({origin:config.vars.PORTAL_ORIGIN,at:new Date().toISOString(),windows_agent_started:false},null,2));
  console.log('Portal deployed. This command does not start or restart the Windows agent or trading engine.');
}
