// Explicit provisioning; no secrets go to stdout and no active bot files are edited.
import { randomBytes, createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export async function provision(directory, origin) {
  const url = new URL(origin);
  if (url.protocol!=='https:' || url.origin!==origin || url.username || !url.hostname.endsWith('.workers.dev')) throw new Error('Use the exact HTTPS workers.dev origin');
  const owner=randomBytes(32).toString('base64url'), device=randomBytes(32).toString('base64url');
  const hash=value=>createHash('sha256').update(value).digest('hex');
  await mkdir(directory,{mode:0o700,recursive:false});
  const files={
    'worker-secrets.json':JSON.stringify({OWNER_KEY_HASH:hash(owner),DEVICE_KEY_HASH:hash(device)},null,2),
    'owner-access-key.txt':owner+'\n',
    'windows-agent.env':`PORTAL_ORIGIN=${origin}\nPORTAL_DEVICE_TOKEN=${device}\n`,
  };
  for(const [name,body]of Object.entries(files))await writeFile(resolve(directory,name),body,{mode:0o600,flag:'wx'});
  return Object.keys(files);
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  const origin=process.argv[2];
  if(!origin)throw new Error('Usage: node scripts/provision.mjs https://name.account.workers.dev');
  await provision(resolve('.secrets'),origin);
  console.log('Credentials created in .secrets. No secrets printed. Review Windows ACL before sharing this folder.');
}
