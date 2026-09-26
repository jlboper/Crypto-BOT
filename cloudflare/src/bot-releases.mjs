const encoder=new TextEncoder();
const repo='jlboper/Crypto-BOT',repositoryId='1366739763';
const issuer='https://token.actions.githubusercontent.com';
export const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const decode=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
const digest=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
class ReleaseValidationError extends Error {}
function require(value,message){if(!value)throw new ReleaseValidationError(message);}
// Only our fixed validation labels may leave the signer; runtime/provider errors
// can contain sensitive material and are deliberately reduced to a constant.
export function releaseFailureCode(error){
  return error instanceof ReleaseValidationError
    ? error.message.toLowerCase().replace(/[^a-z0-9]+/g,'_')
    : 'signing_runtime_failure';
}
export async function authorizePublisher(token,origin,now,transport=fetch){
  require(typeof token==='string'&&token.length<20000,'Invalid publisher token');
  const parts=token.split('.');require(parts.length===3,'Invalid publisher token');
  const header=JSON.parse(new TextDecoder().decode(decode(parts[0])));
  const claim=JSON.parse(new TextDecoder().decode(decode(parts[1])));
  require(header.alg==='RS256'&&typeof header.kid==='string','Invalid publisher algorithm');
  const response=await transport(issuer+'/.well-known/jwks',{redirect:'manual',signal:AbortSignal.timeout(10000)});
  require(response.ok,'Publisher keys unavailable');
  const keys=await response.json();const jwk=keys.keys?.find(k=>k.kid===header.kid&&k.kty==='RSA');
  require(jwk,'Unknown publisher key');
  const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
  require(await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decode(parts[2]),encoder.encode(parts[0]+'.'+parts[1])),'Invalid publisher signature');
  require(claim.iss===issuer&&claim.aud===origin+'/bot-releases','Invalid publisher audience');
  // Repositories created after July 15, 2026 use immutable GitHub subjects.
  require(claim.sub===`repo:jlboper@328148059/Crypto-BOT@${repositoryId}:environment:portal-production`,'Invalid publisher subject');
  require(claim.repository===repo&&claim.repository_id===repositoryId&&claim.repository_owner_id==='328148059'&&claim.ref==='refs/heads/main'&&claim.environment==='portal-production','Invalid publisher repository');
  require(claim.workflow_ref===`${repo}/.github/workflows/portal-release.yml@refs/heads/main`&&claim.event_name==='push','Invalid publisher workflow');
  require(Number.isInteger(claim.exp)&&claim.exp>now&&claim.exp<=now+900&&Number.isInteger(claim.nbf)&&claim.nbf<=now+30,'Expired publisher token');
  require(/^[a-f0-9]{40}$/.test(claim.sha)&&/^[1-9][0-9]{0,14}$/.test(claim.run_id),'Invalid publisher revision');
  return claim;
}
export function validateManifest(m,claim,now){
  require(m&&typeof m==='object'&&!Array.isArray(m),'Invalid manifest');
  require(Object.keys(m).sort().join(',')==='app,commit,expires,files,mode,package_url,runtime_protocol,sequence,sha256,size,version','Invalid manifest fields');
  require(m.app==='crypto-ai-trading-bot'&&['paper','testnet'].includes(m.mode)&&m.runtime_protocol===1,'Invalid runtime');
  require(m.commit===claim.sha&&m.sequence===Number(claim.run_id)&&Number.isSafeInteger(m.sequence),'Revision mismatch');
  require(/^\d+\.\d+\.\d+$/.test(m.version)&&Number.isInteger(m.expires)&&m.expires>now&&m.expires<=now+15*86400,'Invalid release lifetime');
  require(m.package_url===`https://raw.githubusercontent.com/${repo}/bot-releases/packages/${m.commit}.zip`,'Invalid package destination');
  require(/^[a-f0-9]{64}$/.test(m.sha256)&&Number.isInteger(m.size)&&m.size>0&&m.size<=50*1024*1024,'Invalid package digest');
  require(m.files&&typeof m.files==='object'&&!Array.isArray(m.files)&&Object.keys(m.files).length<=2000,'Invalid files');
  for(const [path,hash]of Object.entries(m.files)){
    require(/^[a-zA-Z0-9_./-]+$/.test(path)&&!path.split('/').some(p=>!p||p==='.'||p==='..'||p.startsWith('.env')||p==='__pycache__'),'Unsafe file path');
    require(/^(trader|web|scripts|tests|portal_web)\//.test(path)||['pyproject.toml','config.toml','README.md','UPDATE_NOTES.md','RESEARCH_METHODOLOGY.md'].includes(path),'Protected file path');
    require(/^[a-f0-9]{64}$/.test(hash),'Invalid file digest');
  }
  require(['trader/__main__.py','trader/runtime_control.py','pyproject.toml'].every(p=>m.files[p]),'Incomplete package');
}
export async function signRelease(env,token,manifest,now,transport=fetch){
  require(env.BOT_SIGNING_KEY,'Signing not provisioned');
  const claim=await authorizePublisher(token,env.PORTAL_ORIGIN,now,transport);
  require(claim.sha===env.PORTAL_COMMIT,'Portal and bot revision must match');
  validateManifest(manifest,claim,now);
  const encoded=canonical(manifest),id=await digest(encoded);
  const existing=await env.DB.prepare('SELECT release_id,envelope FROM bot_releases WHERE sequence=?').bind(manifest.sequence).first();
  if(existing){require(existing.release_id===id,'Release sequence conflict');return JSON.parse(existing.envelope);}
  const key=await crypto.subtle.importKey('pkcs8',decode(env.BOT_SIGNING_KEY),{name:'Ed25519'},false,['sign']);
  const signature=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.sign('Ed25519',key,encoder.encode(encoded)))));
  const envelope={manifest,signature};
  const inserted=await env.DB.prepare('INSERT INTO bot_releases(sequence,release_id,commit_sha,envelope,created) SELECT ?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM bot_releases WHERE sequence>=?) RETURNING sequence')
    .bind(manifest.sequence,id,manifest.commit,JSON.stringify(envelope),now,manifest.sequence).first();
  require(inserted,'Release sequence already superseded');
  return envelope;
}
