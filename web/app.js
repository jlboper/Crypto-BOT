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
    <article><span>Prometedores</span><strong>${Number(summary.promising_assets)}</strong></article>
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
    const promising=asset.status==='PROMISING_RESEARCH_ONLY';
    return `<tr class="research-row" data-symbol="${esc(asset.symbol)}"><td><strong>${esc(asset.symbol.replace('USDT',''))}</strong><small>/USDT · ver detalle</small></td><td>${esc(asset.champion_candidate)}<small>${esc(asset.champion_family)}</small></td><td class="${Number(fixed.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(fixed.oos_compounded_return_pct)}</td><td class="${Number(adaptive.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(adaptive.oos_compounded_return_pct)}<small>${Number(adaptive.cash_folds||0)} folds en cash</small></td><td>0.00%</td><td>${pct(fixed.oos_benchmark_return_pct)}</td><td>${Number(fixed.positive_folds_pct||0).toFixed(0)}%</td><td>${gates.length?`${passed}/${gates.length}`:'—'}</td><td><span class="verdict ${promising?'promising':'insufficient'}">${promising?'PROMETEDOR':'EVIDENCIA INSUFICIENTE'}</span></td></tr>`;
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
  const gateLabels={positive_vs_cash:'Supera efectivo',mean_fold_sharpe:'Sharpe OOS',positive_folds:'Consistencia',selection_stability:'Estabilidad de selección',monte_carlo_loss:'Monte Carlo',full_sample_sharpe:'Sharpe de desarrollo',parameter_stability:'Sensibilidad',turnover_control:'Rotación',data_quality:'Calidad de datos',holdout_positive:'Ventana final positiva',holdout_cost_stress:'Costos duplicados',minimum_oos_evidence:'Actividad OOS mínima'};
  const gates=Object.entries(asset.qualification?.gates||{});
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
    <div class="qualification"><h4>Puertas de promoción</h4><div>${gates.map(([name,ok])=>`<span class="gate ${ok?'gate-pass':'gate-fail'}">${ok?'✓':'×'} ${esc(gateLabels[name]||name)}</span>`).join('')||'<span class="gate">Informe anterior: vuelve a ejecutar el análisis.</span>'}</div></div>
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
    const [status,positions,trades,reviews,equity,events,research,researchState] = await Promise.all([
      api('/api/status'),api('/api/positions'),api('/api/trades'),api('/api/ai-reviews'),api('/api/equity'),api('/api/events'),api('/api/research'),api('/api/research/status')
    ]);
    document.getElementById('equity').textContent=money(status.equity);
    document.getElementById('cash').textContent=money(status.cash);
    document.getElementById('exposure').textContent=money(status.exposure);
    document.getElementById('return').textContent=`${status.return_pct>=0?'+':''}${status.return_pct.toFixed(2)}% total`;
    document.getElementById('positionsCount').textContent=`${status.positions} de ${status.max_positions} posiciones`;
    document.getElementById('aiStatus').textContent=status.ai_enabled?'Activa':'Desactivada';
    document.getElementById('aiModel').textContent=status.ai_model;

    const state=document.getElementById('killState'), button=document.getElementById('killButton');
    state.textContent=status.killed?'DETENIDO':'Protecciones activas'; state.classList.toggle('killed',status.killed);
    button.textContent=status.killed?'Reanudar bot':'Activar kill switch'; button.dataset.killed=String(status.killed);

    const activity=status.activity || {state:'starting',age_seconds:null};
    const botState=document.getElementById('botState');
    botState.textContent=activityLabel(activity.state);
    botState.classList.toggle('warning',activity.state==='delayed');
    botState.classList.toggle('offline',activity.state==='offline');

    document.getElementById('positions').innerHTML=positions.length?positions.map(p=>`<tr><td><strong>${esc(p.symbol)}</strong></td><td>${num(p.quantity)}</td><td>${num(p.entry_price,4)}</td><td>${num(p.market_price,4)}</td><td class="${p.unrealized_pnl>=0?'positive':'negative'}">${p.unrealized_pnl>=0?'+':''}${num(p.unrealized_pnl,2)}</td><td class="${p.unrealized_pct>=0?'positive':'negative'}">${p.unrealized_pct>=0?'+':''}${num(p.unrealized_pct,2)}%</td><td>${num(p.stop_price,4)}</td><td>${num(p.take_profit,4)}</td><td>${num(p.high_water,4)}</td></tr>`).join(''):emptyRow(9,'Sin posiciones abiertas');
    document.getElementById('trades').innerHTML=trades.length?trades.slice(0,8).map(t=>`<div class="feed-item"><strong class="${esc(t.side.toLowerCase())}">${esc(t.side)}</strong><div><strong>${esc(t.symbol)} · ${num(t.quantity)}</strong><p>${esc(t.reason)}</p></div><time>${shortTime(t.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay operaciones');
    document.getElementById('reviews').innerHTML=reviews.length?reviews.slice(0,8).map(r=>`<div class="feed-item"><strong class="${esc(r.verdict.toLowerCase())}">${esc(r.verdict)}</strong><div><strong>${esc(r.symbol)} · ${(r.confidence*100).toFixed(0)}%</strong><p>${esc(r.reason)}</p></div><time>${shortTime(r.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay revisiones');
    const important=events.filter(e=>['WARN','ERROR','CRITICAL'].includes(e.level)).slice(0,10);
    document.getElementById('events').innerHTML=important.length?important.map(e=>`<div class="feed-item"><strong class="event-${esc(e.level.toLowerCase())}">${esc(e.level)}</strong><div><p>${esc(e.message)}</p></div><time>${shortTime(e.created_at)}</time></div>`).join(''):feedEmpty('Sin errores ni advertencias recientes');
    renderChart(equity);
    renderResearch(research,researchState);
    document.getElementById('updated').textContent=`Último ciclo ${ageLabel(activity.age_seconds)} · ${shortTime(activity.last_cycle_at)}`;
  } catch(error) {
    const botState=document.getElementById('botState');
    botState.textContent='PORTAL SIN CONEXIÓN'; botState.classList.add('offline');
    document.getElementById('updated').textContent='No fue posible consultar el motor';
  }
}

document.getElementById('killButton').addEventListener('click', async event => {
  const killed=event.currentTarget.dataset.killed==='true';
  const message=killed?'¿Solicitar reanudar nuevas entradas PAPER? Las pausas locales requieren liberación local.':'¿Solicitar pausa de nuevas entradas? El motor la aplicará al comprobar el interruptor; no cierra posiciones.';
  if (!confirm(message)) return;
  await api(killed?'/api/resume':'/api/kill',{method:'POST'}); await refresh();
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
