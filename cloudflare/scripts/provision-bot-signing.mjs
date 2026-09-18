// One-time local setup. Private material is never written to stdout or GitHub.
import {generateKeyPairSync,createPrivateKey,createPublicKey,createHash} from 'node:crypto';
import {existsSync,readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
if(!process.argv.includes('--apply'))throw Error('Explicit --apply required');
if(!existsSync('.secrets'))throw Error('Provision the restricted local secrets directory first');
const privatePath='.secrets/bot-signing.pkcs8';
if(!existsSync(privatePath)){
  const keys=generateKeyPairSync('ed25519');
  writeFileSync(privatePath,keys.privateKey.export({format:'der',type:'pkcs8'}).toString('base64'),{flag:'wx',mode:0o600});
}
const encoded=readFileSync(privatePath,'utf8');
const key=createPrivateKey({key:Buffer.from(encoded,'base64'),format:'der',type:'pkcs8'});
const publicRaw=createPublicKey(key).export({format:'der',type:'spki'}).subarray(-32);
for(const [path,bytes] of [['../release-signing.pub',Buffer.from(publicRaw.toString('hex'))],['../data/trusted-update.pub',publicRaw]]){
  if(existsSync(path)&&!readFileSync(path).equals(bytes))throw Error('Existing trust key differs; refusing rotation');
  if(!existsSync(path))writeFileSync(path,bytes,{flag:'wx'});
}
const result=spawnSync(process.execPath,['node_modules/wrangler/bin/wrangler.js','secret','put','BOT_SIGNING_KEY','--config','wrangler.production.json'],{input:encoded,encoding:'utf8'});
if(result.status!==0)throw Error('Cloudflare signing-secret provisioning failed; no credentials printed');
console.log(JSON.stringify({signing_secret:'provisioned',public_key_sha256:createHash('sha256').update(publicRaw).digest('hex')}));
