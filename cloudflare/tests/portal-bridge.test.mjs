import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';

const source=readFileSync(new URL('../../web/portal-bridge.js',import.meta.url),'utf8');

function node(){
  return {hidden:false,disabled:false,textContent:'',value:'',children:[],attributes:{},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},
    scrollIntoView(){},addEventListener(){},
    setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name];}};
}

function bridge(hostname,responses){
  const elements=new Map(),listeners=new Map(),calls=[];
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  for(const id of ['currentPassword','newPassword','confirmPassword','passwordPanel','passwordMessage','portalLoginMessage','savePassword'])get(id);
  const document={getElementById:get,querySelector:selector=>selector==='.shell'?get('shell'):null,
    createElement:()=>node(),addEventListener:(name,callback)=>listeners.set(name,callback)};
  const window={addEventListener(){},dispatchEvent(){}};
  const fetch=async(path,options)=>{
    calls.push({path,options});
    const response=responses.shift();
    if(!response)throw new Error('Unexpected fetch');
    return {ok:response.status<400,status:response.status,json:async()=>structuredClone(response.body)};
  };
  const context=vm.createContext({document,window,fetch,structuredClone,console,Date,setTimeout,
    location:{hostname,hash:''},crypto:webcrypto,TextEncoder,btoa,
    Event:class{constructor(type){this.type=type;}},confirm:()=>true});
  vm.runInContext(source,context,{filename:'portal-bridge.js'});
  return {api:window.portalApi,calls,elements,start:()=>listeners.get('DOMContentLoaded')()};
}

function state(overrides={}){
  return {csrf:'csrf-token',stale:false,commands:[],jobs:[],snapshot:{dashboard:{}},...overrides};
}

test('bot install approval carries the exact verified release and CSRF token',async()=>{
  const candidate={release_id:'a'.repeat(64),version:'0.6.3',commit:'b'.repeat(40),expires:Date.now()/1000+3600,enabled:true};
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state({snapshot:{bot_update:candidate}})},
    {status:202,body:{id:22,status:'pending'}}]);
  instance.start();
  await instance.elements.get('installBotUpdate').onclick();
  const request=instance.calls[1];
  assert.equal(request.path,'/v1/jobs');
  assert.equal(JSON.parse(request.options.body).release_id,candidate.release_id);
  assert.equal(request.options.headers['X-CSRF-Token'],'csrf-token');
  assert.equal(instance.elements.get('installBotUpdate').disabled,true);
});

test('remote PAPER close sends the exact confirmed position through CSRF and waits for Windows',async()=>{
  const payload={symbol:'BTCUSDT',opened_at:'2026-01-01T00:00:00Z',reference_price:101};
  const instance=bridge('paper.example.workers.dev',[
    {status:200,body:state({snapshot:{dashboard:{},paper_controls:true}})},
    {status:202,body:{id:31,action:'paper_close',status:'pending'}}]);
  const result=await instance.api('/api/paper/close-position',{method:'POST',body:JSON.stringify(payload)});
  assert.equal(result.status,'pending');
  assert.equal(instance.calls[1].path,'/v1/paper-controls');
  assert.equal(JSON.parse(instance.calls[1].options.body).payload.opened_at,payload.opened_at);
  assert.equal(instance.calls[1].options.headers['X-CSRF-Token'],'csrf-token');
});

test('restore in options submits the exact previous version and keeps CSRF',async()=>{
  const offer={restore_id:'a'.repeat(64),current_release_id:'b'.repeat(64),version:'0.6.2',current_version:'0.6.3',enabled:true};
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state({snapshot:{bot_restore:offer}})},
    {status:202,body:{id:23,status:'pending'}}]);
  instance.start();
  await instance.elements.get('restoreBotVersion').onclick();
  const request=instance.calls[1];
  assert.equal(request.path,'/v1/jobs');
  assert.equal(JSON.parse(request.options.body).release_id,offer.restore_id);
  assert.equal(JSON.parse(request.options.body).action,'update_restore');
  assert.equal(request.options.headers['X-CSRF-Token'],'csrf-token');
});

test('options menu groups maintenance and account actions',()=>{
  const instance=bridge('paper.example.workers.dev',[]);
  instance.start();
  instance.elements.get('optionsMenu').hidden=true;
  instance.elements.get('optionsButton').onclick();
  assert.equal(instance.elements.get('optionsMenu').hidden,false);
  assert.equal(instance.elements.get('optionsButton').getAttribute('aria-expanded'),'true');
  instance.elements.get('updateButton').onclick();
  assert.equal(instance.elements.get('optionsMenu').hidden,true);
  assert.equal(instance.elements.get('updatePanel').hidden,false);
});

test('one update search checks GitHub and asks Windows to verify the bot',async()=>{
  const instance=bridge('paper.example.workers.dev',[
    {status:200,body:state()},
    {status:200,body:{message:'Publicación consultada',runs:[]}},
    {status:202,body:{id:31,action:'update_check',status:'pending'}},
  ]);
  instance.start();
  await instance.elements.get('checkAllUpdates').onclick();
  assert.deepEqual(instance.calls.map(call=>call.path),['/v1/status','/v1/updates','/v1/jobs']);
  assert.equal(JSON.parse(instance.calls[2].options.body).action,'update_check');
  assert.equal(instance.elements.get('updateMessage').textContent,'Publicación consultada');
  assert.match(instance.elements.get('botUpdateMessage').textContent,/Windows está verificando el paquete firmado/);
});

test('remote Research Lab uses one authenticated allowlisted job request',async()=>{
  const instance=bridge('paper.example.workers.dev',[
    {status:200,body:state()},
    {status:202,body:{id:7,action:'research',status:'pending'}},
  ]);
  const result=await instance.api('/api/research/run',{method:'POST'});
  assert.equal(result.id,7);
  assert.equal(instance.calls[0].path,'/v1/status');
  assert.equal(instance.calls[0].options.method,'GET');
  assert.equal(instance.calls[0].options.headers.Accept,'application/json');
  assert.equal(instance.calls[0].options.headers['Content-Type'],undefined);
  assert.equal(instance.calls[1].path,'/v1/jobs');
  assert.equal(instance.calls[1].options.headers['X-CSRF-Token'],'csrf-token');
  assert.deepEqual(JSON.parse(instance.calls[1].options.body),{
    action:'research',request_id:JSON.parse(instance.calls[1].options.body).request_id});
});

test('remote Research Lab exposes expiration and renders friendly action labels',async()=>{
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state({
    jobs:[{id:9,action:'research',status:'expired',message:''}],
  })}]);
  const status=await instance.api('/api/research/status');
  assert.equal(status.running,false);
  assert.match(status.error,/venció/);
  assert.match(instance.elements.get('portalCommands').children[0].textContent,/Evaluar estrategias/);
});

test('recent activity is capped at three and history loads authenticated pages from options',async()=>{
  const jobs=Array.from({length:20},(_,index)=>({id:20-index,action:'update_check',status:'completed',message:`Resultado ${index}`}));
  const instance=bridge('paper.example.workers.dev',[
    {status:200,body:state({jobs,activity:jobs.slice(0,3)})},
    {status:200,body:{items:jobs.slice(0,2),next_page:1,retention_days:90}},
    {status:200,body:{items:jobs.slice(2,3),next_page:null,retention_days:90}},
  ]);
  instance.start();
  await instance.api('/api/status');
  assert.equal(instance.elements.get('portalCommands').children.length,3);
  await instance.elements.get('historyButton').onclick();
  assert.equal(instance.calls[1].path,'/v1/activity/0');
  assert.equal(instance.elements.get('historyRows').children.length,2);
  await instance.elements.get('loadMoreHistory').onclick();
  assert.equal(instance.calls[2].path,'/v1/activity/1');
  assert.equal(instance.elements.get('historyRows').children.length,3);
  assert.equal(instance.elements.get('loadMoreHistory').hidden,true);
});

test('PAPER evidence is optional until the stable Windows agent is updated',async()=>{
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state({snapshot:{dashboard:{status:{mode:'PAPER'},paper_scorecard:{mode:'PAPER',status:'INSUFFICIENT_EVIDENCE',equity_points:1}}}})}]);
  const report=await instance.api('/api/paper-scorecard');
  assert.equal(report.mode,'PAPER');
  assert.equal(report.status,'INSUFFICIENT_EVIDENCE');
  assert.deepEqual(await instance.api('/api/paper-scorecard'),report);
  assert.equal(instance.calls.length,1);
});

test('localhost keeps the existing local Research endpoint',async()=>{
  const instance=bridge('localhost',[{status:202,body:{ok:true}}]);
  assert.deepEqual(await instance.api('/api/research/run',{method:'POST'}),{ok:true});
  assert.equal(instance.calls.length,1);
  assert.equal(instance.calls[0].path,'/api/research/run');
});

test('password form sends authenticated request and clears secrets after success',async()=>{
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state()},{status:200,body:{scheme:'initial-key'}},{status:200,body:{ok:true}}]);
  instance.start();
  instance.elements.get('currentPassword').value='old-test-password';
  instance.elements.get('newPassword').value=instance.elements.get('confirmPassword').value='new-test-password-long';
  await instance.elements.get('passwordForm').onsubmit({preventDefault(){}});
  assert.equal(instance.calls[2].path,'/v1/password');
  assert.equal(instance.calls[2].options.headers['X-CSRF-Token'],'csrf-token');
  assert.equal(instance.calls[2].options.body.includes('new-test-password-long'),false);
  assert.match(JSON.parse(instance.calls[2].options.body).new_password,/^[a-f0-9]{64}$/);
  for(const id of ['currentPassword','newPassword','confirmPassword'])assert.equal(instance.elements.get(id).value,'');
  assert.equal(instance.elements.get('shell').hidden,true);
  assert.match(instance.elements.get('portalLoginMessage').textContent,/Contraseña cambiada/);
});

test('password mismatch makes no request and failure clears sensitive inputs',async()=>{
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state()},{status:200,body:{scheme:'initial-key'}},{status:400,body:{error:'Contraseña actual incorrecta'}}]);
  instance.start();
  instance.elements.get('currentPassword').value='old-test-password';
  instance.elements.get('newPassword').value='new-test-password-long';
  instance.elements.get('confirmPassword').value='different-password';
  await instance.elements.get('passwordForm').onsubmit({preventDefault(){}});
  assert.equal(instance.calls.length,0);
  instance.elements.get('confirmPassword').value='new-test-password-long';
  await instance.elements.get('passwordForm').onsubmit({preventDefault(){}});
  for(const id of ['currentPassword','newPassword','confirmPassword'])assert.equal(instance.elements.get(id).value,'');
  assert.equal(instance.elements.get('savePassword').disabled,false);
  assert.match(instance.elements.get('passwordMessage').textContent,/incorrecta/);
});
