import test from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPairSync,sign,verify,createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {authorizePublisher,signRelease,canonical,validateManifest} from '../src/bot-releases.mjs';
const origin='https://portal.example',now=1800000000;
const rsa=generateKeyPairSync('rsa',{modulusLength:2048});
const ed=generateKeyPairSync('ed25519');
const claim={iss:'https://token.actions.githubusercontent.com',aud:origin+'/bot-releases',
  sub:'repo:jlboper/Crypto-BOT:environment:portal-production',repository:'jlboper/Crypto-BOT',repository_id:'1366739763',
  ref:'refs/heads/main',environment:'portal-production',workflow_ref:'jlboper/Crypto-BOT/.github/workflows/portal-release.yml@refs/heads/main',
  event_name:'push',sha:'a'.repeat(40),run_id:'12345',exp:now+300,nbf:now-10};
const token=(overrides={},header={alg:'RS256',kid:'test-key'})=>{
  const input=[header,{...claim,...overrides}].map(x=>Buffer.from(JSON.stringify(x)).toString('base64url')).join('.');
  return input+'.'+sign('RSA-SHA256',Buffer.from(input),rsa.privateKey).toString('base64url');
};
const transport=async url=>{assert.equal(url,'https://token.actions.githubusercontent.com/.well-known/jwks');return Response.json({keys:[{...rsa.publicKey.export({format:'jwk'}),kid:'test-key'}]});};
const manifest=()=>({app:'crypto-ai-trading-bot',mode:'paper',version:'0.6.3',runtime_protocol:1,commit:claim.sha,sequence:12345,
  expires:now+86400,size:100,sha256:'b'.repeat(64),package_url:`https://raw.githubusercontent.com/jlboper/Crypto-BOT/bot-releases/packages/${claim.sha}.zip`,
  files:Object.fromEntries(['trader/__main__.py','trader/runtime_control.py','pyproject.toml'].map(p=>[p,'c'.repeat(64)]))});
test('publisher identity binds protected environment, repository, workflow, revision and lifetime',async()=>{
  assert.equal((await authorizePublisher(token(),origin,now,transport)).sha,claim.sha);
  for(const wrong of [{repository_id:'1'},{ref:'refs/heads/other'},{environment:'other'},{workflow_ref:'other'},
    {aud:'elsewhere'},{sub:'repo:jlboper/Crypto-BOT:pull_request'},{exp:now-1},{event_name:'pull_request'}])
    await assert.rejects(authorizePublisher(token(wrong),origin,now,transport));
  await assert.rejects(authorizePublisher(token({}, {alg:'none',kid:'test-key'}),origin,now,transport));
  const other=generateKeyPairSync('rsa',{modulusLength:2048});
  const input=token().split('.').slice(0,2).join('.');
  await assert.rejects(authorizePublisher(input+'.'+sign('RSA-SHA256',Buffer.from(input),other.privateKey).toString('base64url'),origin,now,transport));
});
test('signing creates verifiable Ed25519 envelopes and rejects sequence substitution',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());
  db.exec('CREATE TABLE bot_releases(sequence INTEGER PRIMARY KEY,release_id TEXT UNIQUE,commit_sha TEXT,envelope TEXT,created INTEGER)');
  const env={PORTAL_ORIGIN:origin,PORTAL_COMMIT:claim.sha,BOT_SIGNING_KEY:ed.privateKey.export({format:'der',type:'pkcs8'}).toString('base64'),
    DB:{prepare:sql=>({bind:(...args)=>({first:async()=>db.prepare(sql).get(...args)||null})})}};
  const m=manifest();const result=await signRelease(env,token(),m,now,transport);
  assert.equal(verify(null,Buffer.from(canonical(m)),ed.publicKey,Buffer.from(result.signature,'base64')),true);
  assert.deepEqual(await signRelease(env,token(),m,now,transport),result);
  await assert.rejects(signRelease(env,token(),{...m,sha256:'d'.repeat(64)},now,transport));
  for(const wrong of [{mode:'live'},{commit:'b'.repeat(40)},{package_url:'https://evil.example/bot.zip'},
    {files:{...m.files,'config.toml':'e'.repeat(64)}},{expires:now+91*86400}])assert.throws(()=>validateManifest({...m,...wrong},claim,now));
});
