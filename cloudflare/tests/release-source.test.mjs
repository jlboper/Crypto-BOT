import test from 'node:test';
import assert from 'node:assert/strict';
import {releaseSource,requireCurrentMain} from '../../scripts/release_source.mjs';
const sha='a'.repeat(40);
const env={GITHUB_REPOSITORY:'jlboper/Crypto-BOT',GITHUB_EVENT_NAME:'push',GITHUB_REF:'refs/heads/main',
  GITHUB_SHA:sha,RELEASE_SHA:sha,RELEASE_REF:'refs/heads/main',GITHUB_TOKEN:'synthetic-token'};
test('release source rejects PRs, foreign repos, manual runs, other branches and revision substitution',()=>{
  assert.equal(releaseSource(env),sha);
  for(const changes of [{GITHUB_EVENT_NAME:'pull_request',GITHUB_REF:'refs/pull/100/merge'},
    {GITHUB_EVENT_NAME:'workflow_dispatch'},{GITHUB_REPOSITORY:'other/repo'},
    {GITHUB_REF:'refs/heads/dev'},{RELEASE_SHA:'b'.repeat(40)},{GITHUB_SHA:undefined},
    {RELEASE_REF:'refs/heads/dev'}])assert.throws(()=>releaseSource({...env,...changes}));
});
test('current main is rechecked before deployment/package publication and fails closed',async()=>{
  let requests=0;
  const fetcher=async(url,options)=>{
    requests++;
    assert.equal(url,'https://api.github.com/repos/jlboper/Crypto-BOT/git/ref/heads/main');
    assert.equal(options.headers.Authorization,'Bearer synthetic-token');
    assert.equal(options.redirect,'error');
    return Response.json({object:{sha}});
  };
  assert.equal(await requireCurrentMain(env,fetcher),sha);
  await assert.rejects(requireCurrentMain({...env,GITHUB_EVENT_NAME:'pull_request'},fetcher));
  await assert.rejects(requireCurrentMain({...env,GITHUB_TOKEN:''},fetcher));
  assert.equal(requests,1);
  await assert.rejects(requireCurrentMain(env,async()=>Response.json({object:{sha:'b'.repeat(40)}})),/superseded/);
  await assert.rejects(requireCurrentMain(env,async()=>new Response('sensitive detail',{status:403})),
    error=>error.message==='Cannot verify current main release');
  await assert.rejects(requireCurrentMain(env,async()=>new Response('sensitive malformed json')),
    error=>error.message==='Cannot verify current main release');
});
