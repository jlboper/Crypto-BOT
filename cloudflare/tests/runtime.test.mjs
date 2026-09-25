import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createHash,pbkdf2Sync,generateKeyPairSync,sign,verify } from 'node:crypto';
import {canonical} from '../src/bot-releases.mjs';

// Uses the exact Miniflare/workerd version pinned by Wrangler's lockfile.
const wranglerRequire = createRequire(import.meta.resolve('wrangler'));
const { Miniflare, convertV4MiniflareOptions } = wranglerRequire('miniflare');

test('real workerd + local D1: browser session -> command -> Windows sync -> ack', {timeout:60000}, async t=>{
  const origin='https://runtime.example.workers.dev';
  const owner='R'.repeat(43), device='S'.repeat(43);
  const hash=v=>createHash('sha256').update(v).digest('hex');
  const publisher=generateKeyPairSync('rsa',{modulusLength:2048}), signer=generateKeyPairSync('ed25519');
  const mf=new Miniflare(convertV4MiniflareOptions({modules:[
    {type:'ESModule',path:fileURLToPath(new URL('../src/worker.mjs',import.meta.url))},
    {type:'ESModule',path:fileURLToPath(new URL('../src/github-updates.mjs',import.meta.url))},
    {type:'ESModule',path:fileURLToPath(new URL('../src/password.mjs',import.meta.url))},
    {type:'ESModule',path:fileURLToPath(new URL('../src/bot-releases.mjs',import.meta.url))}],
    compatibilityDate:'2026-09-14',compatibilityFlags:['nodejs_compat'],
    bindings:{PORTAL_ORIGIN:origin,PORTAL_COMMIT:'d'.repeat(40),OWNER_KEY_HASH:hash(owner),DEVICE_KEY_HASH:hash(device),BOT_SIGNING_KEY:signer.privateKey.export({format:'der',type:'pkcs8'}).toString('base64')},
    d1Databases:{DB:'runtime-test-db'},outboundService:request=>request.url==='https://token.actions.githubusercontent.com/.well-known/jwks'?
      Response.json({keys:[{...publisher.publicKey.export({format:'jwk'}),kid:'runtime-key'}]}):new Response('Network disabled',{status:403})}));
  t.after(()=>mf.dispose());
  const db=await mf.getD1Database('DB');
  // D1 exec requires one statement per line; a single prepared batch keeps the migration atomic.
  const sql=['0001_portal.sql','0002_jobs.sql','0003_owner_password.sql','0004_bot_releases.sql','0005_paper_controls.sql'].map(name=>readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8')).join('\n');
  await db.batch(sql.split(';').map(s=>s.trim()).filter(Boolean).map(s=>db.prepare(s)));
  let cookie='',csrf='';
  async function call(path,body,headers={}){
    const response=await mf.dispatchFetch(origin+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:origin,Cookie:cookie,'X-CSRF-Token':csrf,...headers},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data=await response.json();return {status:response.status,headers:response.headers,body:data};
  }
  const logged=await call('/v1/login',{password:owner});assert.equal(logged.status,200,JSON.stringify(logged.body));
  cookie=logged.headers.get('set-cookie').split(';')[0];csrf=logged.body.csrf;
  assert.equal((await call('/v1/status')).status,200);
  const cmd=await call('/v1/commands',{action:'kill',request_id:'runtime-kill-command-01'});assert.equal(cmd.status,202);
  const snapshot={mode:'PAPER',equity:1000,cash:1000,exposure:0,positions:[],killed:false,last_cycle_at:new Date().toISOString(),ai_model:'gpt-5.6-luna',update_state:'manual_signed_install_only'};
  const received=await call('/v1/device/sync',{snapshot,acks:[]},{Authorization:`Bearer ${device}`});
  assert.equal(received.status,200);assert.equal(received.body.commands[0].id,cmd.body.id);
  const acked=await call('/v1/device/sync',{snapshot:{...snapshot,killed:true},acks:[cmd.body.id]},{Authorization:`Bearer ${device}`});
  assert.equal(acked.status,200);assert.deepEqual(acked.body.commands,[]);
  const status=await call('/v1/status');assert.equal(status.body.commands[0].status,'applied');assert.equal(status.body.snapshot.killed,true);
  const password='Runtime test passphrase 2026';
  const salt='U'.repeat(43),proof=pbkdf2Sync(password,salt,600000,32,'sha256').toString('hex');
  assert.equal((await call('/v1/password',{current_password:owner,new_password:proof,salt})).status,200);
  assert.equal((await call('/v1/status')).status,401);
  assert.equal((await call('/v1/login',{password:owner})).status,401);
  assert.equal((await call('/v1/login',{password:proof})).status,200);
  assert.equal((await call('/v1/device/sync',{snapshot,acks:[]},{Authorization:`Bearer ${device}`})).status,200);
  const now=Math.floor(Date.now()/1000),sha='d'.repeat(40);
  const claims={iss:'https://token.actions.githubusercontent.com',aud:origin+'/bot-releases',sub:'repo:jlboper@328148059/Crypto-BOT@1366739763:environment:portal-production',
    repository:'jlboper/Crypto-BOT',repository_id:'1366739763',repository_owner_id:'328148059',ref:'refs/heads/main',environment:'portal-production',event_name:'push',
    workflow_ref:'jlboper/Crypto-BOT/.github/workflows/portal-release.yml@refs/heads/main',sha,run_id:'12345',exp:now+300,nbf:now-10};
  const input=[{alg:'RS256',kid:'runtime-key'},claims].map(v=>Buffer.from(JSON.stringify(v)).toString('base64url')).join('.');
  const jwt=input+'.'+sign('RSA-SHA256',Buffer.from(input),publisher.privateKey).toString('base64url');
  const manifest={app:'crypto-ai-trading-bot',mode:'paper',runtime_protocol:1,version:'0.6.3',commit:sha,sequence:12345,expires:now+86400,size:100,sha256:'a'.repeat(64),
    package_url:`https://raw.githubusercontent.com/jlboper/Crypto-BOT/bot-releases/packages/${sha}.zip`,
    files:Object.fromEntries(['pyproject.toml','trader/__main__.py','trader/runtime_control.py'].map(p=>[p,'b'.repeat(64)]))};
  const signed=await call('/v1/releases/sign',manifest,{Authorization:`Bearer ${jwt}`});
  assert.equal(signed.status,200,JSON.stringify(signed.body));
  assert.equal(verify(null,Buffer.from(canonical(manifest)),signer.publicKey,Buffer.from(signed.body.signature,'base64')),true);
  assert.deepEqual((await call('/v1/releases/latest')).body,signed.body);
});
