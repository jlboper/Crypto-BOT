import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {validMigrationAudit} from '../src/migration-audit.mjs';
import {portal} from './helpers/portal-dom.mjs';

const source=fs.readFileSync(new URL('../../web/migration-audit.js',import.meta.url),'utf8');
const css=fs.readFileSync(new URL('../../web/portal.css',import.meta.url),'utf8');
const markup=fs.readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
const produced=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8',fileURLToPath(new URL('../../tests/emit_migration_audit_fixture.py',import.meta.url))],{encoding:'utf8'}));
const fixture=()=>structuredClone(produced);
const current=()=>{const value=fixture();value.at=new Date().toISOString();for(const row of value.accounts)row.at=value.at;return value;};
const view=()=>{const p=portal();vm.runInContext(source,p.context);return {...p,audit:p.context.CryptoMigrationAudit};};

test('Python synthetic audit uses the same bounded closed contract in browser and Worker',()=>{
  assert.equal(validMigrationAudit(fixture()),true);
  assert.equal(globalThis.CryptoMigrationAudit.valid(fixture()),true);
  assert.equal(Buffer.byteLength(JSON.stringify(produced),'utf8')<8000,true);
  assert.deepEqual(produced.accounts.map(row=>row.environment),['SPOT_TESTNET','FUTURES_DEMO']);
  assert.equal(produced.qualified_days,null);
  assert.equal(produced.costs.proposal_usd,'100');assert.equal(produced.costs.hypothetical_usdt,'80');
});

test('Python and shared validator agree on semantic counts unknown fields and decimal boundaries',()=>{
  const cases=[fixture()];
  for(const mutate of [x=>x.schema=true,x=>x.autonomy_level=true,x=>x.execution_enabled=true,x=>x.qualified_days=30,
    x=>x.source_version='01.10.52',x=>x.source_version='1000.10.52',x=>x.accounts[0].exchange_positions=null,
    x=>x.accounts[0].open_orders=true,x=>x.accounts[0].open_orders=10001,x=>x.checks[0].total=0,
    x=>x.checks[0].passed=0,x=>x.checks[0].state='FAILED',x=>x.costs.state='FEASIBLE_HYPOTHESIS',
    x=>x.costs.proposal_usd='0',x=>x.costs.hypothetical_usdt='0.01',x=>x.costs.hypothetical_usdt='1000000000.01',
    x=>x.costs.hypothetical_usdt='1000000000',x=>x.costs.proposal_usd='100.00',x=>x.cohort.receipt_days=30,
    x=>x.at='0000-01-01T00:00:00.000Z',x=>x.accounts[0].private_id='private']){
    const value=fixture();mutate(value);cases.push(value);
  }
  const repo=fileURLToPath(new URL('../../',import.meta.url));
  const script='import json,sys;sys.path.insert(0,sys.argv[1]);from trader.migration_audit import valid_migration_audit;print(json.dumps([valid_migration_audit(x) for x in json.load(sys.stdin)]))';
  const expected=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',script,repo],{encoding:'utf8',input:JSON.stringify(cases)}));
  assert.deepEqual(cases.map(validMigrationAudit),expected);
});

test('authority, complete-account certification, ready days and unknown fields are refused',()=>{
  const flags=['execution_enabled','controls_enabled','reservations_enabled','promotion_allowed','financial_authorization','automatic_activation','can_veto','accounts_linked','complete_exchange_inventory','history_complete'];
  for(const mutate of [...flags.map(key=>x=>x[key]=true),x=>x.schema=true,x=>x.engine='LIVE',x=>x.mode='LIVE',x=>x.autonomy_level=1,
    x=>x.qualified_days=30,x=>x.extra=false,x=>x.source_version='01.10.52',x=>x.source_version='0.10.52;placeOrder()',x=>x.accounts[0].uid=123,
    x=>x.accounts[0].accountAlias='private',x=>x.costs.wallet_balance='100',x=>x.cohort.ready=true]){
    const value=fixture();mutate(value);assert.equal(validMigrationAudit(value),false);
  }
});

test('strict UTC report and account cuts reject invalid dates and account evidence after the report',()=>{
  for(const at of ['today','2026-02-30T01:00:00.000Z','2026-10-23T01:00:00Z','2026-10-23T01:00:00.000+00:00','2026-10-23T01:00:00.000Z\n']){
    const value=fixture();value.at=at;assert.equal(validMigrationAudit(value),false);
  }
  const value=current();value.accounts[0].at=new Date(Date.parse(value.at)+1).toISOString();assert.equal(validMigrationAudit(value),false);
});

test('accounts remain exactly ordered, bounded and independently unknown instead of zero',()=>{
  for(const mutate of [x=>x.accounts.reverse(),x=>x.accounts.pop(),x=>x.accounts[0].environment='LIVE',x=>x.accounts[0].state='CERTIFIED',
    x=>x.accounts[0].identity='VERIFIED',x=>x.accounts[0].quantity_check='HEDGED',x=>x.accounts[0].local_positions=true,
    x=>x.accounts[0].exchange_positions=-1,x=>x.accounts[0].open_orders=10001,x=>x.accounts[0].conditional_orders=1.5]){
    const value=fixture();mutate(value);assert.equal(validMigrationAudit(value),false);
  }
  const value=current();for(const row of value.accounts){row.state='UNKNOWN';row.at=null;row.identity='UNKNOWN';for(const key of ['local_positions','exchange_positions','open_orders','conditional_orders'])row[key]=null;}
  assert.equal(validMigrationAudit(value),true);
  const p=view();p.audit.render(value);
  assert.match(p.get('migrationAuditAccounts').textContent,/Posiciones localesDesconocido/);
  assert.match(p.get('migrationAuditAccounts').textContent,/Órdenes estándarDesconocido/);
  assert.doesNotMatch(p.get('migrationAuditAccounts').textContent,/Posiciones locales0|Órdenes estándar0/);
});

test('only three explicit synthetic checks with coherent PASS FAIL and unknown counts are accepted',()=>{
  for(const mutate of [x=>x.checks.reverse(),x=>x.checks[0].state='LIVE_READY',x=>x.checks[0].passed=0,x=>x.checks[0].passed=1,
    x=>x.checks[0].total=0,x=>x.checks[0].total=1001,x=>x.checks[0].passed=true,x=>x.checks[0].state='NOT_RUN',
    x=>x.checks[0].state='FAILED',x=>x.checks[0].evidence='private']){
    const value=fixture();mutate(value);assert.equal(validMigrationAudit(value),false);
  }
  const value=current();value.checks[0]={id:'CAPITAL_FLOW',state:'FAILED',passed:1,total:2};
  value.checks[1]={id:'RISK_LATCHES',state:'NOT_RUN',passed:null,total:null};value.checks[2]={id:'RECOVERY',state:'UNAVAILABLE',passed:null,total:null};
  assert.equal(validMigrationAudit(value),true);
  const p=view();p.audit.render(value);assert.match(p.get('migrationAuditChecks').textContent,/Ensayo SIM con fallos · 1\/2/);
  assert.match(p.get('migrationAuditChecks').textContent,/Sin ejecutar/);assert.match(p.get('migrationAuditChecks').textContent,/No disponible/);
});

test('cost hypotheses count explicit scenarios without approving policy or converting USD to USDT',()=>{
  for(const mutate of [x=>x.costs.state='PROFITABLE',x=>x.costs.state='FEASIBLE_HYPOTHESIS',x=>x.costs.scenarios=101,x=>x.costs.feasible=3,x=>x.costs.rejected=null,
    x=>x.costs.scenarios=true,x=>x.costs.feasible=-1,x=>x.costs.rejected=0.5]){
    const value=fixture();mutate(value);assert.equal(validMigrationAudit(value),false);
  }
  for(const amount of [100,true,'0','01','100.00','1e2','-1','NaN','1000000000.01','0.001','1'.repeat(100)]){
    const value=fixture();value.costs.proposal_usd=amount;assert.equal(validMigrationAudit(value),false,String(amount).slice(0,25));
  }
  for(const amount of [null,'0.01','100.1','1000000000']){const value=fixture();value.costs.hypothetical_usdt=amount;assert.equal(validMigrationAudit(value),true);}
  const p=view();p.audit.render(current());
  assert.match(p.get('migrationAuditCapital').textContent,/100 USD.*80 USDT.*Importes separados/s);
  assert.doesNotMatch(p.get('migrationAuditCapital').textContent,/180|equivalente|saldo total/);
});

test('forward receipt counts never become certified days or automatic LIVE approval',()=>{
  for(const mutate of [x=>x.cohort.state='CERTIFIED',x=>x.cohort.receipt_days=36501,x=>x.cohort.receipt_days=1.5,
    x=>x.cohort.receipt_days=true,x=>x.cohort.missing_windows=50000001,x=>x.cohort.missing_windows=-1]){
    const value=fixture();mutate(value);assert.equal(validMigrationAudit(value),false);
  }
  const value=current();value.cohort={state:'SUPPLIED_RECEIPTS_ONLY',receipt_days:30,missing_windows:0};
  const p=view();p.audit.render(value);assert.match(p.get('migrationAuditCoverage').textContent,/suministrados: 30/);
  assert.match(p.get('migrationAuditCoverage').textContent,/Días válidos certificados: desconocidos/);
  assert.equal(value.qualified_days,null);assert.equal(p.calls.length,0);
});

test('the compact audit shows separate Testnet Demo counts and synthetic results without controls',()=>{
  const p=view();p.audit.render(current());
  assert.equal(p.get('migrationAuditState').textContent,'AUDITORÍA · SOLO LECTURA');
  assert.equal(p.get('migrationAuditAccounts').querySelectorAll('article').length,2);
  assert.match(p.get('migrationAuditAccounts').textContent,/Spot Testnet.*Futures Demo/s);
  assert.match(p.get('migrationAuditAccounts').textContent,/cuentas sin vincular/);
  assert.equal(p.get('migrationAuditChecks').querySelectorAll('article').length,3);
  assert.match(p.get('migrationAuditChecks').textContent,/Ensayo SIM aprobado/);
  assert.match(p.get('migration-audit').textContent,/No acreditan un reinicio real de Windows ni admisión conjunta/);
  assert.equal(p.get('migration-audit').querySelectorAll('button,input,select,form').length,0);
  assert.equal(p.calls.length,0);
});

test('refresh retains the original evidence cut and never replaces it with now',()=>{
  const p=view(),value=current();value.at='2026-01-02T03:04:05.000Z';for(const row of value.accounts)row.at=value.at;
  const before=structuredClone(value);p.audit.render(value);const note=p.get('migrationAuditNote').textContent;p.audit.render(value);
  assert.equal(p.get('migrationAuditNote').textContent,note);assert.deepEqual(value,before);
  assert.match(p.get('migrationAuditState').textContent,/INFORME HISTÓRICO/);
  assert.match(p.get('migrationAuditAccounts').textContent,/Corte histórico/);
});

test('source age, future clock and remote sync are separate observations',()=>{
  const p=view();p.audit.render(current(),true);
  assert.equal(p.get('migrationAuditState').textContent,'AUDITORÍA · SOLO LECTURA');
  assert.match(p.get('migrationAuditNote').textContent,/sincronización remota no está vigente/);
  assert.doesNotMatch(p.get('migrationAuditNote').textContent,/El corte es histórico/);
  for(const offset of [-91000,6000]){const value=current();value.at=new Date(Date.now()+offset).toISOString();for(const row of value.accounts)row.at=value.at;
    p.audit.render(value);assert.match(p.get('migrationAuditState').textContent,/INFORME HISTÓRICO/);assert.match(p.get('migrationAuditNote').textContent,/no describe el estado actual/);}
  const value=current();value.accounts[0].at='2026-01-02T03:04:05.000Z';p.audit.render(value);
  assert.equal(p.get('migrationAuditState').textContent,'AUDITORÍA · SOLO LECTURA');assert.match(p.get('migrationAuditAccounts').textContent,/Corte histórico/);
});

test('absent incompatible and disconnected reports clear all earlier figures without requests',()=>{
  const p=view();
  for(const value of [null,{...current(),execution_enabled:true},{...current(),at:'<img src=x onerror=alert(1)>'}]){
    p.audit.render(current());p.audit.render(value);
    assert.equal(p.get('migrationAuditAccounts').textContent,'');assert.equal(p.get('migrationAuditChecks').textContent,'');
    assert.equal(p.get('migrationAuditCapital').textContent,'Importes desconocidos; sin asignación.');
    assert.equal(p.get('migration-audit').querySelectorAll('img,script').length,0);
  }
  p.audit.render(current());p.audit.disconnected();assert.match(p.get('migrationAuditNote').textContent,/No permite inferir una caída/);
  assert.equal(p.get('migrationAuditAccounts').textContent,'');assert.equal(p.calls.length,0);
});

test('malicious external labels and identifiers are refused and never inserted into the DOM',()=>{
  const p=view(),value=current();value.accounts[0].identity='<img src=x onerror=alert(1)>';
  p.audit.render(value);assert.equal(p.get('migrationAuditAccounts').textContent,'');assert.equal(p.get('migration-audit').querySelectorAll('img,script').length,0);
  assert.equal(p.calls.length,0);
});

test('the shared module loads once before app and deep links open its folded System panel',()=>{
  assert.equal([...markup.matchAll(/src="\/migration-audit\.js"/g)].length,1);
  assert.equal(markup.indexOf('src="/migration-audit.js"')<markup.indexOf('src="/app.js"'),true);
  const p=portal({hash:'#migration-audit'});assert.equal(p.get('system-settings').hidden,false);assert.equal(p.get('migration-audit').open,true);
  assert.equal(p.get('migration-audit').tagName,'DETAILS');assert.equal(p.get('migration-audit').querySelector('.migration-audit-recipes').open,false);
  assert.equal(p.get('modelSettingsPanel').hidden,true);
});

test('mobile rules use one column and wrapping values; this does not claim browser geometry',()=>{
  assert.match(css,/@media\(max-width:640px\)\{\.migration-audit-grid,\.migration-audit-checks\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/\.migration-audit-card,\.migration-audit-check\{[^}]*min-width:0;overflow-wrap:anywhere/);
  assert.match(css,/\.migration-audit-recipes>summary\{[^}]*min-height:44px/);
});
