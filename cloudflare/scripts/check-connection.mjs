// Authenticated read-only status; no financial values or session secrets printed.
import {readFile,writeFile} from 'node:fs/promises';
const config=JSON.parse(await readFile('wrangler.production.json','utf8'));
const origin=config.vars.PORTAL_ORIGIN;
if(!/^https:\/\/crypto-paper-private-portal\.[a-z0-9-]+\.workers\.dev$/.test(origin))throw new Error('Unexpected destination');
const password=(await readFile('.secrets/owner-access-key.txt','utf8')).trim();
const request=(path,options={})=>fetch(origin+path,{...options,redirect:'error',signal:AbortSignal.timeout(15000)});
const login=await request('/v1/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({password})});
if(login.status!==200)throw new Error('Owner login failed');
const cookie=login.headers.get('set-cookie').split(';')[0];
const {csrf}=await login.json();
try{
  const response=await request('/v1/status',{headers:{Cookie:cookie}});
  if(response.status!==200)throw new Error('Status unavailable');
  const state=await response.json();
  const report={at:new Date().toISOString(),connected:!state.stale,mode:state.snapshot?.mode,received_at:state.received_at,last_cycle_at:state.snapshot?.last_cycle_at,
    dashboard_available:!!state.snapshot?.dashboard,jobs_api:Array.isArray(state.jobs),commands_count:state.commands.length,jobs_count:state.jobs?.length||0,orders_sent:false};
  await writeFile('connection-verification.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  if(!report.connected||report.mode!=='PAPER'||!report.dashboard_available||!report.jobs_api)process.exitCode=1;
}finally{
  const response=await request('/v1/logout',{method:'POST',headers:{Origin:origin,Cookie:cookie,'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:'{}'});
  if(response.status!==200)throw new Error('Session cleanup failed');
}
