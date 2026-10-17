// Retry only fixed authenticated revision-availability/propagation failures.
// Every attempt reuses the exact request and lets the signer revalidate OIDC,
// current main, deployed revision and the manifest. No cached proof or fallback.
const propagationDelays = [5000, 10000, 15000, 20000, 25000, 30000];
const retryableRevisionCodes = new Set([
  'portal_and_bot_revision_must_match',
  'publisher_revision_unavailable',
  'publisher_revision_rate_limited',
]);
// These are fixed labels emitted by the signer validation protocol. A body with
// arbitrary text shaped like a code must not become a publication log message.
const signerFailureCodes = new Set([
  ...retryableRevisionCodes,
  'signing_not_provisioned', 'invalid_publisher_token', 'invalid_publisher_algorithm',
  'publisher_keys_unavailable', 'unknown_publisher_key', 'invalid_publisher_signature',
  'invalid_publisher_audience', 'invalid_publisher_subject', 'invalid_publisher_repository',
  'invalid_publisher_environment', 'invalid_publisher_workflow', 'expired_publisher_token',
  'invalid_publisher_revision', 'publisher_revision_forbidden', 'publisher_revision_not_found',
  'publisher_revision_superseded', 'invalid_manifest', 'invalid_manifest_fields',
  'invalid_runtime', 'revision_mismatch', 'invalid_release_lifetime',
  'invalid_package_destination', 'invalid_package_digest', 'invalid_files',
  'unsafe_file_path', 'protected_file_path', 'invalid_file_digest', 'incomplete_package',
  'release_sequence_conflict', 'release_sequence_already_superseded', 'signing_runtime_failure',
]);

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
    const code = typeof failure?.code === 'string' && signerFailureCodes.has(failure.code) ? failure.code : 'unclassified';
    if (response.status === 403 && retryableRevisionCodes.has(code)
        && attempt < propagationDelays.length) {
      await pause(propagationDelays[attempt]);
      continue;
    }
    throw Error(`Signed publication rejected (${response.status}; ${code})`);
  }
}
