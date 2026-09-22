import { timingSafeEqual } from 'node:crypto';
import { githubUpdates, UpdateError } from './github-updates.mjs';
import { passwordDigest, validPassword, PASSWORD_ITERATIONS } from './password.mjs';
import { signRelease, releaseFailureCode } from './bot-releases.mjs';

const encoder = new TextEncoder();
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const HASH = /^[a-f0-9]{64}$/;
const LIMIT = 524288;
const JOB_MAX_SECONDS = 3 * 3600;
const security = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Strict-Transport-Security': 'max-age=31536000',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
};

export async function sha256(text) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(text))), b => b.toString(16).padStart(2, '0')).join('');
}
function same(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  const left = encoder.encode(a), right = encoder.encode(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...security, 'Content-Type': 'application/json; charset=utf-8', ...extra } });
}
class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function assert(condition, message) { if (!condition) throw new HttpError(400, message); }
async function readBody(request, maximum = 65536) {
  if ((request.headers.get('content-type') || '').split(';')[0] !== 'application/json') throw new HttpError(415, 'JSON required');
  const declared = request.headers.get('content-length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > maximum)) throw new HttpError(413, 'Body too large');
  if (!request.body) throw new HttpError(400, 'Body required');
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maximum) { await reader.cancel(); throw new HttpError(413, 'Body too large'); }
    chunks.push(value);
  }
  const data = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length; }
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(data)); }
  catch { throw new HttpError(400, 'Invalid JSON'); }
  assert(object(value), 'Object required');
  return value;
}
function validateSnapshot(snapshot) {
  assert(object(snapshot) && snapshot.mode === 'PAPER', 'PAPER snapshot required');
  const allowed = ['mode','equity','cash','exposure','positions','killed','last_cycle_at','ai_model','update_state','dashboard','bot_update','bot_restore'];
  assert(Object.keys(snapshot).every(k => allowed.includes(k)), 'Unknown snapshot field');
  for (const key of ['equity', 'cash', 'exposure']) {
    assert(snapshot[key] === null || (typeof snapshot[key] === 'number' && Number.isFinite(snapshot[key]) && snapshot[key] >= 0), 'Invalid balance');
  }
  assert(typeof snapshot.killed === 'boolean', 'Invalid pause state');
  assert(snapshot.last_cycle_at === null || (typeof snapshot.last_cycle_at === 'string' && snapshot.last_cycle_at.length <= 40 && Number.isFinite(Date.parse(snapshot.last_cycle_at))), 'Invalid cycle time');
  assert(typeof snapshot.ai_model === 'string' && /^[a-zA-Z0-9._-]{1,80}$/.test(snapshot.ai_model) && !snapshot.ai_model.startsWith('sk-'), 'Invalid model');
  assert(snapshot.update_state === 'manual_signed_install_only', 'Invalid update state');
  if(snapshot.bot_update!=null){
    const b=snapshot.bot_update;
    assert(object(b)&&Object.keys(b).every(k=>['release_id','version','sequence','expires','commit','enabled'].includes(k)),'Invalid bot release');
    assert(HASH.test(b.release_id)&&/^\d+\.\d+\.\d+$/.test(b.version)&&/^[a-f0-9]{40}$/.test(b.commit)&&Number.isSafeInteger(b.sequence)&&b.sequence>0&&Number.isInteger(b.expires)&&typeof b.enabled==='boolean','Invalid bot release');
  }
  if(snapshot.bot_restore!=null){
    const b=snapshot.bot_restore;
    assert(object(b)&&Object.keys(b).sort().join(',')==='current_release_id,current_version,enabled,restore_id,version','Invalid restore offer');
    assert(HASH.test(b.restore_id)&&HASH.test(b.current_release_id)&&/^\d+\.\d+\.\d+$/.test(b.version)&&/^\d+\.\d+\.\d+$/.test(b.current_version)&&b.enabled===true,'Invalid restore offer');
  }
  assert(Array.isArray(snapshot.positions) && snapshot.positions.length <= 100, 'Invalid positions');
  for (const p of snapshot.positions) {
    assert(object(p) && Object.keys(p).length === 5 && /^[A-Z0-9]{2,30}$/.test(p.symbol), 'Invalid position');
    for (const key of ['quantity','entry_price','stop_price','take_profit']) assert(typeof p[key] === 'number' && Number.isFinite(p[key]) && p[key] > 0, 'Invalid position value');
  }
  if (snapshot.dashboard !== undefined) {
    const d = snapshot.dashboard;
    assert(object(d) && object(d.status) && d.status.mode === 'PAPER', 'Invalid dashboard');
    assert(Object.keys(d).every(k=>['status','positions','equity','trades','reviews','events','risk','research','research_state','updates','paper_scorecard'].includes(k)), 'Unknown dashboard field');
    if(d.paper_scorecard!==undefined){
      const s=d.paper_scorecard;
      assert(object(s)&&s.mode==='PAPER'&&['INSUFFICIENT_EVIDENCE','REVIEW_REQUIRED'].includes(s.status),'Invalid PAPER scorecard');
      assert(Object.keys(s).length<=20&&JSON.stringify(s).length<3000,'Oversized PAPER scorecard');
    }
    for(const key of ['positions','equity','trades','reviews','events'])assert(Array.isArray(d[key]) && d[key].length<=300,'Dashboard rows exceeded');
    assert(object(d.research) && Array.isArray(d.research.assets) && d.research.assets.length<=30,'Invalid research report');
  }
  return snapshot;
}
function statement(db, sql, ...args) { return db.prepare(sql).bind(...args); }
function results(batch, index) { return batch[index]?.results || []; }
function cookie(request) {
  const values = (request.headers.get('cookie') || '').split(';').map(p => p.trim()).filter(p => p.startsWith('__Host-session='));
  return values.length === 1 ? values[0].slice('__Host-session='.length) : '';
}
function sessionCookie(token, age = 3600) { return `__Host-session=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${age}`; }
async function passwordBudget(db,now){
  const budget=await statement(db,`INSERT INTO login_budget VALUES(1,?,1)
    ON CONFLICT(id) DO UPDATE SET attempts=CASE WHEN window_start<=? THEN 1 ELSE attempts+1 END,
    window_start=CASE WHEN window_start<=? THEN excluded.window_start ELSE window_start END
    WHERE attempts<10 OR window_start<=? RETURNING attempts`,now,now-300,now-300,now-300).all();
  if(!budget.results.length)throw new HttpError(429,'Espera cinco minutos antes de volver a intentarlo');
}
async function matchesPassword(value,credential,bootstrap){
  if(typeof value!=='string'||value.length>128)return false;
  if(!credential)return TOKEN.test(value)&&same(await sha256(value),bootstrap);
  if(!validPassword(value)||credential.iterations!==PASSWORD_ITERATIONS)return false;
  return same(await passwordDigest(value,credential.salt),credential.digest);
}

export async function handle(request, env, now = Math.floor(Date.now() / 1000)) {
  const url = new URL(request.url);
  // No inferred Host, forwarded origin, or fallback credentials in production.
  if (!env.PORTAL_ORIGIN || new URL(env.PORTAL_ORIGIN).origin !== env.PORTAL_ORIGIN || !env.PORTAL_ORIGIN.startsWith('https://') || env.PORTAL_ORIGIN.endsWith('.invalid')) return json({ error: 'Portal not provisioned' }, 503);
  if (url.origin !== env.PORTAL_ORIGIN) return json({ error: 'Origin not allowed' }, 403);
  if (url.search) return json({ error: 'Query parameters not accepted' }, 400);
  const method = request.method, path = url.pathname;
  if (!['GET', 'POST'].includes(method)) return json({ error: 'Method not allowed' }, 405, { Allow: 'GET, POST' });
  if(path==='/v1/health' && method==='GET'){
    await statement(env.DB,'SELECT id FROM jobs LIMIT 1').all();
    return json({status:'ok',commit:/^[a-f0-9]{40}$/.test(env.PORTAL_COMMIT||'')?env.PORTAL_COMMIT:null});
  }
  if (method === 'GET' && ['/', '/app.js', '/style.css','/styles.css','/monitoring.css','/portal-bridge.js','/portal.css','/crypto-ai-trader-icon.png','/manifest.webmanifest','/service-worker.js'].includes(path)) {
    const asset = await env.ASSETS.fetch(request);
    const headers = new Headers(asset.headers);
    for (const [name, value] of Object.entries(security)) headers.set(name, value);
    return new Response(asset.body, { status: asset.status, headers });
  }
  if (!HASH.test(env.OWNER_KEY_HASH || '') || !HASH.test(env.DEVICE_KEY_HASH || '') || env.OWNER_KEY_HASH === env.DEVICE_KEY_HASH) return json({ error: 'Portal not provisioned' }, 503);
  const db = env.DB;
  if(path==='/v1/releases/sign'&&method==='POST'){
    const body=await readBody(request,LIMIT);
    try{return json(await signRelease(env,(request.headers.get('authorization')||'').replace(/^Bearer /,''),body,now));}
    catch(error){return json({error:'Publisher authorization or signed release validation failed',code:releaseFailureCode(error)},403);}
  }
  if(path==='/v1/releases/latest'&&method==='GET'){
    const row=await statement(db,'SELECT envelope FROM bot_releases ORDER BY sequence DESC LIMIT 1').first();
    return row?json(JSON.parse(row.envelope)):json({error:'No signed bot release published'},404);
  }
  if (path === '/v1/device/sync' && method === 'POST') {
    const auth = request.headers.get('authorization') || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
    if (!TOKEN.test(token) || !same(await sha256(token), env.DEVICE_KEY_HASH)) return json({ error: 'Unauthorized device' }, 401);
    const body = await readBody(request, LIMIT);
    assert(Object.keys(body).every(k => ['snapshot','acks','job_results'].includes(k)), 'Unknown field');
    const snapshot = validateSnapshot(body.snapshot);
    const acks = body.acks || [];
    assert(Array.isArray(acks) && acks.length <= 50 && acks.every(id => Number.isSafeInteger(id) && id > 0), 'Invalid acknowledgements');
    const queries = [statement(db, 'INSERT INTO snapshots(id,payload,received_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,received_at=excluded.received_at', JSON.stringify(snapshot), now)];
    if (acks.length) queries.push(statement(db, `UPDATE commands SET status='applied' WHERE id IN (${acks.map(() => '?').join(',')}) AND status IN ('pending','expired') AND delivered_at IS NOT NULL`, ...acks));
    queries.push(statement(db, "UPDATE commands SET status='expired' WHERE status='pending' AND expires<=?", now));
    queries.push(statement(db, "UPDATE commands SET delivered_at=? WHERE status='pending' AND delivered_at IS NULL", now));
    queries.push(statement(db, "SELECT id,action,expires FROM commands WHERE status='pending' ORDER BY id LIMIT 50"));
    const commandIndex = queries.length-1;
    const jobResults=body.job_results||[];
    assert(Array.isArray(jobResults)&&jobResults.length<=20,'Invalid job results');
    const jq=[];
    for(const job of jobResults){
      assert(object(job)&&Object.keys(job).every(key=>['id','action','status','message'].includes(key))&&
        Number.isSafeInteger(job.id)&&job.id>0&&['research','update_check','update_install','update_restore'].includes(job.action)&&
        ['running','completed','failed'].includes(job.status),'Invalid job result');
      assert(typeof job.message==='string'&&job.message.length<=300,'Invalid job message');
      jq.push(statement(db,"UPDATE jobs SET status=?,message=? WHERE id=? AND action=? AND delivered_at IS NOT NULL AND status IN ('pending','running')",job.status,job.message,job.id,job.action));
    }
    jq.push(statement(db,"UPDATE jobs SET status='expired' WHERE status='pending' AND expires<=?",now));
    jq.push(statement(db,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS));
    jq.push(statement(db,"UPDATE jobs SET delivered_at=COALESCE(delivered_at,?) WHERE status='pending' AND expires>?",now,now));
    jq.push(statement(db,"SELECT id,action,expires,release_id FROM jobs WHERE status='pending' AND expires>? ORDER BY id LIMIT 1",now));
    const batch=await db.batch([...queries,...jq]);
    return json({ commands: results(batch, commandIndex), jobs:results(batch,batch.length-1), poll_seconds: 30 });
  }
  if (method === 'POST' && request.headers.get('origin') !== env.PORTAL_ORIGIN) return json({ error: 'Origin not allowed' }, 403);
  const credential=await statement(db,'SELECT version,salt,digest,iterations FROM owner_password WHERE id=1 AND bootstrap_hash=?',env.OWNER_KEY_HASH).first();
  const ownerVersion=credential?.version||env.OWNER_KEY_HASH;
  if(path==='/v1/auth-parameters'&&method==='GET')return json(credential?
    {scheme:'pbkdf2-sha256',salt:credential.salt,iterations:PASSWORD_ITERATIONS}:
    {scheme:'initial-key'});
  if (path === '/v1/login' && method === 'POST') {
    const body = await readBody(request);
    await passwordBudget(db,now);
    if (!await matchesPassword(body.password,credential,env.OWNER_KEY_HASH)) return json({ error: 'Clave incorrecta' }, 401);
    const token = randomToken(), csrf = randomToken();
    await db.batch([
      statement(db, 'DELETE FROM sessions WHERE expires<=?', now),
      statement(db, 'INSERT INTO sessions(token,csrf,owner_version,expires) VALUES(?,?,?,?)', await sha256(token), csrf, ownerVersion, now+3600),
      statement(db, 'DELETE FROM sessions WHERE token NOT IN (SELECT token FROM sessions ORDER BY expires DESC,rowid DESC LIMIT 10)'),
    ]);
    return json({ csrf }, 200, { 'Set-Cookie': sessionCookie(token) });
  }
  const token = cookie(request);
  if (!TOKEN.test(token)) return json({ error: 'Session required' }, 401);
  const session = await statement(db, 'SELECT token,csrf FROM sessions WHERE token=? AND expires>? AND owner_version=?', await sha256(token), now, ownerVersion).first();
  if (!session) return json({ error: 'Session expired' }, 401);
  if (method === 'POST' && !same(request.headers.get('x-csrf-token') || '', session.csrf)) return json({ error: 'Invalid CSRF token' }, 403);
  if(path==='/v1/password'&&method==='POST'){
    const body=await readBody(request,2048);
    assert(Object.keys(body).every(k=>['current_password','new_password','salt'].includes(k)),'Unknown field');
    assert(validPassword(body.new_password)&&TOKEN.test(body.salt||''),'Invalid password proof');
    await passwordBudget(db,now);
    if(!await matchesPassword(body.current_password,credential,env.OWNER_KEY_HASH))return json({error:'Contraseña actual incorrecta'},400);
    assert(body.new_password!==body.current_password,'Elige una contraseña diferente');
    assert(!same(await sha256(body.new_password),env.DEVICE_KEY_HASH),'Usa una contraseña distinta de las credenciales técnicas');
    assert(body.salt!==credential?.salt,'Use a new password salt');
    const version=randomToken(),salt=body.salt,digest=await passwordDigest(body.new_password,salt);
    const update=await db.batch([
      statement(db,`INSERT INTO owner_password(id,bootstrap_hash,version,salt,digest,iterations) VALUES(1,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET bootstrap_hash=excluded.bootstrap_hash,version=excluded.version,
        salt=excluded.salt,digest=excluded.digest,iterations=excluded.iterations
        WHERE owner_password.version=? OR owner_password.bootstrap_hash<>? RETURNING version`,env.OWNER_KEY_HASH,version,salt,digest,PASSWORD_ITERATIONS,ownerVersion,env.OWNER_KEY_HASH),
      statement(db,'DELETE FROM sessions WHERE owner_version=? AND EXISTS(SELECT 1 FROM owner_password WHERE version=?)',ownerVersion,version)
    ]);
    if(!results(update,0).length)return json({error:'La contraseña cambió en otra sesión; vuelve a entrar'},409);
    return json({ok:true},200,{'Set-Cookie':sessionCookie('',0)});
  }
  if(path==='/v1/updates' && method==='GET')return json(await githubUpdates(env).list());
  if (path === '/v1/status' && method === 'GET') {
    const batch = await db.batch([
      statement(db, 'SELECT payload,received_at FROM snapshots WHERE id=1'),
      statement(db, "SELECT id,action,CASE WHEN status='pending' AND expires<=? THEN 'expired' ELSE status END AS status,expires FROM commands ORDER BY id DESC LIMIT 20", now),
      statement(db,"SELECT id,action,status,message FROM jobs ORDER BY id DESC LIMIT 20"),
    ]);
    const snapshot = results(batch, 0)[0];
    return json({ csrf: session.csrf, snapshot: snapshot ? JSON.parse(snapshot.payload) : null,
      received_at: snapshot?.received_at ?? null, stale: !snapshot || now-snapshot.received_at > 120,
      commands: results(batch, 1), jobs:results(batch,2) });
  }
  if(path==='/v1/jobs'&&method==='POST'){
    const body=await readBody(request);
    assert(Object.keys(body).every(k=>['action','request_id','release_id'].includes(k)),'Unknown job field');
    assert(['research','update_check','update_install','update_restore'].includes(body.action)&&typeof body.request_id==='string'&&/^[A-Za-z0-9_-]{16,100}$/.test(body.request_id),'Invalid job');
    assert(['update_install','update_restore'].includes(body.action)?HASH.test(body.release_id||''):body.release_id===undefined,'Exact release or restore approval required');
    const batch=await db.batch([
      statement(db,"UPDATE jobs SET status='expired' WHERE status='pending' AND expires<=?",now),
      statement(db,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS),
      statement(db,`INSERT INTO jobs(request_id,action,status,created,expires,release_id) SELECT ?,?,'pending',?,?,?
        WHERE EXISTS(SELECT 1 FROM snapshots WHERE received_at>=? AND
          (?!='update_install' OR (json_extract(payload,'$.bot_update.enabled')=1 AND json_extract(payload,'$.bot_update.release_id')=? AND json_extract(payload,'$.bot_update.expires')>?))
          AND (?!='update_restore' OR (json_extract(payload,'$.bot_restore.enabled')=1 AND json_extract(payload,'$.bot_restore.restore_id')=?)))
        AND NOT EXISTS(SELECT 1 FROM jobs WHERE status IN ('pending','running') OR created>?) ON CONFLICT(request_id) DO NOTHING`,body.request_id,body.action,now,now+300,body.release_id??null,now-120,body.action,body.release_id??null,now,body.action,body.release_id??null,now-60),
      statement(db,'SELECT id,action,status,release_id FROM jobs WHERE request_id=?',body.request_id),
    ]);
    const job=results(batch,3)[0];
    if(!job)return json({error:'Windows no disponible, trabajo en curso o espera de un minuto'},409);
    if(job.action!==body.action||job.release_id!==(body.release_id??null))return json({error:'Idempotency conflict'},409);
    return json(job,202);
  }
  if (path === '/v1/commands' && method === 'POST') {
    const body = await readBody(request);
    assert(Object.keys(body).every(k => ['action','request_id'].includes(k)), 'Unknown field');
    assert(['kill','resume'].includes(body.action) && typeof body.request_id === 'string' && /^[A-Za-z0-9_-]{16,100}$/.test(body.request_id), 'Invalid command');
    const batch = await db.batch([
      statement(db, `INSERT INTO commands(request_id,action,expires,status,created)
        SELECT ?,?,?,'pending',? WHERE (?='kill' OR EXISTS(SELECT 1 FROM snapshots WHERE id=1 AND received_at>=?))
        ON CONFLICT(request_id) DO NOTHING`, body.request_id, body.action, now+120, now, body.action, now-120),
      statement(db, `UPDATE commands SET status='superseded' WHERE status='pending' AND id <
        (SELECT id FROM commands WHERE request_id=? AND action=?)`, body.request_id, body.action),
      statement(db, 'SELECT id,action,status,expires FROM commands WHERE request_id=?', body.request_id),
    ]);
    const command = results(batch, 2)[0];
    if (!command) return json({ error: 'Windows sin conexión reciente; reanudación bloqueada' }, 409);
    if (command.action !== body.action) return json({ error: 'Idempotency conflict' }, 409);
    return json({ id: command.id, status: command.expires<=now && command.status==='pending' ? 'expired' : command.status }, 202);
  }
  if (path === '/v1/logout' && method === 'POST') {
    await statement(db, 'DELETE FROM sessions WHERE token=?', session.token).run();
    return json({ ok: true }, 200, { 'Set-Cookie': sessionCookie('', 0) });
  }
  return json({ error: 'Not found' }, 404);
}

export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) { const known=error instanceof HttpError || error instanceof UpdateError; return json({ error: known ? error.message : 'Service temporarily unavailable' }, known ? error.status : 503); }
  },
  async scheduled(_event, env) {
    const now = Math.floor(Date.now()/1000);
    await env.DB.batch([
      statement(env.DB, 'DELETE FROM sessions WHERE expires<=?', now),
      statement(env.DB, "DELETE FROM commands WHERE created<? AND status!='pending'", now-90*86400),
      statement(env.DB, "UPDATE commands SET status='expired' WHERE status='pending' AND expires<=?", now),
      statement(env.DB,"UPDATE jobs SET status='failed',message='Windows no confirmó el resultado dentro del límite' WHERE status='running' AND created<=?",now-JOB_MAX_SECONDS),
      statement(env.DB,"DELETE FROM jobs WHERE created<? AND status IN ('completed','failed','expired')",now-90*86400),
    ]);
  },
};
