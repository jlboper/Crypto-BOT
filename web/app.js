const money = value => `${Number(value || 0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})} USDT`;
const num = (value, digits=6) => Number(value || 0).toLocaleString('en-US',{maximumFractionDigits:digits});
const query = new URLSearchParams(location.search);
const queryToken = query.get('token') || '';
if (queryToken) {
  sessionStorage.setItem('dashboard_token', queryToken);
  query.delete('token');
  history.replaceState({}, '', `${location.pathname}${query.size ? `?${query}` : ''}${location.hash}`);
}
const token = queryToken || sessionStorage.getItem('dashboard_token') || '';
const headers = token ? {'X-Dashboard-Token': token} : {};
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
let lastResearchReport = null;
let lastPositions = [];
let currentExecutionMode = 'paper';
const paperControlsAvailable = () => typeof window.paperControlsAvailable === 'function' ? window.paperControlsAvailable() : true;

async function api(path, options={}) {
  if(window.portalApi)return window.portalApi(path,{...options,headers:{...headers,...(options.headers||{})}});
  const response = await fetch(path, {...options, headers:{...headers,...(options.headers||{})}});
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function renderChart(rows) {
  const canvas = document.getElementById('equityChart');
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext('2d'); ctx.scale(ratio,ratio); ctx.clearRect(0,0,width,height);
  if (!rows.length) { ctx.fillStyle='#8fa0ba'; ctx.font='14px system-ui'; ctx.fillText('La curva aparecerá después del primer ciclo.',16,height/2); return; }
  const values = rows.map(r=>Number(r.equity)); const min=Math.min(...values), max=Math.max(...values); const span=Math.max(max-min,1);
  const x=i=>18+(i/Math.max(values.length-1,1))*(width-36); const y=v=>18+(1-(v-min)/span)*(height-42);
  const gradient=ctx.createLinearGradient(0,0,0,height); gradient.addColorStop(0,'rgba(45,226,166,.28)'); gradient.addColorStop(1,'rgba(45,226,166,0)');
  ctx.beginPath(); values.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v))); ctx.lineTo(x(values.length-1),height-20); ctx.lineTo(x(0),height-20); ctx.closePath(); ctx.fillStyle=gradient; ctx.fill();
  ctx.beginPath(); values.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v))); ctx.strokeStyle='#2de2a6'; ctx.lineWidth=2; ctx.stroke();
}

function emptyRow(columns, text) { return `<tr><td colspan="${columns}" class="empty">${text}</td></tr>`; }
function feedEmpty(text) { return `<div class="empty">${text}</div>`; }
function shortTime(value) { return value ? new Date(value).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'short'}) : '—'; }
function activityLabel(state) {
  return ({operational:'OPERATIVO',delayed:'RETRASADO',offline:'SIN ACTIVIDAD',starting:'INICIANDO'})[state] || 'DESCONOCIDO';
}
function ageLabel(seconds) {
  if (seconds === null || seconds === undefined) return 'sin ciclos registrados';
  if (seconds < 60) return `hace ${Math.round(seconds)} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds/60)} min`;
  return `hace ${(seconds/3600).toFixed(1)} h`;
}

const pct = value => `${Number(value || 0)>=0?'+':''}${Number(value || 0).toFixed(2)}%`;

function renderPaperEvidence(report, equity, trades) {
  const evidenceMode=String(report?.mode||currentExecutionMode||'paper').toUpperCase();
  const state=document.getElementById('paperEvidenceState');
  const note=document.getElementById('paperEvidenceNote');
  const panel=document.getElementById('paperEvidenceMetrics');
  const complete=['PAPER','TESTNET'].includes(report?.mode)&&report?.equity_points>0;
  const samples=equity.filter(row=>Number.isFinite(Number(row.equity))&&Number(row.equity)>0);
  const closes=trades.filter(row=>row.side==='SELL');
  let peak=0,drawdown=0;
  for(const row of samples){const value=Number(row.equity);peak=Math.max(peak,value);drawdown=Math.max(drawdown,100*(peak-value)/peak);}
  const first=samples[0],last=samples.at(-1);
  const days=first&&last?Math.max(0,(Date.parse(last.created_at)-Date.parse(first.created_at))/86400000):0;
  const values=complete?{
    days:Number(report.observed_days),trades:Number(report.closed_trades),pnl:Number(report.net_realized_pnl_usdt),
    fees:Number(report.fees_usdt),drawdown:Number(report.sampled_max_drawdown_pct),win:report.win_rate_pct,
    points:Number(report.equity_points)
  }:{days,trades:closes.length,pnl:closes.reduce((sum,row)=>sum+Number(row.realized_pnl||0),0),
    fees:trades.reduce((sum,row)=>sum+Number(row.fee||0),0),drawdown,win:null,points:samples.length};
  state.textContent=complete?(report.status==='REVIEW_REQUIRED'?'REVISIÓN HUMANA':'EVIDENCIA INSUFICIENTE'):'MUESTRA PARCIAL';
  state.className='state '+(complete&&report.status==='REVIEW_REQUIRED'?'warning':'neutral');
  const openCount=Number(report?.open_positions||0);
  const stale=openCount>0&&report?.price_status!=='fresh';
  note.textContent=complete?
    `Historial ${report.mode} desde ${shortTime(report.started_at)}. ${stale?'Precios de posiciones abiertas ausentes o desactualizados: P&L abierto no disponible. ':''}${report.invalid_points?'Hay registros inválidos que requieren revisión. ':''}30 días y 30 cierres son solo evidencia operativa; nunca activan dinero real automáticamente.`:
    'Se muestran solo los últimos 300 puntos de equity y 50 operaciones recibidos. El historial completo aparecerá cuando el agente de Windows incorpore esta medición.';
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;
  const optionalMoney=value=>value==null?'—':`${finite(value).toFixed(2)} USDT`;
  const metrics=[
    ['Días observados',finite(values.days).toFixed(1)],
    ['Operaciones cerradas',finite(values.trades).toFixed(0)],
    ['P&amp;L realizado neto',`${finite(values.pnl).toFixed(2)} USDT`],
    ['Drawdown de equity muestreada',`${finite(values.drawdown).toFixed(2)}%`],
    ['Comisiones registradas',`${finite(values.fees).toFixed(2)} USDT`],
    ['Operaciones ganadoras',values.win===null?'—':`${finite(values.win).toFixed(1)}%`],
    ['Muestras de equity',finite(values.points).toFixed(0)],
    ['P&amp;L abierto estimado',complete?optionalMoney(report.estimated_open_pnl_usdt):'—'],
    ['Exposición abierta con precio reciente',complete?optionalMoney(report.open_exposure_usdt):'—'],
    ['Factor de beneficio realizado',complete&&report.profit_factor!=null?finite(report.profit_factor).toFixed(2):'—']
  ];
  const cards=items=>items.map(([label,value])=>`<article><span>${label}</span><strong>${value}</strong></article>`).join('');
  panel.innerHTML=cards(metrics.slice(0,4));
  document.getElementById('paperMoreMetrics').innerHTML=cards(metrics.slice(4));
  const benchmark=report?.benchmark,comparison=document.getElementById('paperBenchmark');
  comparison.textContent=benchmark?.paper_return_pct!=null&&benchmark?.btc_net_return_pct!=null?
    `Mismo período desde ${shortTime(benchmark.started_at)} (${benchmark.observed_days} días, ${benchmark.matched_points} muestras): equity ${evidenceMode} ${pct(benchmark.paper_return_pct)} · BTC con costos de referencia ${pct(benchmark.btc_net_return_pct)} · diferencia ${pct(benchmark.net_difference_pp)} puntos. BTC usa el 100% del capital; no hay libro de aportes/retiros ni evidencia suficiente para operar con dinero real.`:
    `Comparación BTC: esperando al menos dos ciclos ${evidenceMode} con cotización BTC y equity simultáneas. Los datos anteriores no se reconstruyen.`;
  const checks=[
    [Number(report?.observed_days)>=30,`Seguimiento ${evidenceMode}: ${finite(report?.observed_days).toFixed(1)} de 30 días`],
    [Number(report?.closed_trades)>=30,`Operaciones cerradas: ${finite(report?.closed_trades).toFixed(0)} de 30`],
    [Number(benchmark?.observed_days)>=30,`Comparación temporal BTC: ${finite(benchmark?.observed_days).toFixed(1)} de 30 días`],
    [complete&&Number(report?.invalid_points)===0&&report?.price_status!=='stale_or_missing','Integridad de muestras y cotizaciones abiertas'],
  ];
  const checklist=document.getElementById('readinessChecks');checklist.replaceChildren();
  for(const [ready,label] of checks){const item=document.createElement('li');item.textContent=`${ready?'✓':'○'} ${label}`;checklist.append(item);}
  const assets=complete&&Array.isArray(report.by_asset)?report.by_asset:[];
  const attribution=report?.attribution||{};
  const preflight=attribution.market_preflight||{};
  const latest=Array.isArray(preflight.recent_issues)?preflight.recent_issues:[];
  document.getElementById('marketPreflight').textContent=Number(preflight.checked)>0?
    `Compatibilidad aproximada de ${finite(preflight.checked).toFixed(0)} entradas ${evidenceMode} candidatas: ${finite(preflight.estimated_compatible).toFixed(0)} pasan los filtros públicos comprobados, ${finite(preflight.incompatible).toFixed(0)} presentan incompatibilidades y ${finite(preflight.unknown).toFixed(0)} no tienen reglas suficientes. ${latest.length?`Ejemplos recientes: ${latest.map(row=>`${row.symbol} (${Array.isArray(row.reasons)?row.reasons.join(', '):'sin detalle'})`).join(' · ')}. `:''}El valor mínimo de una orden de mercado usa precios de referencia que pueden variar; faltan Testnet y conciliación de ejecuciones.`:
    'Aún no se evaluaron candidatas con las reglas públicas de Binance Spot. El preflight se registra a partir de esta versión; no envía órdenes ni certifica ejecución.';
  const shown=assets.map(asset=>`
    <tr><td>${esc(asset.symbol)}</td><td>${finite(asset.closed_trades).toFixed(0)}</td>
    <td class="${finite(asset.net_realized_pnl_usdt)>=0?'positive':'negative'}">${optionalMoney(asset.net_realized_pnl_usdt)}</td>
    <td>${asset.win_rate_pct==null?'—':`${finite(asset.win_rate_pct).toFixed(1)}%`}</td>
    <td>${optionalMoney(asset.open_exposure_usdt)}</td><td>${optionalMoney(asset.estimated_open_pnl_usdt)}</td></tr>`).join('');
  const remaining=Number(report?.omitted_assets||0)>0?
    `<tr><td>Otros ${finite(report.omitted_assets).toFixed(0)} activos</td><td>${finite(attribution.omitted_closed_trades).toFixed(0)}</td>
    <td class="${finite(attribution.omitted_net_realized_pnl_usdt)>=0?'positive':'negative'}">${optionalMoney(attribution.omitted_net_realized_pnl_usdt)}</td><td>—</td><td>—</td><td>—</td></tr>`:'';
  document.getElementById('paperAssetRows').innerHTML=shown||remaining?shown+remaining:
    emptyRow(6,complete?'Aún no hay posiciones ni cierres.':'Disponible al sincronizar el historial completo.');
  const exitLabels={protective_stop:'Stop de protección',take_profit:'Objetivo de ganancia',trend_exit:'Salida por tendencia',other:'Otro motivo'};
  const exits=complete&&Array.isArray(attribution.exit_reasons)?attribution.exit_reasons:[];
  document.getElementById('paperExitRows').innerHTML=exits.length?exits.map(row=>
    `<tr><td>${exitLabels[row.reason]||'Otro motivo'}</td><td>${finite(row.closed_trades).toFixed(0)}</td>
    <td class="${finite(row.net_realized_pnl_usdt)>=0?'positive':'negative'}">${optionalMoney(row.net_realized_pnl_usdt)}</td></tr>`).join(''):
    emptyRow(3,complete?'Aún no hay cierres.':'Disponible al sincronizar el historial completo.');
  const covered=attribution.research_closed_trades;
  document.getElementById('researchCoverage').textContent=complete&&covered!=null?
    `Los cinco activos estudiados concentran ${finite(covered).toFixed(0)} de ${finite(report.closed_trades).toFixed(0)} cierres ${evidenceMode}. El informe histórico no evalúa los demás pares operados por el bot.`:
    `El informe histórico solo estudia cinco activos; esperando historial completo para medir su cobertura de las operaciones ${evidenceMode}.`;
  if (report?.omitted_assets) note.textContent+=` ${report.omitted_assets} activos agrupados en «Otros»; su resultado y cierres están incluidos en el total.`;
}

function renderResearch(report, state) {
  lastResearchReport=report;
  const badge=document.getElementById('researchState');
  const button=document.getElementById('researchButton');
  button.disabled=Boolean(state.running);
  document.getElementById('exportResearch').disabled=!(report.assets?.length);
  button.textContent=state.running?'Analizando…':'Ejecutar análisis';
  if (state.running) {
    badge.textContent='ANALIZANDO'; badge.className='state warning';
  } else if (state.error) {
    badge.textContent='ERROR'; badge.className='state offline';
  } else if (!report.assets?.length) {
    badge.textContent='SIN EJECUTAR'; badge.className='state neutral';
  } else {
    badge.textContent='INFORME LISTO'; badge.className='state';
  }
  const summary=report.summary;
  const portfolio=report.portfolio||{};
  const adaptivePortfolio=report.adaptive_portfolio||{};
  document.getElementById('researchSummary').innerHTML=summary?`
    <article><span>Activos</span><strong>${Number(summary.assets)}</strong></article>
    <article><span>Estrategias evaluadas</span><strong>${Number(summary.assets)*Number(summary.strategies_per_asset)}</strong></article>
    <article><span>Folds fuera de muestra</span><strong>${Number(summary.total_walk_forward_folds)}</strong></article>
    <article><span>Candidatos a forward test</span><strong>${Number(summary.forward_test_ready||summary.promotion_candidates||0)}</strong></article>
    <article><span>Portafolio fijo OOS</span><strong class="${Number(portfolio.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(portfolio.oos_compounded_return_pct)}</strong></article>
    <article><span>Selector + cash gate</span><strong class="${Number(adaptivePortfolio.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(adaptivePortfolio.oos_compounded_return_pct)}</strong></article>
    <article><span>Efectivo USDT</span><strong>0.00%</strong></article>
    <article><span>Benchmark combinado</span><strong>${pct(portfolio.oos_benchmark_return_pct)}</strong></article>`:'';
  const assets=report.assets || [];
  document.getElementById('researchAssets').innerHTML=assets.length?assets.map(asset=>{
    const fixed=asset.fixed_strategy||asset.walk_forward||{};
    const adaptive=asset.adaptive_selector||asset.walk_forward||{};
    const gates=Object.values(asset.qualification?.gates||{});
    const passed=gates.filter(Boolean).length;
    const promotion=asset.promotion||{};
    const stage=promotion.stage||'RESEARCH';
    const candidate=stage==='CANDIDATE';
    const label=({RESEARCH:'INVESTIGANDO',CANDIDATE:'CANDIDATO',FORWARD_TEST:'FORWARD TEST',TESTNET:'LISTO TESTNET',APPROVED:'APROBADO',RETIRED:'RETIRADO'})[stage]||stage;
    return `<tr class="research-row" data-symbol="${esc(asset.symbol)}"><td><strong>${esc(asset.symbol.replace('USDT',''))}</strong><small>/USDT · ver detalle</small></td><td>${esc(asset.champion_candidate)}<small>${esc(asset.champion_family)}</small></td><td class="${Number(fixed.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(fixed.oos_compounded_return_pct)}</td><td class="${Number(adaptive.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(adaptive.oos_compounded_return_pct)}<small>${Number(adaptive.cash_folds||0)} folds en cash</small></td><td>0.00%</td><td>${pct(fixed.oos_benchmark_return_pct)}</td><td>${Number(fixed.positive_folds_pct||0).toFixed(0)}%</td><td>${gates.length?`${passed}/${gates.length}`:'—'}</td><td><span class="verdict ${candidate?'promising':'insufficient'}">${esc(label)}</span></td></tr>`;
  }).join(''):emptyRow(9,state.running?'El análisis está trabajando en segundo plano…':'Ejecuta el primer análisis desde este portal.');
  const detail=state.error?`Último error: ${state.error}`:(report.generated_at?`Informe generado ${shortTime(report.generated_at)} · Los candidatos siguen bloqueados para operación automática.`:'El estudio descarga aproximadamente 5,000 velas cerradas por activo y puede tardar varios minutos.');
  document.getElementById('researchUpdated').textContent=detail;
}

function renderResearchDetail(asset) {
  const panel=document.getElementById('researchDetail');
  const full=asset.candidate_full_sample||{};
  const fixed=asset.fixed_strategy||asset.walk_forward||{};
  const adaptive=asset.adaptive_selector||{};
  const mc=fixed.monte_carlo||asset.monte_carlo||{};
  const regimes=asset.regime_analysis||[];
  const sensitivity=asset.parameter_sensitivity||[];
  const holdout=asset.holdout;
  const candidates=asset.candidates||[];
  const gateLabels={positive_vs_cash:'Supera efectivo',beats_asset_hold_oos:'Supera mantener el activo OOS',mean_fold_sharpe:'Sharpe OOS',positive_folds:'Consistencia',selection_stability:'Estabilidad de selección',monte_carlo_loss:'Monte Carlo',full_sample_sharpe:'Sharpe de desarrollo',parameter_stability:'Sensibilidad',turnover_control:'Rotación',data_quality:'Calidad de datos',holdout_positive:'Ventana final positiva',holdout_beats_asset_hold:'Ventana final supera mantener el activo',holdout_cost_stress:'Costos duplicados',minimum_oos_evidence:'Actividad OOS mínima'};
  const gates=Object.entries(asset.qualification?.gates||{});
  const promotion=asset.promotion||{};
  const stages=['RESEARCH','CANDIDATE','FORWARD_TEST','TESTNET','APPROVED'];
  const currentStage=promotion.stage||'RESEARCH';
  const currentIndex=Math.max(0,stages.indexOf(currentStage));
  const stageLabels={RESEARCH:'Investigación',CANDIDATE:'Candidato',FORWARD_TEST:'Forward test',TESTNET:'Listo para Testnet',APPROVED:'Aprobado'};
  panel.hidden=false;
  panel.innerHTML=`<div class="detail-heading"><div><p class="eyebrow">${esc(asset.symbol)} · DIAGNÓSTICO</p><h3>${esc(asset.champion_candidate)}</h3></div><button class="detail-close" aria-label="Cerrar detalle">×</button></div>
    <div class="detail-metrics">
      <article><span>OOS estrategia fija</span><strong>${pct(fixed.oos_compounded_return_pct)}</strong></article>
      <article><span>Ventana final reservada</span><strong>${holdout?pct(holdout.base_costs.return_pct):'Sin evaluar'}</strong></article>
      <article><span>Ventana final · costos ×2</span><strong>${holdout?pct(holdout.double_costs.return_pct):'Sin evaluar'}</strong></article>
      <article><span>OOS selector + cash</span><strong>${pct(adaptive.oos_compounded_return_pct)}</strong></article>
      <article><span>Folds mantenidos en cash</span><strong>${Number(adaptive.cash_folds||0)}</strong></article>
      <article><span>Sharpe de desarrollo</span><strong>${Number(full.sharpe_ratio||0).toFixed(2)}</strong></article>
      <article><span>Drawdown máximo</span><strong>${Number(full.max_drawdown_pct||0).toFixed(2)}%</strong></article>
      <article><span>Operaciones / año</span><strong>${Number(asset.trades_per_year||0).toFixed(1)}</strong></article>
      <article><span>Monte Carlo P05</span><strong>${pct(mc.p05_return_pct)}</strong></article>
      <article><span>Drawdown P95</span><strong>${Number(mc.p95_drawdown_pct||0).toFixed(2)}%</strong></article>
    </div>
    <div class="qualification"><h4>Pipeline de promoción</h4><div>${stages.map((stage,index)=>`<span class="gate ${index<currentIndex?'gate-pass':index===currentIndex?'gate-pass':'gate'}">${index<currentIndex?'✓':index===currentIndex?'●':'○'} ${esc(stageLabels[stage])}</span>`).join('')}</div>
      <p class="research-updated"><strong>Siguiente acción:</strong> ${esc(promotion.recommended_action||'Mantener en investigación')} · ${esc(promotion.reason||'Sin decisión de promoción')}. Toda promoción requiere aprobación del propietario; LIVE nunca se activa desde el laboratorio.</p>
      ${promotion.forward_test?.required?`<p class="research-updated">Forward test mínimo previsto: ${Number(promotion.forward_test.minimum_observed_days||30)} días y ${Number(promotion.forward_test.minimum_closed_trades||30)} cierres, con retorno neto positivo y ventaja frente al benchmark.</p>`:''}
    </div>
    <div class="qualification"><h4>Puertas de investigación</h4><div>${gates.map(([name,ok])=>`<span class="gate ${ok?'gate-pass':'gate-fail'}">${ok?'✓':'×'} ${esc(gateLabels[name]||name)}</span>`).join('')||'<span class="gate">Informe anterior: vuelve a ejecutar el análisis.</span>'}</div></div>
    <h4>Comparación entre estrategias · solo desarrollo OOS</h4>
    <div class="table-wrap"><table class="research-table"><thead><tr><th>Estrategia</th><th>Retorno OOS</th><th>Cierres OOS</th><th>Ventanas +</th><th>Selección</th></tr></thead>
    <tbody>${candidates.map(candidate=>`<tr><td>${esc(candidate.strategy)}</td><td>${candidate.development_oos_return_pct==null?'—':pct(candidate.development_oos_return_pct)}</td><td>${candidate.development_oos_trades==null?'—':Number(candidate.development_oos_trades)}</td><td>${candidate.development_positive_folds_pct==null?'—':pct(candidate.development_positive_folds_pct)}</td><td>${candidate.strategy===asset.champion_candidate?'Fijada en entrenamiento inicial':'Comparación retrospectiva'}</td></tr>`).join('')}</tbody></table></div>
    <p class="research-updated">Este ranking se calculó después de observar las ventanas de desarrollo: no selecciona ni cambia estrategias en el bot. La ventana final reservada se informa arriba.</p>
    <div class="detail-columns"><div><h4>Por régimen · estrategia fija</h4>${regimes.map(row=>`<p><span>${esc(row.regime)} · ${Number(row.folds||0)} folds</span><strong>${pct(row.average_return_pct)}</strong></p>`).join('')}</div>
    <div><h4>Sensibilidad del score · muestra completa</h4>${sensitivity.map(row=>`<p><span>Umbral ${Number(row.minimum_score)}</span><strong>${pct(row.return_pct)} · DD ${Number(row.max_drawdown_pct||0).toFixed(1)}%</strong></p>`).join('')}</div></div>`;
  panel.scrollIntoView({behavior:'smooth',block:'nearest'});
}

function exportResearchCsv() {
  if (!lastResearchReport?.assets?.length) return;
  const lines=[['Activo','Estrategia fija','OOS fijo %','Selector adaptativo %','Folds en cash','Cash %','Benchmark %','Folds positivos %','Puertas aprobadas','Puertas totales','Dictamen']];
  lastResearchReport.assets.forEach(asset=>{
    const fixed=asset.fixed_strategy||asset.walk_forward||{}, adaptive=asset.adaptive_selector||{};
    const gates=Object.values(asset.qualification?.gates||{});
    lines.push([asset.symbol,asset.champion_candidate,fixed.oos_compounded_return_pct,
      adaptive.oos_compounded_return_pct,adaptive.cash_folds,0,fixed.oos_benchmark_return_pct,
      fixed.positive_folds_pct,gates.filter(Boolean).length,gates.length,asset.status]);
  });
  const csv=lines.map(row=>row.map(value=>{let cell=String(value);if(/^[=+\-@\t\r]/.test(cell))cell="'"+cell;return `"${cell.replaceAll('"','""')}"`;}).join(',')).join('\r\n');
  const link=document.createElement('a'); link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  link.download=`crypto-ai-research-${new Date().toISOString().slice(0,10)}.csv`; link.click(); URL.revokeObjectURL(link.href);
}

async function refresh() {
  try {
    const [status,positions,trades,reviews,equity,events,research,researchState,paperReport] = await Promise.all([
      api('/api/status'),api('/api/positions'),api('/api/trades'),api('/api/ai-reviews'),api('/api/equity'),api('/api/events'),api('/api/research'),api('/api/research/status'),api('/api/paper-scorecard')
    ]);
    currentExecutionMode=String(status.mode||'paper').toLowerCase();
    const modeUpper=currentExecutionMode.toUpperCase();
    document.getElementById('mode').textContent=modeUpper;
    document.getElementById('executionModeChoice').value=currentExecutionMode==='testnet'?'testnet':'paper';
    document.getElementById('testTestnetExecution').disabled=currentExecutionMode!=='testnet'||!paperControlsAvailable();
    document.getElementById('accountEnvironmentTitle').textContent='Cuenta de prueba · '+modeUpper;
    document.getElementById('riskPanelTitle').textContent='Límites '+modeUpper;
    document.getElementById('financialEvidenceTitle').textContent='Seguimiento financiero '+modeUpper;
    document.getElementById('equity').textContent=money(status.equity);
    document.getElementById('cash').textContent=money(status.cash);
    document.getElementById('exposure').textContent=money(status.exposure);
    document.getElementById('return').textContent=`${status.return_pct>=0?'+':''}${status.return_pct.toFixed(2)}% total`;
    document.getElementById('positionsCount').textContent=`${status.positions} de ${status.max_positions} posiciones`;
    document.getElementById('aiStatus').textContent=status.ai_enabled?'Activa':'Desactivada';
    document.getElementById('aiModel').textContent=status.ai_model;
    const chosen=document.getElementById('aiModelChoice');
    if(['gpt-5.6-luna','gpt-6-luna'].includes(status.ai_model))chosen.value=status.ai_model;
    const risk=status.risk||{};
    const riskName=status.paper_risk_profile||'normal';
    const profileSelect=document.getElementById('riskProfile');
    if(['minimo','leve','prudente','moderado','alto','normal'].includes(riskName))profileSelect.value=riskName;
    document.getElementById('saveRiskProfile').disabled=!paperControlsAvailable();
    const riskLevels={minimo:['Mínimo',.25],leve:['Leve',.35],prudente:['Prudente',.5],moderado:['Moderado',.65],alto:['Alto',.85],normal:['Muy alto',1]};
    const riskSelected=riskLevels[riskName];
    const riskBudget=Number(risk.risk_per_trade_pct);
    const riskDescription=riskSelected?`${riskSelected[0]} · ${Number.isFinite(riskBudget)?(100*riskBudget*riskSelected[1]).toFixed(3)+'% del capital en pérdida estimada por operación':'presupuesto reducido'}`:'Perfil inválido: nuevas entradas bloqueadas';
    document.getElementById('riskProfileNote').textContent=paperControlsAvailable()?
      `Actual: ${riskDescription}. El cambio afecta nuevas entradas ${modeUpper}; los topes de posición y exposición no aumentan.`:
      'Esperando conexión y controles del motor en Windows.';
    const effectiveRisk={...risk,risk_per_trade_pct:Number(risk.risk_per_trade_pct)*({minimo:.25,prudente:.5,normal:1}[riskName]??0)};
    for(const [id,key] of [['riskTrade','risk_per_trade_pct'],['riskPosition','max_position_pct'],['riskExposure','max_total_exposure_pct'],['riskDaily','daily_loss_limit_pct'],['riskWeekly','weekly_loss_limit_pct']]){
      const value=Number(effectiveRisk[key]);
      document.getElementById(id).textContent=effectiveRisk[key]!=null&&Number.isFinite(value)?`${(value*100).toFixed(2).replace(/\.00$/,'')}%`:'—';
    }

    const state=document.getElementById('killState'), button=document.getElementById('killButton');
    state.textContent=status.killed?'DETENIDO':'Protecciones activas'; state.classList.toggle('killed',status.killed);
    button.textContent=status.killed?'Reanudar nuevas entradas':'Pausar nuevas entradas'; button.dataset.killed=String(status.killed);

    const activity=status.activity || {state:'starting',age_seconds:null};
    document.getElementById('operationSummary').textContent=activity.state==='operational'?
      `Motor ${modeUpper} activo. ${status.positions} posiciones abiertas de ${status.max_positions}; ${status.killed?'nuevas entradas pausadas y protecciones vigentes':'nuevas entradas sujetas a límites y revisión IA'}. Último ciclo ${ageLabel(activity.age_seconds)}.`:
      `Motor ${activityLabel(activity.state).toLowerCase()}. ${status.killed?'Nuevas entradas pausadas. ':'Comprueba la conexión de Windows antes de dar instrucciones. '}Último ciclo ${ageLabel(activity.age_seconds)}.`;
    const botState=document.getElementById('botState');
    botState.textContent=activityLabel(activity.state);
    botState.classList.toggle('warning',activity.state==='delayed');
    botState.classList.toggle('offline',activity.state==='offline');

    lastPositions=positions;
    document.getElementById('positions').innerHTML=positions.length?positions.map(p=>`<tr><td><strong>${esc(p.symbol)}</strong></td><td>${num(p.quantity)}</td><td>${num(p.entry_price,4)}</td><td>${p.market_price==null?'—':num(p.market_price,4)}</td><td class="${p.unrealized_pnl==null?'':p.unrealized_pnl>=0?'positive':'negative'}">${p.unrealized_pnl==null?'—':`${p.unrealized_pnl>=0?'+':''}${num(p.unrealized_pnl,2)}`}</td><td class="${p.unrealized_pct==null?'':p.unrealized_pct>=0?'positive':'negative'}">${p.unrealized_pct==null?'—':`${p.unrealized_pct>=0?'+':''}${num(p.unrealized_pct,2)}%`}</td><td>${num(p.stop_price,4)}</td><td>${num(p.take_profit,4)}</td><td>${num(p.high_water,4)}</td><td><button class="secondary paper-close" data-symbol="${esc(p.symbol)}" ${p.market_price==null||!paperControlsAvailable()?'disabled':''}>Cerrar ${currentExecutionMode==='testnet'?'TESTNET':'PAPER'}</button></td></tr>`).join(''):emptyRow(10,'Sin posiciones abiertas');
    document.getElementById('trades').innerHTML=trades.length?trades.slice(0,8).map(t=>`<div class="feed-item"><strong class="${esc(t.side.toLowerCase())}">${esc(t.side)}</strong><div><strong>${esc(t.symbol)} · ${num(t.quantity)}</strong><p>${esc(t.reason)}</p></div><time>${shortTime(t.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay operaciones');
    document.getElementById('reviews').innerHTML=reviews.length?reviews.slice(0,8).map(r=>`<div class="feed-item"><strong class="${esc(r.verdict.toLowerCase())}">${esc(r.verdict)}</strong><div><strong>${esc(r.symbol)} · ${(r.confidence*100).toFixed(0)}%</strong><p>${esc(r.reason)}</p></div><time>${shortTime(r.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay revisiones');
    const important=events.filter(e=>['WARN','ERROR','CRITICAL'].includes(e.level)).slice(0,10);
    document.getElementById('events').innerHTML=important.length?important.map(e=>`<div class="feed-item"><strong class="event-${esc(e.level.toLowerCase())}">${esc(e.level)}</strong><div><p>${esc(e.message)}</p></div><time>${shortTime(e.created_at)}</time></div>`).join(''):feedEmpty('Sin errores ni advertencias recientes');
    renderChart(equity);
    renderResearch(research,researchState);
    renderPaperEvidence(paperReport,equity,trades);
    document.getElementById('updated').textContent=`Último ciclo ${ageLabel(activity.age_seconds)} · ${shortTime(activity.last_cycle_at)}`;
  } catch(error) {
    const botState=document.getElementById('botState');
    botState.textContent='PORTAL SIN CONEXIÓN'; botState.classList.add('offline');
    document.getElementById('operationSummary').textContent='No se pudo consultar el motor. Comprueba la conexión con Windows antes de operar.';
    document.getElementById('updated').textContent='No fue posible consultar el motor';
  }
}

document.getElementById('killButton').addEventListener('click', async event => {
  const killed=event.currentTarget.dataset.killed==='true';
  const message=killed?`¿Solicitar reanudar nuevas entradas ${currentExecutionMode.toUpperCase()}? Las pausas locales requieren liberación local.`:'¿Solicitar pausa de nuevas entradas? El motor la aplicará al comprobar el interruptor; no cierra posiciones.';
  if (!confirm(message)) return;
  await api(killed?'/api/resume':'/api/kill',{method:'POST'}); await refresh();
});
document.getElementById('saveRiskProfile').addEventListener('click', async event=>{
  if(!paperControlsAvailable())return;
  const profile=document.getElementById('riskProfile').value;
  if(!confirm(`¿Aplicar ${profile} a las próximas entradas ${currentExecutionMode.toUpperCase()}? El límite base no aumenta.`))return;
  event.currentTarget.disabled=true;
  try{
    const result=await api('/api/paper/risk-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile})});
    if(result.status==='pending')alert('Solicitud enviada a Windows. El perfil cambiará cuando aparezca como completada en Actividad.');
    await refresh();
  }catch(error){alert(`No se cambió el perfil: ${error.message}`);event.currentTarget.disabled=false;}
});
document.getElementById('positions').addEventListener('click',async event=>{
  const button=event.target.closest('.paper-close');
  if(!button||!paperControlsAvailable())return;
  const position=lastPositions.find(row=>row.symbol===button.dataset.symbol);
  if(!position||!Number.isFinite(Number(position.market_price))||Number(position.market_price)<=0)return;
  if(!confirm(`¿Cerrar ${position.symbol} en ${currentExecutionMode.toUpperCase()}? Se consultará un precio nuevo y el cierre pasará por el broker del entorno activo.${currentExecutionMode==='paper'?' Nuevas entradas en este par se bloquearán 24 horas.':''}`))return;
  button.disabled=true;
  try{
    const result=await api('/api/paper/close-position',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:position.symbol,opened_at:position.opened_at,reference_price:position.market_price})});
    if(result.status==='pending')alert('Solicitud enviada a Windows. Comprueba que el cierre figure como completado antes de repetir.');
    await refresh();
  }catch(error){alert(`No se confirmó el cierre: ${error.message}`);button.disabled=false;}
});
document.getElementById('researchButton').addEventListener('click', async event => {
  if (!confirm('¿Ejecutar el análisis histórico de cinco activos? No modifica las operaciones del bot.')) return;
  event.currentTarget.disabled=true;
  try { await api('/api/research/run',{method:'POST'}); await refresh(); }
  catch(error) { alert(`No fue posible iniciar el análisis: ${error.message}`); event.currentTarget.disabled=false; }
});
document.getElementById('exportResearch').addEventListener('click',exportResearchCsv);
document.getElementById('researchAssets').addEventListener('click',event=>{
  const row=event.target.closest('.research-row'); if (!row || !lastResearchReport) return;
  const asset=lastResearchReport.assets.find(item=>item.symbol===row.dataset.symbol); if (asset) renderResearchDetail(asset);
});
document.getElementById('researchDetail').addEventListener('click',event=>{
  if (event.target.closest('.detail-close')) document.getElementById('researchDetail').hidden=true;
});
window.addEventListener('resize',()=>api('/api/equity').then(renderChart).catch(()=>{}));
window.addEventListener('portal-ready',refresh);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
window.addEventListener('DOMContentLoaded',refresh);
setInterval(()=>{if(!document.hidden&&!document.querySelector('.shell').hidden)refresh();},30000);
