import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {readFileSync} from 'node:fs';
import {portal} from './helpers/portal-dom.mjs';
const markup=readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');

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
  assert.equal(p.root.querySelectorAll('details').length,45); // 39 retained + six Intelligence folds.
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
