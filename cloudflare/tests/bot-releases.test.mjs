import test from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPairSync,sign,verify,createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {authorizePublisher,signRelease,canonical,validateManifest,releaseFailureCode} from '../src/bot-releases.mjs';
const origin='https://portal.example',now=1800000000;
test('signer diagnostics never expose arbitrary exception contents',()=>{
  assert.equal(releaseFailureCode(new Error('secret bearer token private key')), 'signing_runtime_failure');
  try{validateManifest(null,{},0);}catch(error){assert.equal(releaseFailureCode(error),'invalid_manifest');}
});
const rsa=generateKeyPairSync('rsa',{modulusLength:2048});
const ed=generateKeyPairSync('ed25519');
const claim={iss:'https://token.actions.githubusercontent.com',aud:origin+'/bot-releases',
  sub:'repo:jlboper@328148059/Crypto-BOT@1366739763:environment:portal-production',repository:'jlboper/Crypto-BOT',repository_id:'1366739763',repository_owner_id:'328148059',
  ref:'refs/heads/main',environment:'portal-production',workflow_ref:'jlboper/Crypto-BOT/.github/workflows/portal-release.yml@refs/heads/main',
  event_name:'push',sha:'a'.repeat(40),run_id:'12345',exp:now+300,nbf:now-10};
const token=(overrides={},header={alg:'RS256',kid:'test-key'})=>{
  const input=[header,{...claim,...overrides}].map(x=>Buffer.from(JSON.stringify(x)).toString('base64url')).join('.');
  return input+'.'+sign('RSA-SHA256',Buffer.from(input),rsa.privateKey).toString('base64url');
};
const transport=async(url,options)=>{
  if(url==='https://token.actions.githubusercontent.com/.well-known/jwks')return Response.json({keys:[{...rsa.publicKey.export({format:'jwk'}),kid:'test-key'}]});
  assert.equal(url,'https://api.github.com/repos/jlboper/Crypto-BOT/git/ref/heads/main');
  assert.equal(options.redirect,'manual');
  return Response.json({object:{sha:claim.sha}});
};
const manifest=()=>({app:'crypto-ai-trading-bot',mode:'paper',version:'0.6.3',runtime_protocol:1,commit:claim.sha,sequence:12345,
  expires:now+86400,size:100,sha256:'b'.repeat(64),package_url:`https://raw.githubusercontent.com/jlboper/Crypto-BOT/bot-releases/packages/${claim.sha}.zip`,
  files:Object.fromEntries(['trader/__main__.py','trader/runtime_control.py','pyproject.toml'].map(p=>[p,'c'.repeat(64)]))});

test('optional prepared LIVE capability is strict signed metadata and never an enabled mode',()=>{
  const legacy=manifest();assert.doesNotThrow(()=>validateManifest(legacy,claim,now));
  for(const mode of ['paper','testnet']){
    const prepared={...legacy,mode,prepared_live_protocol:1};
    assert.doesNotThrow(()=>validateManifest(prepared,claim,now));
    const signature=sign(null,Buffer.from(canonical(prepared)),ed.privateKey);
    assert.equal(verify(null,Buffer.from(canonical(prepared)),ed.publicKey,signature),true);
    assert.equal(verify(null,Buffer.from(canonical({...prepared,prepared_live_protocol:2})),ed.publicKey,signature),false);
    assert.equal(verify(null,Buffer.from(canonical(legacy)),ed.publicKey,signature),false);
  }
  for(const protocol of [true,false,0,2,'1',null,undefined,{},[],NaN])assert.throws(()=>validateManifest({...legacy,prepared_live_protocol:protocol},claim,now));
  for(const mode of ['live','LIVE','SPOT_LIVE','FUTURES_LIVE'])assert.throws(()=>validateManifest({...legacy,mode,prepared_live_protocol:1},claim,now));
  for(const extra of [{live_enabled:true},{owner_authorization:true},{prepared_live_protocol:1,execution_enabled:true}])assert.throws(()=>validateManifest({...legacy,...extra},claim,now));
});
test('publisher identity binds protected environment, repository, workflow, revision and lifetime',async()=>{
  assert.equal((await authorizePublisher(token(),origin,now,transport)).sha,claim.sha);
  const prSha='d'.repeat(40), prRef='refs/pull/86/merge';
  const prClaim={ref:prRef,event_name:'pull_request',base_ref:'main',head_ref:'release/v0106-approval-before-merge',
    workflow_ref:`jlboper/Crypto-BOT/.github/workflows/portal-release.yml@${prRef}`,sha:prSha};
  await assert.rejects(authorizePublisher(token(prClaim),origin,now,transport),/Invalid publisher workflow/);
  await assert.rejects(authorizePublisher(token({...prClaim,
    workflow_ref:'jlboper/Crypto-BOT/.github/workflows/portal-release.yml@refs/heads/main'}),origin,now,transport),/Invalid publisher workflow/);
  for(const wrong of [
    {...prClaim,base_ref:'other'},
    {...prClaim,head_ref:'feature/not-release'},
    {...prClaim,head_ref:'release/'},
    {...prClaim,ref:'refs/pull/86/head'},
    {...prClaim,ref:'refs/pull/086/merge'},
    {...prClaim,ref:'refs/pull/not-a-number/merge'},
    {...prClaim,workflow_ref:'jlboper/Crypto-BOT/.github/workflows/other.yml@refs/heads/main'}
  ]) await assert.rejects(authorizePublisher(token(wrong),origin,now,transport));
  for(const wrong of [{repository_id:'1'},{repository_owner_id:'1'},
    {sub:'repo:jlboper/Crypto-BOT:environment:portal-production'},
    {sub:claim.sub.replace('@328148059','@1')},{sub:claim.sub.replace('@1366739763','@1')},
    {sub:claim.sub.replace('portal-production','other')},
    {ref:'refs/heads/other'},{environment:'other'},{workflow_ref:'other'},
    {aud:'elsewhere'},{sub:'repo:jlboper/Crypto-BOT:pull_request'},{exp:now-1},{event_name:'pull_request'}])
    await assert.rejects(authorizePublisher(token(wrong),origin,now,transport));
  await assert.rejects(authorizePublisher(token({}, {alg:'none',kid:'test-key'}),origin,now,transport));
  const other=generateKeyPairSync('rsa',{modulusLength:2048});
  const input=token().split('.').slice(0,2).join('.');
  await assert.rejects(authorizePublisher(input+'.'+sign('RSA-SHA256',Buffer.from(input),other.privateKey).toString('base64url'),origin,now,transport));
});
test('signer rejects a genuine main identity superseded by a newer commit',async()=>{
  const changedMain=async(url,options)=>url.includes('api.github.com')
    ? Response.json({object:{sha:'f'.repeat(40)}}):transport(url,options);
  await assert.rejects(authorizePublisher(token(),origin,now,changedMain),/Publisher revision superseded/);
  const unavailable=async(url,options)=>url.includes('api.github.com')
    ? new Response('private provider detail',{status:503}):transport(url,options);
  await assert.rejects(authorizePublisher(token(),origin,now,unavailable),/Publisher revision unavailable/);
});

test('main revision HTTP failures use fixed bounded labels without reading provider bodies or private headers',async()=>{
  const cases=[
    [403,'0','Publisher revision rate limited','publisher_revision_rate_limited'],
    [429,null,'Publisher revision rate limited','publisher_revision_rate_limited'],
    [403,'58','Publisher revision forbidden','publisher_revision_forbidden'],
    [403,null,'Publisher revision forbidden','publisher_revision_forbidden'],
    [404,null,'Publisher revision not found','publisher_revision_not_found'],
    [500,null,'Publisher revision unavailable','publisher_revision_unavailable'],
    [503,null,'Publisher revision unavailable','publisher_revision_unavailable'],
    [401,null,'Publisher revision unavailable','publisher_revision_unavailable'],
    [302,null,'Publisher revision unavailable','publisher_revision_unavailable'],
  ];
  for(const [status,remaining,label,code] of cases){
    let mainCalls=0,headerReads=0;
    const failing=async(url,options)=>{
      if(url.includes('token.actions.githubusercontent.com'))return transport(url,options);
      mainCalls++;
      assert.equal(url,'https://api.github.com/repos/jlboper/Crypto-BOT/git/ref/heads/main');
      assert.equal(options.redirect,'manual');
      return {ok:false,status,statusText:'private upstream address and bearer token',
        headers:{get(name){
          headerReads++;
          assert.equal(name,'x-ratelimit-remaining');
          return remaining;
        }},
        json(){assert.fail('A rejected provider body must not be read');},
        text(){assert.fail('A rejected provider body must not be read');}};
    };
    await assert.rejects(authorizePublisher(token(),origin,now,failing),error=>{
      assert.equal(error.message,label);
      assert.equal(releaseFailureCode(error),code);
      assert.doesNotMatch(error.message,/private|address|bearer|token/);
      return true;
    });
    assert.equal(mainCalls,1,'The Worker must not retry the main-ref request');
    assert.equal(headerReads,status===403?1:0);
  }
});

test('main revision transport and body-read errors do not expose arbitrary exception details',async()=>{
  for(const stage of ['network','json']){
    let mainCalls=0;
    const failing=async(url,options)=>{
      if(url.includes('token.actions.githubusercontent.com'))return transport(url,options);
      mainCalls++;
      if(stage==='network')throw new Error('sensitive private key token upstream 203.0.113.1');
      return {ok:true,json:async()=>{throw new Error('private provider response content');}};
    };
    await assert.rejects(authorizePublisher(token(),origin,now,failing),error=>{
      assert.equal(error.message,'Publisher revision unavailable');
      assert.equal(releaseFailureCode(error),'publisher_revision_unavailable');
      return true;
    });
    assert.equal(mainCalls,1);
  }
});

test('invalid OIDC identities cannot trigger a main-ref availability query',async()=>{
  const other=generateKeyPairSync('rsa',{modulusLength:2048});
  const input=token().split('.').slice(0,2).join('.');
  const forged=input+'.'+sign('RSA-SHA256',Buffer.from(input),other.privateKey).toString('base64url');
  const invalid=[token({iss:'https://untrusted.example'}),token({aud:'elsewhere'}),
    token({repository_id:'1'}),token({sub:'untrusted'}),token({environment:'other'}),
    token({ref:'refs/heads/other'}),token({event_name:'pull_request'}),token({exp:now-1}),
    token({workflow_ref:'untrusted'}),token({sha:'not-a-commit'}),forged,
    token({}, {alg:'none',kid:'test-key'})];
  for(const publisher of invalid){
    let mainCalls=0;
    const limited=async(url,options)=>{
      if(url.includes('token.actions.githubusercontent.com'))return transport(url,options);
      mainCalls++;
      return new Response('sensitive failure',{status:403,headers:{'x-ratelimit-remaining':'0'}});
    };
    await assert.rejects(authorizePublisher(publisher,origin,now,limited));
    assert.equal(mainCalls,0);
  }
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
  await assert.rejects(signRelease({...env,PORTAL_COMMIT:'f'.repeat(40)},token(),m,now,transport),
    /Portal and bot revision must match/);
  await assert.rejects(signRelease(env,token({run_id:'12344'}),{...m,sequence:12344},now,transport),
    /Release sequence already superseded/);
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM bot_releases').get().count,1);
  for(const wrong of [{mode:'live'},{commit:'b'.repeat(40)},{package_url:'https://evil.example/bot.zip'},
    {files:{...m.files,'secrets.toml':'e'.repeat(64)}},{expires:now+91*86400}])assert.throws(()=>validateManifest({...m,...wrong},claim,now));
  assert.doesNotThrow(()=>validateManifest({...m,mode:'testnet',files:{...m.files,'config.toml':'e'.repeat(64)}},claim,now));
});
