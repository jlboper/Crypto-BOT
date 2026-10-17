import test from 'node:test';
import assert from 'node:assert/strict';
import {requestReleaseSignature} from '../../scripts/retry_release_signature.mjs';

const stale = () => Response.json({code: 'portal_and_bot_revision_must_match'}, {status: 403});
const origin = 'https://portal.example';
const manifest = {version: '0.6.14', commit: 'a'.repeat(40)};
const retryableCodes = ['portal_and_bot_revision_must_match', 'publisher_revision_unavailable', 'publisher_revision_rate_limited'];
const rejected = (code, status = 403) => Response.json({code}, {status});

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

test('unknown codes shaped like fixed labels cannot disclose arbitrary secrets', async () => {
  for (const code of ['private_bearer_token','github_pat_private']) {
    let calls = 0;
    await assert.rejects(requestReleaseSignature(origin,'oidc',manifest,{
      fetcher: async () => {calls++; return rejected(code);},
      pause: async () => assert.fail('Unknown code cannot retry'),
    }), /^Error: Signed publication rejected \(403; unclassified\)$/);
    assert.equal(calls,1);
  }
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

test('each authenticated transient revision failure can succeed with the same immutable request', async () => {
  for (const code of retryableCodes) {
    const calls = [], delays = [], timeouts = [];
    const input = {version: '0.10.39', commit: 'b'.repeat(40), files: {'trader/__main__.py': 'c'.repeat(64)}};
    const frozenBody = JSON.stringify(input);
    const originalTimeout = AbortSignal.timeout;
    AbortSignal.timeout = ms => {timeouts.push(ms); return originalTimeout(ms);};
    try {
      const result = await requestReleaseSignature(origin, 'same-protected-oidc', input, {
        fetcher: async (url, options) => {
          calls.push({url,options});
          return calls.length === 1 ? rejected(code) : Response.json({manifest: JSON.parse(frozenBody), signature: 'verified-envelope'});
        },
        pause: async ms => {
          delays.push(ms);
          // Even a caller mutation during backoff cannot replace the built body.
          input.commit = 'd'.repeat(40);
          input.files['trader/__main__.py'] = 'e'.repeat(64);
        },
      });
      assert.equal(result.signature, 'verified-envelope', code);
      assert.deepEqual(delays, [5000], code);
      assert.deepEqual(timeouts, [30000,30000], code);
      assert.equal(calls.length, 2, code);
      for (const {url,options} of calls) {
        assert.equal(url, origin+'/v1/releases/sign', code);
        assert.equal(options.method, 'POST', code);
        assert.equal(options.redirect, 'error', code);
        assert.deepEqual(options.headers, {Authorization: 'Bearer same-protected-oidc', 'Content-Type': 'application/json'}, code);
        assert.equal(options.body, frozenBody, code);
      }
    } finally {
      AbortSignal.timeout = originalTimeout;
    }
  }
});

test('mixed transient causes share the existing six delays and 105 second budget', async () => {
  let calls = 0;
  const delays = [];
  await assert.rejects(requestReleaseSignature(origin, 'oidc', manifest, {
    fetcher: async () => rejected(retryableCodes[calls++ % retryableCodes.length]),
    pause: async ms => delays.push(ms),
  }), /^Error: Signed publication rejected \(403; portal_and_bot_revision_must_match\)$/);
  assert.equal(calls,7);
  assert.deepEqual(delays,[5000,10000,15000,20000,25000,30000]);
  assert.equal(delays.reduce((sum,delay)=>sum+delay,0),105000);
});

test('authorization, superseded source and manifest failures never retry', async () => {
  const permanent = ['publisher_revision_forbidden','publisher_revision_not_found',
    'publisher_revision_superseded','invalid_publisher_signature','expired_publisher_token',
    'invalid_publisher_audience','invalid_publisher_subject','invalid_publisher_workflow',
    'invalid_publisher_repository','invalid_publisher_environment','invalid_publisher_revision',
    'invalid_manifest_fields','revision_mismatch','invalid_release_lifetime','invalid_package_digest',
    'release_sequence_conflict','release_sequence_already_superseded','signing_runtime_failure'];
  for (const code of permanent) {
    let calls = 0;
    await assert.rejects(requestReleaseSignature(origin, 'oidc', manifest, {
      fetcher: async () => {calls++; return rejected(code);},
      pause: async () => assert.fail('A permanent rejection must never retry: '+code),
    }), error => error.message === `Signed publication rejected (403; ${code})`);
    assert.equal(calls,1,code);
  }
});

test('a permanent rejection after a transient failure immediately ends the shared retry loop', async () => {
  let calls = 0;
  const delays = [];
  await assert.rejects(requestReleaseSignature(origin,'same-oidc',manifest,{
    fetcher: async () => rejected(calls++ === 0 ? 'publisher_revision_unavailable' : 'publisher_revision_superseded'),
    pause: async ms => delays.push(ms),
  }), /^Error: Signed publication rejected \(403; publisher_revision_superseded\)$/);
  assert.equal(calls,2);
  assert.deepEqual(delays,[5000]);
});

test('transient-looking payloads outside the authenticated 403 code contract cannot retry or leak body text', async () => {
  const secret = 'private-token-or-provider-body';
  const responses = [
    () => rejected('publisher_revision_unavailable',401),
    () => rejected('publisher_revision_rate_limited',429),
    () => rejected('portal_and_bot_revision_must_match',500),
    () => Response.json({error: 'publisher_revision_unavailable', detail: secret},{status:403}),
    () => Response.json({code: ['publisher_revision_unavailable'], detail: secret},{status:403}),
    () => Response.json({code: secret, token: secret, manifest},{status:403}),
    () => new Response('publisher_revision_unavailable '+secret,{status:403}),
  ];
  for (const response of responses) {
    let calls = 0;
    await assert.rejects(requestReleaseSignature(origin,secret,manifest,{
      fetcher: async () => {calls++; return response();},
      pause: async () => assert.fail('Only allowlisted authenticated codes may retry'),
    }), error => !error.message.includes(secret) && /^Signed publication rejected \(\d{3}; [a-z_]+\)$/.test(error.message));
    assert.equal(calls,1);
  }
});
