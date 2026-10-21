import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {validResearchValidation} from '../src/research-validation.mjs';
import {portal} from './helpers/portal-dom.mjs';

const fixture=()=>JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8',fileURLToPath(new URL('../../tests/emit_research_validation_fixture.py',import.meta.url))],{encoding:'utf8'}));
const source=fs.readFileSync(new URL('../../web/research-validation.js',import.meta.url),'utf8');

test('Python research summary uses the same closed browser and Worker schema',()=>{
  const value=fixture();
  assert.equal(validResearchValidation(value),true);
  assert.equal(globalThis.CryptoResearchValidation.valid(value),true);
  assert.equal(value.engines.length,4);
});

test('authority, inferred gains, unknown keys, incoherent replay and future evidence are refused',()=>{
  const value=fixture();
  for(const mutate of [x=>x.controls_enabled=true,x=>x.reservations_enabled=true,x=>x.execution_enabled=true,x=>x.promotion_allowed=true,x=>x.autonomy_level=1,x=>x.comparison.aggregate_capital=4000,x=>x.comparison.best_strategy='SPOT',x=>x.engines[0].attribution.estimated_losses_avoided=10,x=>x.engines[0].attribution.causal_claim_allowed=true,x=>x.engines[1].execution_validated=true,x=>x.extra='untrusted',x=>x.engines[0].extra=true,x=>x.engines[0].engine='FUTURES',x=>x.engines[3].replay={checked:16,matches:16,mismatches:1,unavailable:0,sampled:16},x=>x.engines[0].evidence_at='2099-01-01T00:00:00Z',x=>x.control_preconditions[0].state='APPROVED',x=>x.engines[0].limitations=['<script>']]){
    const next=structuredClone(value);mutate(next);assert.equal(validResearchValidation(next),false);
  }
});

test('invalid dates, oversized text and malformed monetary/count inputs never turn into a result',()=>{
  const value=fixture();
  for(const mutate of [x=>x.captured_at='today',x=>x.source_generated_at='2099-01-01T00:00:00Z',x=>x.state='APPROVED',x=>x.engines[0].strategies_or_assets=true,x=>x.engines[0].strategies_or_assets=-1,x=>x.engines[2].replay={checked:1,mismatches:1001,invalid_timestamps:0},x=>x.engines[0].limitations=['x'.repeat(20000)]]){
    const next=structuredClone(value);mutate(next);assert.equal(validResearchValidation(next),false);
  }
});

test('Pulse timestamp and rule-version failures remain visible even before numerical replay',()=>{
  const value=fixture();value.engines[2].replay={checked:0,mismatches:2,invalid_timestamps:3};
  assert.equal(validResearchValidation(value),true);
  const p=portal();vm.runInContext(source,p.context);p.context.CryptoResearchValidation.render(value);
  assert.match(p.get('researchValidationEngines').textContent,/0 comprobados · 2 divergencias · 3 tiempos inválidos/);
});

test('rendered research matrix explains four separate scopes and keeps unknown counterfactuals explicit',()=>{
  const p=portal();vm.runInContext(source,p.context);
  p.context.CryptoResearchValidation.render(fixture());
  assert.equal(p.get('researchValidationState').textContent,'EVIDENCIA PARCIAL · SOLO LECTURA');
  assert.equal(p.get('researchValidationEngines').children.filter(node=>node.tagName==='ARTICLE').length,4);
  assert.match(p.get('researchValidationEngines').textContent,/Mercado público.*SHADOW/s);
  assert.match(p.get('researchControlReadiness').textContent,/Pérdidas evitadas.*no evaluables/);
  assert.match(p.get('researchControlReadiness').textContent,/autorización separada requerida/);
  assert.equal(p.calls.length,0);
});

test('absent or forged matrix clears prior figures and makes no control or provider request',()=>{
  const p=portal();vm.runInContext(source,p.context);const ui=p.context.CryptoResearchValidation;
  ui.render(fixture());ui.render(null);
  assert.equal(p.get('researchValidationState').textContent,'SIN MATRIZ ARCHIVADA');
  assert.equal(p.get('researchValidationEngines').textContent,'');
  const forged=fixture();forged.controls_enabled=true;ui.render(forged);
  assert.equal(p.get('researchValidationState').textContent,'MATRIZ NO COMPATIBLE');
  assert.equal(p.calls.length,0);
});
