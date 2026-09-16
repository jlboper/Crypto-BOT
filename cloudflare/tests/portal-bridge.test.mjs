import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../web/portal-bridge.js',import.meta.url),'utf8');

function node(){
  return {hidden:false,disabled:false,textContent:'',value:'',children:[],
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},
    scrollIntoView(){},addEventListener(){}};
}

function bridge(hostname,responses){
  const elements=new Map(),listeners=new Map(),calls=[];
  const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
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
    location:{hostname,hash:''},crypto:{randomUUID:()=> '12345678-1234-4234-8234-123456789abc'},
    Event:class{constructor(type){this.type=type;}},confirm:()=>true});
  vm.runInContext(source,context,{filename:'portal-bridge.js'});
  return {api:window.portalApi,calls,elements};
}

function state(overrides={}){
  return {csrf:'csrf-token',stale:false,commands:[],jobs:[],snapshot:{dashboard:{}},...overrides};
}

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
    action:'research',request_id:'12345678-1234-4234-8234-123456789abc'});
});

test('remote Research Lab exposes expiration and renders friendly action labels',async()=>{
  const instance=bridge('paper.example.workers.dev',[{status:200,body:state({
    jobs:[{id:9,action:'research',status:'expired',message:''}],
  })}]);
  const status=await instance.api('/api/research/status');
  assert.equal(status.running,false);
  assert.match(status.error,/venció/);
  assert.match(instance.elements.get('portalCommands').children[0].textContent,/Research Lab/);
});

test('localhost keeps the existing local Research endpoint',async()=>{
  const instance=bridge('localhost',[{status:202,body:{ok:true}}]);
  assert.deepEqual(await instance.api('/api/research/run',{method:'POST'}),{ok:true});
  assert.equal(instance.calls.length,1);
  assert.equal(instance.calls[0].path,'/api/research/run');
});
