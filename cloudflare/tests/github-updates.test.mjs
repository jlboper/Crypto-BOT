import test from 'node:test';
import assert from 'node:assert/strict';
import {githubUpdates} from '../src/github-updates.mjs';
const sha='a'.repeat(40);
const run=()=>({id:42,run_attempt:1,head_sha:sha,head_branch:'main',event:'push',path:'.github/workflows/portal-release.yml',head_repository:{full_name:'jlboper/Crypto-BOT'},actor:{login:'reviewed-user'},created_at:'2026-09-16T00:00:00Z',status:'waiting'});
function fixture(changes={}){
  const requests=[];
  const fetcher=async(url,options)=>{
    requests.push({url,...options});
    assert.match(url,/^https:\/\/api.github.com\/repos\/jlboper\/Crypto-BOT\//);
    assert.equal(options.method,'GET');assert.equal(options.headers.Authorization,undefined);
    let value;
    if(url.includes('/git/ref/'))value={object:{sha:changes.head||sha}};
    else if(url.includes('/jobs'))value={total_count:1,jobs:[{name:'validate',status:'completed',conclusion:changes.tests||'success'}]};
    else value={workflow_runs:[{...run(),...changes.run}]};
    return new Response(JSON.stringify(value),{status:200});
  };
  return {api:githubUpdates({PORTAL_COMMIT:changes.published},fetcher),requests};
}
test('only the tested current main commit links to GitHub review',async()=>{
  const {api,requests}=fixture();const result=await api.list();
  assert.equal(result.runs.length,1);assert.equal(result.runs[0].review_on_github,true);
  assert.equal(result.runs[0].actor,'reviewed-user');assert.match(result.runs[0].commit_url,new RegExp(sha));
  assert.equal(requests.every(r=>r.method==='GET'),true);
});
test('old runs, failed tests, other branches, workflows and repos cannot be presented for review',async()=>{
  for(const changes of [{head:'b'.repeat(40)},{tests:'failure'},{run:{head_branch:'dev'}},{run:{path:'.github/workflows/evil.yml'}},{run:{head_repository:{full_name:'other/repo'}}},{run:{event:'pull_request'}}]){
    const result=await fixture(changes).api.list();
    if(changes.tests)assert.equal(result.runs[0].review_on_github,false);else assert.deepEqual(result.runs,[]);
  }
});
test('published commit is labeled without any write credential',async()=>{
  const result=await fixture({published:sha,run:{status:'completed',conclusion:'success'}}).api.list();
  assert.equal(result.runs[0].published,true);assert.equal(result.runs[0].review_on_github,false);
});
test('provider failures and malformed JSON are redacted',async()=>{
  await assert.rejects(githubUpdates({},async()=>new Response('sensitive provider body',{status:403})).list(),error=>error.status===429&&!error.message.includes('sensitive'));
  await assert.rejects(githubUpdates({},async()=>new Response('not json',{status:200})).list(),error=>error.status===502);
});
