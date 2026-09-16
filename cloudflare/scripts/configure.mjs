import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function configure(template, { accountId, databaseId, origin }) {
  if (!/^[a-f0-9]{32}$/.test(accountId||'')) throw new Error('A Cloudflare account ID is required');
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(databaseId||'') || /^0+-0+-0+-0+-0+$/.test(databaseId)) throw new Error('A real D1 database ID is required');
  const url=new URL(origin);
  if (url.protocol!=='https:' || url.origin!==origin || !/^[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev$/.test(url.hostname) || !url.hostname.startsWith(template.name+'.')) throw new Error('Use the exact workers.dev URL for this Worker name');
  const config=structuredClone(template);
  config.account_id=accountId;
  config.vars.PORTAL_ORIGIN=origin;
  config.d1_databases[0].database_id=databaseId;
  return config;
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  const [accountId,databaseId,origin]=process.argv.slice(2);
  const template=JSON.parse(await readFile('wrangler.jsonc','utf8'));
  const config=configure(template,{accountId,databaseId,origin});
  await writeFile('wrangler.production.json',JSON.stringify(config,null,2)+'\n',{flag:'wx'});
  console.log('Production configuration created; no resources deployed or secrets printed.');
}
