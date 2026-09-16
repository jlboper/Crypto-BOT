import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const workflow=readFileSync(new URL('../../.github/workflows/portal-release.yml',import.meta.url),'utf8');
const deploy=readFileSync(new URL('../scripts/deploy-ci.mjs',import.meta.url),'utf8');
test('release workflow pins actions, cancels obsolete runs and protects deployment credentials',()=>{
  assert.match(workflow,/cancel-in-progress: true/);
  for(const line of workflow.split(/\r?\n/).filter(line=>line.includes('uses: actions/')))assert.match(line,/actions\/[a-z-]+@[a-f0-9]{40}\b/);
  assert.match(workflow,/environment: portal-production/);
  assert.match(workflow,/secrets\.DEPLOYMENT_ENABLED/);
  assert.doesNotMatch(workflow,/GITHUB_APPROVAL_TOKEN/);
});
test('CI fails closed for pending migrations and rolls back failed health',()=>{
  assert.match(deploy,/await checkMigrations/);
  assert.match(deploy,/Protected environment gate not configured/);
  assert.match(deploy,/\['rollback','--message'/);
  assert.match(deploy,/attempt<3/);
});
