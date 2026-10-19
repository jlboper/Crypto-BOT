import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const markup=readFileSync(new URL('../../../web/index.html',import.meta.url),'utf8');
const source=readFileSync(new URL('../../../web/app.js',import.meta.url),'utf8');
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
export function portal({hash='',locked=false,saved={}}={}){
  const root=parse(markup),listeners=new Map(),calls=[],storage=new Map([['crypto-ai-trader.ui.folds.v1',JSON.stringify(saved)]]);
  const get=id=>root.querySelectorAll('[id]').find(node=>node.id===id)||null;
  const document={hidden:false,getElementById:get,querySelector:selector=>root.querySelector(selector),querySelectorAll:selector=>root.querySelectorAll(selector)};
  document.querySelector('.shell').hidden=locked;
  const location={hash,pathname:'/',search:'',hostname:'127.0.0.1'},entries=[hash];let index=0;
  const history={pushState(_s,_t,url){entries.splice(++index);entries.push(new URL(url,'http://127.0.0.1').hash);location.hash=entries[index];},replaceState(_s,_t,url){entries[index]=new URL(url,'http://127.0.0.1').hash;location.hash=entries[index];},back(){if(index>0){location.hash=entries[--index];for(const callback of listeners.get('popstate')||[])callback();}},forward(){if(index<entries.length-1){location.hash=entries[++index];for(const callback of listeners.get('popstate')||[])callback();}}};
  const window={addEventListener(name,callback){const list=listeners.get(name)||[];list.push(callback);listeners.set(name,list);},requestAnimationFrame:callback=>callback(),localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},portalButtonBusy:()=>false,paperControlsAvailable:()=>true,portalApi:async(path,options)=>{calls.push({path,options});return {status:'pending'};}};
  const context=vm.createContext({document,window,location,history,URL,URLSearchParams,Date,console,navigator:{},sessionStorage:{getItem:()=>null},setInterval:()=>0,setTimeout,clearTimeout});
  vm.runInContext(source,context);vm.runInContext('refresh=async()=>{}',context);
  window.PulsePortal.init();window.FourEnginePortal.init();window.CommandCenterPortal.init();window.GuardianIntelligencePortal.init();
  return {intelligence:window.GuardianIntelligencePortal,ui:window.CommandCenterPortal,pulse:window.PulsePortal,root,get,document,window,context,location,history,listeners,calls,storage,entries};
}
