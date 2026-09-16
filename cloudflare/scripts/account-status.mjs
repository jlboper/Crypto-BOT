// Read-only preflight. Never print the OAuth credential or raw API responses.
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
const account=process.argv[2];
if(!/^[a-f0-9]{32}$/.test(account||''))throw new Error('Account ID required');
const config=await readFile(join(process.env.APPDATA,'xdg.config','.wrangler','config','default.toml'),'utf8');
const token=config.match(/^oauth_token\s*=\s*"([^"]+)"/m)?.[1];
if(!token)throw new Error('Run Wrangler login first');
for(const endpoint of ['subscriptions','workers/subdomain','workers/scripts','d1/database']){
  const response=await fetch(`https://api.cloudflare.com/client/v4/accounts/${account}/${endpoint}`,{headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(20000)});
  const data=await response.json();
  let result;
  if(data.success){
    if(endpoint==='subscriptions')result=data.result.map(s=>({product:s.rate_plan?.id,name:s.rate_plan?.public_name,price:s.price,currency:s.currency,state:s.state}));
    if(endpoint==='workers/subdomain')result={subdomain:data.result.subdomain};
    if(endpoint==='workers/scripts')result=data.result.map(s=>({id:s.id}));
    if(endpoint==='d1/database')result=data.result.map(s=>({name:s.name,uuid:s.uuid}));
  }
  console.log(JSON.stringify({endpoint,status:response.status,success:data.success,result,errorCodes:data.errors?.map(e=>e.code)}));
}
