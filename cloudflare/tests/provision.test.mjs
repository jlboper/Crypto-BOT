import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { provision } from '../scripts/provision.mjs';

test('provision separates credentials, writes only hashes for server and refuses overwrite', async()=>{
  const temporary=await mkdtemp(join(tmpdir(),'portal-provision-'));
  try {
    const destination=join(temporary,'keys');
    const origin='https://crypto-paper-private-portal.example.workers.dev';
    await provision(destination,origin);
    const owner=(await readFile(join(destination,'owner-access-key.txt'),'utf8')).trim();
    const env=await readFile(join(destination,'windows-agent.env'),'utf8');
    const device=env.split('PORTAL_DEVICE_TOKEN=')[1].trim();
    const hashes=JSON.parse(await readFile(join(destination,'worker-secrets.json'),'utf8'));
    assert.equal(/^[A-Za-z0-9_-]{43}$/.test(owner),true);
    assert.equal(/^[A-Za-z0-9_-]{43}$/.test(device),true);
    assert.equal(owner===device,false);
    const hash=v=>createHash('sha256').update(v).digest('hex');
    assert.equal(hashes.OWNER_KEY_HASH===hash(owner),true);
    assert.equal(hashes.DEVICE_KEY_HASH===hash(device),true);
    await assert.rejects(provision(destination,origin));
    assert.equal((await readFile(join(destination,'owner-access-key.txt'),'utf8')).trim()===owner,true);
    await assert.rejects(provision(join(temporary,'bad'),'http://example.workers.dev'));
  } finally {await rm(temporary,{recursive:true,force:true});}
});
