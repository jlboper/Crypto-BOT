import test from 'node:test';
import assert from 'node:assert/strict';
import {checkMigrations} from '../scripts/check-migrations.mjs';
const settings={accountId:'account',databaseId:'database',token:'test-only',expected:['0001.sql','0002.sql']};
const reply=(names)=>new Response(JSON.stringify({success:true,result:[{success:true,results:names.map(name=>({name}))}]}));
test('migration preflight uses only SELECT with the limited credential',async()=>{
  await checkMigrations(settings,async(url,options)=>{
    assert.equal(url,'https://api.cloudflare.com/client/v4/accounts/account/d1/database/database/query');
    assert.equal(options.redirect,'error');
    assert.equal(options.headers.Authorization,'Bearer test-only');
    assert.deepEqual(JSON.parse(options.body),{sql:'SELECT name FROM d1_migrations ORDER BY id',params:[]});
    return reply(settings.expected);
  });
});
test('pending, unknown and malformed migration histories block publication',async()=>{
  for(const names of [[],['0001.sql'],['0001.sql','0002.sql','future.sql'],['0001.sql','0001.sql'],[null]]){
    await assert.rejects(checkMigrations(settings,async()=>reply(names)));
  }
  await assert.rejects(checkMigrations(settings,async()=>new Response('{}')));
  await assert.rejects(checkMigrations(settings,async()=>new Response('',{status:403})),/verification failed/);
});

test('reviewed additive migration may be pending only when explicitly allowed',async()=>{
  const transport=async()=>({ok:true,json:async()=>({success:true,result:[{success:true,results:[{name:'0001.sql'}]}]})});
  const seen=await checkMigrations({...settings,allowPending:['0002.sql']},transport);
  assert.deepEqual(seen,['0001.sql']);
});
