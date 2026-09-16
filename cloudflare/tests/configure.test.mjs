import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { configure } from '../scripts/configure.mjs';

const template=JSON.parse(readFileSync(new URL('../wrangler.jsonc',import.meta.url),'utf8'));
const settings={accountId:'a'.repeat(32),databaseId:'11111111-1111-1111-1111-111111111111',origin:'https://crypto-paper-private-portal.example.workers.dev'};
test('production configuration has exact origin, dedicated D1 and only reviewed assets',()=>{
  const result=configure(template,settings);
  assert.equal(result.account_id,settings.accountId);assert.equal(result.vars.PORTAL_ORIGIN,settings.origin);
  assert.equal(result.assets.directory,'public');assert.equal(result.assets.run_worker_first,true);
  assert.equal(result.preview_urls,false);assert.equal(result.observability.enabled,false);
  assert.equal(result.d1_databases.length,1);assert.equal(template.vars.PORTAL_ORIGIN,'https://portal.invalid');
});
test('placeholder database, wrong account, third party origin and URL paths fail',()=>{
  for(const bad of [{databaseId:'00000000-0000-0000-0000-000000000000'},{accountId:''},{origin:'https://evil.example'},{origin:settings.origin+'/path'},{origin:'http://crypto-paper-private-portal.example.workers.dev'},{origin:'https://different.example.workers.dev'}]){
    assert.throws(()=>configure(template,{...settings,...bad}));
  }
});
