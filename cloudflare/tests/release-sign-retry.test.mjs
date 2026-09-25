import test from 'node:test';
import assert from 'node:assert/strict';
import {requestReleaseSignature} from '../../scripts/retry_release_signature.mjs';

const stale = () => Response.json({code: 'portal_and_bot_revision_must_match'}, {status: 403});
const origin = 'https://portal.example';
const manifest = {version: '0.6.14', commit: 'a'.repeat(40)};

test('a delayed portal revision signs the same manifest in one protected run', async () => {
  const requests = [], delays = [];
  const fetcher = async (url, options) => {
    requests.push({url, options});
    return requests.length < 3 ? stale() : Response.json({manifest, signature: 'signed'});
  };
  const envelope = await requestReleaseSignature(origin, 'oidc', manifest, {
    fetcher, pause: async ms => delays.push(ms),
  });
  assert.equal(envelope.signature, 'signed');
  assert.deepEqual(delays, [5000, 10000]);
  assert.equal(requests.length, 3);
  for (const {url, options} of requests) {
    assert.equal(url, origin + '/v1/releases/sign');
    assert.equal(options.method, 'POST');
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'Bearer oidc');
    assert.equal(options.body, JSON.stringify(manifest));
  }
});

test('other signer rejection cannot be retried or expose arbitrary server text', async () => {
  let calls = 0;
  await assert.rejects(requestReleaseSignature(origin, 'oidc', manifest, {
    fetcher: async () => {calls++; return Response.json({code: 'secret:private-key'}, {status: 403});},
    pause: async () => assert.fail('Unexpected retry'),
  }), /^Error: Signed publication rejected \(403; unclassified\)$/);
  assert.equal(calls, 1);
});

test('retry stops after a bounded propagation window', async () => {
  let calls = 0;
  const delays = [];
  await assert.rejects(requestReleaseSignature(origin, 'oidc', manifest, {
    fetcher: async () => {calls++; return stale();},
    pause: async ms => delays.push(ms),
  }), /^Error: Signed publication rejected \(403; portal_and_bot_revision_must_match\)$/);
  assert.equal(calls, 7);
  assert.deepEqual(delays, [5000, 10000, 15000, 20000, 25000, 30000]);
});

test('network failure is not treated as proof of revision propagation', async () => {
  let calls = 0;
  await assert.rejects(requestReleaseSignature(origin, 'oidc', manifest, {
    fetcher: async () => {calls++; throw Error('Transport failure');},
    pause: async () => assert.fail('Unexpected retry'),
  }), /Transport failure/);
  assert.equal(calls, 1);
});
