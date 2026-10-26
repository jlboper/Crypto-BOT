import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs';
import vm from 'node:vm';
import {validInstitutionalContext} from '../src/pulse-institutional.mjs';
import {portal} from './helpers/portal-dom.mjs';

const source=fs.readFileSync(new URL('../../web/pulse-institutional.js',import.meta.url),'utf8');
const produced=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8',fileURLToPath(new URL('../../tests/emit_institutional_fixture.py',import.meta.url))],{encoding:'utf8'}));
const fixture=()=>structuredClone(produced);
const view=()=>{const p=portal();vm.runInContext(source,p.context);return {...p,institutional:p.context.CryptoInstitutionalContext};};

test('Python source and shared browser/Worker agree on a bounded public context contract',()=>{
  assert.equal(validInstitutionalContext(fixture()),true);assert.equal(produced.observations.length,2);
  assert.equal(Buffer.byteLength(JSON.stringify(produced))<8000,true);
  assert.equal(produced.execution_enabled,false);assert.equal(produced.providers[1].state,'DISABLED');
});

test('validator parity rejects commands, missing provenance, future evidence and invented ETF flows',()=>{
  const cases=[fixture()];
  for(const mutate of [x=>x.execution_enabled=true,x=>x.schema=true,x=>x.mode='BUY',x=>x.api_key='secret',
    x=>x.providers[0].url='https://evil.example',x=>x.observations[0].metrics.usd_flows=100,
    x=>x.observations[0].metrics.open_interest_contracts=true,x=>x.observations[1].metrics.etf_net_flows_usd=1,
    x=>x.observations[0].received_at='2026-10-26T12:00:00.000Z',x=>x.observations[1].url='javascript:alert(1)',
    x=>x.observations[0].title='<img src=x onerror=order()>',x=>x.observations.push(structuredClone(x.observations[0])),
    x=>x.observations[0].limitations.push('BUY_NOW')]){const value=fixture();mutate(value);cases.push(value);}
  const repo=fileURLToPath(new URL('../../',import.meta.url));
  const script='import json,sys;sys.path.insert(0,sys.argv[1]);from trader.market_pulse_institutional_contract import valid_institutional_context;print(json.dumps([valid_institutional_context(x) for x in json.load(sys.stdin)]))';
  const expected=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',script,repo],{encoding:'utf8',input:JSON.stringify(cases)}));
  assert.deepEqual(cases.map(validInstitutionalContext),expected);
});

test('render distinguishes contracts, disclosure metadata, first-observed release and missing flows',()=>{
  const p=view();p.institutional.render(fixture());
  const text=p.get('pulseInstitutionalObservations').textContent;
  assert.match(text,/contratos, no flujos/i);assert.match(text,/Flujos netos de ETF: no disponibles/);
  assert.match(text,/Fecha de los datos/);assert.match(text,/primera observación/);assert.match(text,/Publicado \/ aceptado por SEC/);
  assert.match(p.get('pulseInstitutionalProviders').textContent,/contacto real del propietario/);
  assert.equal(p.calls.length,0);assert.equal(p.get('pulse-institutional').querySelectorAll('button,input,select,form').length,0);
});

test('malformed untrusted context clears figures and cannot inject markup or execute actions',()=>{
  const p=view();p.institutional.render(fixture());const invalid=fixture();invalid.observations[0].title='<img src=x onerror=order()>';
  p.institutional.render(invalid);assert.equal(p.get('pulseInstitutionalObservations').textContent,'');
  assert.match(p.get('pulseInstitutionalNote').textContent,/incompatible/);assert.equal(p.get('pulse-institutional').querySelectorAll('img,script').length,0);
  p.institutional.disconnected();assert.match(p.get('pulseInstitutionalNote').textContent,/No demuestra una caída/);assert.equal(p.calls.length,0);
});

test('context-only fold is optional and hash navigable within the existing Pulse dashboard',()=>{
  const p=portal({hash:'#pulse-institutional'});assert.equal(p.get('trading-engines').hidden,false);assert.equal(p.get('pulse-institutional').open,true);
  assert.equal(p.get('pulse-institutional').parentElement.id,'market-pulse');
  const markup=fs.readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');assert.equal([...markup.matchAll(/src="\/pulse-institutional\.js"/g)].length,1);
});
