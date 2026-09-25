// Cloudflare can serve the new portal revision at one edge before another edge
// sees it. Retry only this fixed, authenticated revision mismatch; every other
// signing failure keeps its original fail-closed behavior.
const propagationDelays = [5000, 10000, 15000, 20000, 25000, 30000];

export async function requestReleaseSignature(origin, token, manifest, {
  fetcher = fetch,
  pause = ms => new Promise(resolve => setTimeout(resolve, ms)),
} = {}) {
  const url = origin + '/v1/releases/sign';
  const body = JSON.stringify(manifest);
  for (let attempt = 0; ; attempt++) {
    const response = await fetcher(url, {
      method: 'POST', redirect: 'error',
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      body, signal: AbortSignal.timeout(30000),
    });
    if (response.ok) return response.json();
    const failure = await response.json().catch(() => ({}));
    const code = /^[a-z_]{1,80}$/.test(failure?.code || '') ? failure.code : 'unclassified';
    if (response.status === 403 && code === 'portal_and_bot_revision_must_match'
        && attempt < propagationDelays.length) {
      await pause(propagationDelays[attempt]);
      continue;
    }
    throw Error(`Signed publication rejected (${response.status}; ${code})`);
  }
}
