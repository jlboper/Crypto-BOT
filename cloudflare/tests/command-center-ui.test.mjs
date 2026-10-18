import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const markup=readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
const source=readFileSync(new URL('../../web/app.js',import.meta.url),'utf8');
const decode=value=>value.replace(/&(?:amp|lt|gt|quot|#39);/g,x=>({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[x]));

// A DOM with real parentage, attributes and selectors, built from the shipped HTML.
// Unlike ID-generating stubs it rejects missing targets and detects duplicate IDs.
class Element {
  constructor(tagName,attributes={},parentElement=null){
    this.tagName=tagName.toUpperCase();this.attributes=new Map(Object.entries(attributes));this.parentElement=parentElement;
    this.children=[];this.listeners=new Map();this._text='';this._html='';this.hidden=this.attributes.has('hidden');this.open=this.attributes.has('open');this.disabled=this.attributes.has('disabled');
    this.dataset=Object.fromEntries([...this.attributes].filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),value]));
    this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};
  }
  get id(){return this.getAttribute('id')||'';}
  get className(){return this.getAttribute('class')||'';}
  set className(value){this.setAttribute('class',value);}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set textContent(value){this._text=String(value);this._html='';this.children=[];}
  get innerHTML(){return this._html;}
  set innerHTML(value){this._html=String(value);this.children=[];this._text='';parse(this._html,this);}
  getAttribute(key){return this.attributes.get(key)??null;}
  setAttribute(key,value){this.attributes.set(key,String(value));}
  removeAttribute(key){this.attributes.delete(key);}
  get clientWidth(){for(let node=this;node;node=node.parentElement)if(node.hidden||(node.tagName==='DETAILS'&&!node.open))return 0;return 800;}
  get clientHeight(){return 190;}
  addEventListener(name,callback,options){const listeners=this.listeners.get(name)||[];listeners.push({callback,capture:options===true});this.listeners.set(name,listeners);}
  async dispatch(name,extra={}){const event={target:this,button:0,preventDefault(){this.defaultPrevented=true;},...extra};for(const {callback} of (this.listeners.get(name)||[]).toSorted((a,b)=>Number(b.capture)-Number(a.capture)))await callback(event);return event;}
  click(){return this.dispatch('click');}
  scrollIntoView(){this.scrolled=(this.scrolled||0)+1;}
  focus(){this.focused=true;}
  getContext(){this.drawn=(this.drawn||0)+1;return {scale(){},clearRect(){},fillText(){},beginPath(){},lineTo(){},moveTo(){},closePath(){},fill(){},stroke(){},createLinearGradient(){return {addColorStop(){}};}};}
  querySelectorAll(selectors){const all=[];const visit=node=>{for(const child of node.children){all.push(child);visit(child);}};visit(this);return all.filter(node=>selectors.split(',').some(selector=>matches(node,selector.trim())));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
function matches(node,selector){
  const parts=selector.split(/\s+/),simple=parts.pop();
  const attrs=[...simple.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
  const bare=simple.replace(/\[[^\]]*\]/g,'');
  const tag=bare.match(/^[\w-]+/)?.[0],id=bare.match(/#([\w-]+)/)?.[1],classes=[...bare.matchAll(/\.([\w-]+)/g)].map(m=>m[1]);
  if(tag&&node.tagName!==tag.toUpperCase()||id&&node.id!==id||classes.some(c=>!node.className.split(/\s+/).includes(c))||attrs.some(([,key,value])=>node.getAttribute(key)===null||value!==undefined&&node.getAttribute(key)!==value))return false;
  if(!parts.length)return true;
  for(let parent=node.parentElement;parent;parent=parent.parentElement)if(matches(parent,parts.join(' ')))return true;
  return false;
}
function parse(html,root=new Element('document')){
  const stack=[root],voids=new Set(['meta','link','img','input','hr','br','source','wbr']);
  for(const token of html.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g)||[]){
    if(token.startsWith('<!'))continue;
    if(token.startsWith('</')){assert.equal(stack.at(-1).tagName,token.slice(2,-1).trim().toUpperCase(),'HTML nesting must remain valid');stack.pop();continue;}
    if(token.startsWith('<')){
      const tag=token.match(/^<([\w-]+)/)?.[1];if(!tag)continue;
      const attributes={};for(const match of token.slice(tag.length+1,-1).matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attributes[match[1]]=decode(match[2]??match[3]??match[4]??'');
      const node=new Element(tag,attributes,stack.at(-1));stack.at(-1).children.push(node);if(!voids.has(tag))stack.push(node);
    }else stack.at(-1)._text+=decode(token);
  }
  return root;
}
function portal({hash='',locked=false,saved={}}={}){
  const root=parse(markup),listeners=new Map(),calls=[],storage=new Map([['crypto-ai-trader.ui.folds.v1',JSON.stringify(saved)]]);
  const get=id=>root.querySelectorAll('[id]').find(node=>node.id===id)||null;
  const document={hidden:false,getElementById:get,querySelector:selector=>root.querySelector(selector),querySelectorAll:selector=>root.querySelectorAll(selector)};
  document.querySelector('.shell').hidden=locked;
  const location={hash,pathname:'/',search:'',hostname:'127.0.0.1'},entries=[hash];let index=0;
  const history={pushState(_s,_t,url){entries.splice(++index);entries.push(new URL(url,'http://127.0.0.1').hash);location.hash=entries[index];},replaceState(_s,_t,url){entries[index]=new URL(url,'http://127.0.0.1').hash;location.hash=entries[index];},back(){if(index>0){location.hash=entries[--index];for(const callback of listeners.get('popstate')||[])callback();}},forward(){if(index<entries.length-1){location.hash=entries[++index];for(const callback of listeners.get('popstate')||[])callback();}}};
  const window={addEventListener(name,callback){const list=listeners.get(name)||[];list.push(callback);listeners.set(name,list);},requestAnimationFrame:callback=>callback(),localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},portalButtonBusy:()=>false,paperControlsAvailable:()=>true,portalApi:async(path,options)=>{calls.push({path,options});return {status:'pending'};}};
  const context=vm.createContext({document,window,location,history,URL,URLSearchParams,Date,console,navigator:{},sessionStorage:{getItem:()=>null},setInterval:()=>0,setTimeout,clearTimeout});
  vm.runInContext(source,context);vm.runInContext('refresh=async()=>{}',context);
  window.PulsePortal.init();window.FourEnginePortal.init();window.CommandCenterPortal.init();
  return {ui:window.CommandCenterPortal,pulse:window.PulsePortal,root,get,document,window,context,location,history,listeners,calls,storage,entries};
}
const active=p=>p.root.querySelectorAll('[data-workspace]').filter(node=>!node.hidden).map(node=>node.dataset.workspace);
const now=()=>new Date().toISOString();
const guardian=()=>({schema:1,engine:'PORTFOLIO_GUARDIAN',mode:'OBSERVER',state:'PARTIAL',controls_enabled:false,can_veto:false,execution_enabled:false,at:now(),reservations:{state:'NOT_INTEGRATED',reserved_usdt:null},alerts:[],scopes:[
  {id:'SPOT',environment:'SPOT_TESTNET',state:'FRESH',position_count:2,gross_usdt:20,net_usdt:20,capital:{state:'FRESH',at:now(),equity_usdt:1010,cash_usdt:990,available_usdt:null}},
  {id:'FUTURES',environment:'FUTURES_DEMO',state:'PARTIAL',position_count:3,gross_usdt:null,net_usdt:null,capital:{state:'UNKNOWN',at:now(),equity_usdt:null,cash_usdt:null,available_usdt:null}},
  {id:'AI_MARKET_PULSE',environment:'SHADOW',state:'FRESH',position_count:0,gross_usdt:0,net_usdt:0,capital:{state:'FRESH',at:now(),equity_usdt:1000,cash_usdt:1000,available_usdt:null}},
  {id:'QUANT_ARBITRAGE',environment:'SHADOW',state:'NOT_STARTED',position_count:null,capital:{state:'UNKNOWN'}}]});

test('shipped markup has seven exclusive workspaces, unique IDs and the original financial/control targets',()=>{
  const p=portal(),ids=p.root.querySelectorAll('[id]').map(node=>node.id);
  assert.equal(new Set(ids).size,ids.length);assert.equal(p.root.querySelectorAll('[data-workspace]').length,7);assert.deepEqual(active(p),['command-center']);
  assert.equal(p.root.querySelectorAll('details').length,39);
  for(const id of ['killButton','pauseFuturesForward','pauseMarketPulse','resumeMarketPulse','pauseQuant','resumeQuant','riskProfile','saveRiskProfile','positions','reviews','trades','events','research-lab','modelSettingsPanel','passwordPanel','updatePanel','guardianScopes'])assert.ok(p.get(id),id+' retained');
  assert.match(markup,/CRYPTO-BOT 2\.0/);assert.match(markup,/Intelligent Trading Command Center/);assert.match(p.get('guardian-ai').textContent,/LEVEL 0/);
});

test('all seven routes replace the active workspace and update desktop/mobile accessible navigation',()=>{
  const p=portal();
  for(const route of ['portfolio-capital','trading-engines','guardian-ai','operations-decisions','research-lab','system-settings','command-center']){
    assert.equal(p.ui.navigate(route,{scroll:false,focus:true}),true);assert.deepEqual(active(p),[route]);assert.equal(p.get('workspaceChoice').value,route);
    const selected=p.root.querySelectorAll('.platform-nav a').filter(node=>node.getAttribute('aria-current')==='page');assert.equal(selected.length,1);assert.equal(selected[0].getAttribute('href'),'#'+route);assert.equal(p.get(route+'-heading').focused,true);
  }
});

test('engine/fold aliases, research, activity and transient panels reveal their correct workspace',()=>{
  const p=portal();
  for(const [id,route] of [['platform-overview','command-center'],['spot-bot','trading-engines'],['futures-bot','trading-engines'],['pulse-news','trading-engines'],['quant-statistical','trading-engines'],['portfolio-guardian','guardian-ai'],['guardian-quality','guardian-ai'],['comparison-details','portfolio-capital'],['spot-finance','portfolio-capital'],['futures-finance','portfolio-capital'],['activity-section','operations-decisions'],['historyPanel','operations-decisions'],['research-lab','research-lab'],['modelSettingsPanel','system-settings'],['updates','system-settings'],['password','system-settings'],['observation-details','system-settings']]){
    assert.equal(p.pulse.revealSection(id,false),true,id);assert.deepEqual(active(p),[route],id);
    const target=p.get(p.ui.targetId(id));assert.equal(target.hidden,false);if(target.tagName==='DETAILS')assert.equal(target.open,true);
  }
  assert.equal(p.get('spot-analysis').open,true);assert.equal(p.get('diagnosticsPanel').open,true);
});

test('push navigation, browser back/forward and native hash changes preserve one view without fetching',async()=>{
  const p=portal();
  const link=p.root.querySelectorAll('.platform-nav a').find(node=>node.getAttribute('href')==='#portfolio-capital');await link.click();
  p.ui.navigate('pulse-news',{scroll:false});assert.equal(p.location.hash,'#pulse-news');p.history.back();assert.deepEqual(active(p),['portfolio-capital']);p.history.back();assert.deepEqual(active(p),['command-center']);p.history.forward();assert.deepEqual(active(p),['portfolio-capital']);
  p.location.hash='#guardian-quality';for(const callback of p.listeners.get('hashchange')||[])callback();assert.deepEqual(active(p),['guardian-ai']);assert.equal(p.get('guardian-quality').open,true);assert.equal(p.calls.length,0);
});

test('unknown, malformed, prototype and external routes fail safely to Command Center',()=>{
  for(const hash of ['#%E0%A4%A','#unknown','#constructor','#toString','#https://evil.test','#'+('a'.repeat(101))]){
    const p=portal({hash});assert.deepEqual(active(p),['command-center']);assert.equal(p.ui.navigate(hash.slice(1)),false);assert.equal(p.ui.resolve('__proto__'),null);assert.equal(p.entries.length,1);
  }
});

test('authenticated deep links restore folds and remain hidden until portal-ready completes',async()=>{
  const p=portal({hash:'#quant-statistical',locked:true,saved:{'pulse-news':true,'spot-analysis':false}});
  assert.deepEqual(active(p),['trading-engines']);assert.equal(p.get('quant-statistical').open,true);assert.equal(p.get('pulse-news').open,true);assert.equal(p.get('spot-analysis').open,false);assert.equal(p.get('quant-statistical').scrolled,undefined);assert.equal(p.document.querySelector('.shell').hidden,true);
  p.document.querySelector('.shell').hidden=false;await p.pulse.onPortalReady();assert.equal(p.get('quant-statistical').scrolled,1);
  p.get('pulse-news').open=false;await p.get('pulse-news').dispatch('toggle');assert.equal(JSON.parse(p.storage.get('crypto-ai-trader.ui.folds.v1'))['pulse-news'],false);
});

test('toolbar routes and compact mobile choice keep the existing action handlers',async()=>{
  const p=portal();let invoked=0;p.get('updateButton').addEventListener('click',()=>invoked++);
  await p.get('updateButton').click();assert.deepEqual(active(p),['system-settings']);assert.equal(invoked,1);assert.equal(p.location.hash,'#updates');
  await p.get('historyButton').click();assert.deepEqual(active(p),['operations-decisions']);
  p.get('workspaceChoice').value='guardian-ai';await p.get('workspaceChoice').dispatch('change');assert.deepEqual(active(p),['guardian-ai']);
});

test('Portfolio displays separate real typed scopes, valid zeros and unknowns without synthetic reservations or totals',()=>{
  const p=portal();p.ui.render({platform:{portfolio_guardian:guardian()}});
  const panels=p.get('capitalScopes').children.filter(node=>node.tagName==='ARTICLE');assert.equal(panels.length,4);
  assert.match(panels[0].textContent,/1,010 USDT/);assert.match(panels[0].textContent,/Disponible reportado—/);
  assert.match(panels[1].textContent,/VALORACIÓN INCOMPLETA/);assert.doesNotMatch(panels[1].textContent,/0 USDT/);
  assert.match(panels[2].textContent,/Exposición bruta0 USDT/);assert.match(panels[3].textContent,/SIN INICIAR/);assert.doesNotMatch(panels[3].textContent,/0 USDT/);
  assert.match(p.get('capitalReservations').textContent,/NO INTEGRADAS.*desconocido/);assert.doesNotMatch(p.get('capitalScopes').textContent,/2,010|Total global|Total de capital/);
});

test('old, future, incompatible or lost Guardian evidence masks every current monetary value',()=>{
  const p=portal();
  for(const changed of [{remote_sync_stale:true},{portfolio_guardian:{...guardian(),at:'2000-01-01T00:00:00Z'}},{portfolio_guardian:{...guardian(),at:new Date(Date.now()+10000).toISOString()}},{portfolio_guardian:{...guardian(),can_veto:true}}]){
    p.ui.render({platform:{portfolio_guardian:guardian(),...changed}});assert.doesNotMatch(p.get('capitalScopes').textContent,/1,010 USDT|990 USDT|1,000 USDT|0 USDT/);
  }
  p.ui.disconnected();assert.match(p.get('commandReadingState').textContent,/NO DISPONIBLE/);assert.doesNotMatch(p.get('capitalScopes').textContent,/1,010 USDT/);assert.match(p.get('commandAlerts').textContent,/sin verificar/);
});

test('Command Center uses actual bounded dated decisions and alerts, distinguishes old sources and escapes untrusted text',()=>{
  const p=portal(),attack='<img src=x onerror=steal()>',g=guardian();g.alerts=[{code:attack,scope:'SPOT',symbol:attack}];
  const reviews=Array.from({length:20},(_,i)=>({verdict:'REJECT',created_at:new Date(Date.now()-i*1000).toISOString(),symbol:'BTCUSDT',reason:attack}));
  p.ui.render({status:{mode:'TESTNET',activity:{state:'operational'}},reviews,events:[{level:'ERROR',message:attack,created_at:now()}],platform:{portfolio_guardian:g,remote_sync_stale:true}});
  assert.equal(p.get('commandDecisions').children.filter(node=>node.tagName==='ARTICLE').length,6);assert.match(p.get('commandDecisions').textContent,/Spot Bot · TESTNET · fuente antigua/);
  assert.doesNotMatch(p.get('commandDecisions').innerHTML,/<img|onerror="/);assert.match(p.get('commandDecisions').innerHTML,/&lt;img/);assert.doesNotMatch(p.get('commandAlerts').innerHTML,/<img/);assert.match(p.get('commandReadingState').textContent,/ANTIGUA/);
  p.ui.render({reviews:[{created_at:new Date(Date.now()+10000).toISOString(),symbol:'FUTURE'}]});assert.match(p.get('commandDecisions').textContent,/Sin decisiones con hora verificable/);
});

test('revealing a chart workspace redraws cached data only when its canvas is visible',()=>{
  const p=portal();vm.runInContext('lastPortalChartData={spot:[],futures:[]}',p.context);
  p.ui.navigate('guardian-ai',{scroll:false});assert.equal(p.get('equityChart').drawn,undefined);
  p.ui.navigate('spot-bot',{scroll:false});assert.ok(p.get('equityChart').drawn>0);assert.equal(p.calls.length,0);
});

test('actual isolated Quant and Guardian producer identifies instruments and preserves typed capital in Command Center',()=>{
  const p=portal();
  const platform=JSON.parse(execFileSync(process.env.PYTHON||'python',[fileURLToPath(new URL('../../tests/emit_quant_fixture.py',import.meta.url))],{encoding:'utf8'}));
  assert.ok(platform.quant.decisions.length);assert.equal(typeof platform.quant.decisions[0].instrument,'string');
  p.ui.render({platform});
  assert.match(p.get('commandDecisions').textContent,/Quant Arbitrage · SHADOW/);assert.ok(p.get('commandDecisions').textContent.includes(platform.quant.decisions[0].instrument));assert.doesNotMatch(p.get('commandDecisions').textContent,/Activo sin identificar/);
  assert.match(p.get('capitalScopes').textContent,/Capital hipotético Shadow/);assert.doesNotMatch(p.get('capitalScopes').textContent,/NaN|undefined/);
  platform.portfolio_guardian.alerts=[{code:'GROSS_LIMIT_EXCEEDED',scope:'FUTURES'},{code:'NATIVE_PROTECTION_UNCONFIRMED',scope:'SPOT'}];
  p.ui.render({platform});assert.match(p.get('commandAlerts').textContent,/Límite de exposición bruta superado/);assert.match(p.get('commandAlerts').textContent,/Protección nativa sin confirmar/);
});
