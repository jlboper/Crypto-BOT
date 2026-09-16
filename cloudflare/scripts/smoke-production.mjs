// Verify the deployed portal without starting Windows or queuing commands.
import { readFile,writeFile } from 'node:fs/promises';
const config=JSON.parse(await readFile('wrangler.production.json','utf8'));
const origin=config.vars.PORTAL_ORIGIN;
if(!/^https:\/\/crypto-paper-private-portal\.[a-z0-9-]+\.workers\.dev$/.test(origin))throw new Error('Unexpected destination');
const checks=[];
const verify=(condition,label)=>{if(!condition)throw new Error(`Check failed: ${label}`);checks.push(label);};
async function request(path,options={}){return fetch(origin+path,{...options,redirect:'error',signal:AbortSignal.timeout(20000)});}
for(const path of ['/','/app.js','/style.css']){
  const response=await request(path);
  verify(response.status===200,`asset ${path}`);
  verify(response.headers.get('cache-control')==='no-store',`no cache ${path}`);
  verify(response.headers.get('content-security-policy')?.includes("frame-ancestors 'none'"),`CSP ${path}`);
  await response.arrayBuffer();
}
verify((await request('/v1/status')).status===401,'unauthenticated status denied');
const key=(await readFile('.secrets/owner-access-key.txt','utf8')).trim();
const login=await request('/v1/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({password:key})});
verify(login.status===200,'owner login');
const cookieHeader=login.headers.get('set-cookie')||'';
verify(['Secure','HttpOnly','SameSite=Strict'].every(value=>cookieHeader.includes(value)),'secure session cookie');
const session=cookieHeader.split(';')[0];
const {csrf}=await login.json();
try {
  const response=await request('/v1/status',{headers:{Cookie:session}});
  verify(response.status===200,'authenticated status');
  const state=await response.json();
  verify(state.snapshot===null && state.stale===true,'Windows not connected');
  verify(state.commands.length===0,'no commands queued');
  verify((await request('/v1/logout',{method:'POST',headers:{Origin:origin,Cookie:session,'Content-Type':'application/json'},body:'{}'})).status===403,'missing CSRF denied');
} finally {
  const logout=await request('/v1/logout',{method:'POST',headers:{Origin:origin,Cookie:session,'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:'{}'});
  verify(logout.status===200,'logout');
}
verify((await request('/v1/status',{headers:{Cookie:session}})).status===401,'session revoked');
await writeFile('production-verification.json',JSON.stringify({origin,at:new Date().toISOString(),checks,windows_agent_started:false,commands_sent:false},null,2));
console.log(JSON.stringify({passed:checks.length,origin,windows_agent_started:false,commands_sent:false}));
