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
let lastPortalChartData = null;
const paperControlsAvailable = () => typeof window.paperControlsAvailable === 'function' ? window.paperControlsAvailable() : true;
const motionReduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
function retriggerMotion(node, className) {
  if (!node || motionReduced() || document.hidden) return;
  node.classList.remove(className);
  void node.offsetWidth;
  node.classList.add(className);
  node.addEventListener('animationend',()=>node.classList.remove(className),{once:true});
}
function installPortalMotion() {
  const shell=document.querySelector('.shell');
  if(shell&&!motionReduced())requestAnimationFrame(()=>shell.classList.add('motion-ready'));
  const watched=[
    '.engine-kpis strong','.engine-kpis em','.metrics strong',
    '.research-summary strong','.health-grid dd','.dual-scorecards dd',
    '.state','.badge','.bot-version'
  ];
  const nodes=[...document.querySelectorAll(watched.join(','))];
  const observer=new MutationObserver(records=>{
    const touched=new Set(records.map(record=>record.target.nodeType===3?record.target.parentElement:record.target).filter(Boolean));
    for(const node of touched){
      retriggerMotion(node,node.matches('.state,.badge')?'motion-state':'motion-value');
      if(node.matches('.state')){
        const label=(node.textContent||'').toUpperCase();
        node.classList.toggle('motion-operational',/OPERATIVO|ACTIVO · ESPERANDO SEÑAL|PROTECCIONES ACTIVAS/.test(label));
      }
    }
  });
  for(const node of nodes)observer.observe(node,{subtree:true,characterData:true,childList:true});
}

async function api(path, options={}) {
  if(window.portalApi)return window.portalApi(path,{...options,headers:{...headers,...(options.headers||{})}});
  const response = await fetch(path, {...options, headers:{...headers,...(options.headers||{})}});
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function renderChart(rows, canvasId='equityChart') {
  const canvas = document.getElementById(canvasId);
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
  retriggerMotion(canvas,'motion-chart');
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
const optionalNumber = value => value!=null&&Number.isFinite(Number(value))?Number(value):null;
const profitFactorLabel = value => value==null?'—':Number(value)===999?'Sin pérdidas registradas':Number(value).toFixed(2);
function futuresEquityValue(row) {
  const wallet=optionalNumber(row.wallet_balance), pnl=optionalNumber(row.unrealized_pnl);
  return wallet!=null&&pnl!=null?wallet+pnl:optionalNumber(row.equity ?? row.value);
}

function futuresCycleFresh(futures, status={}) {
  const age=(Date.now()-Date.parse(futures?.cycle_diagnostic?.at))/1000;
  const seconds=Number(status.cycle_seconds)||900;
  return Number.isFinite(age)&&age>=-120&&age<=Math.max(seconds*1.5,seconds+120);
}
function futuresSignalEvidence(futures, symbol) {
  const signal=futures?.latest_signals?.[symbol]||{};
  const age=(Date.now()-Date.parse(signal.at))/1000;
  const timeframe=String(signal.timeframe||futures?.guardrails?.forward_timeframe||'');
  const match=/^(\d+)([mh])$/.exec(timeframe);
  const seconds=match?Number(match[1])*(match[2]==='h'?3600:60):0;
  const fresh=seconds>0&&Number.isFinite(age)&&age>=-120&&age<=seconds+1800;
  const issue=futuresCycleFresh(futures)?futures?.cycle_diagnostic?.issues?.find(row=>row.symbol===symbol):null;
  return {signal,fresh,issue,score:fresh?String(signal.long_score??'—')+' / '+String(signal.short_score??'—'):'— / —',
    stamp:(signal.at?shortTime(signal.at):'Sin fecha')+' · '+(timeframe?timeframe.toUpperCase()+' · ':'')+(fresh?'último análisis':'dato histórico')};
}

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
    ['Cierres de estrategia / técnicos',complete&&report.financial?`${report.financial.strategy_closed_trades} / ${report.financial.technical_closed_trades}`:'—'],
    ['P&amp;L neto de estrategia',complete?optionalMoney(report.financial?.strategy_net_pnl_usdt):'—'],
    ['Expectativa neta de estrategia / cierre',complete?optionalMoney(report.financial?.strategy_net_expectancy_usdt):'—'],
    ['Días observados',finite(values.days).toFixed(1)],
    ['Operaciones cerradas',finite(values.trades).toFixed(0)],
    ['P&amp;L realizado neto',`${finite(values.pnl).toFixed(2)} USDT`],
    ['Drawdown de equity muestreada',`${finite(values.drawdown).toFixed(2)}%`],
    ['Comisiones registradas',`${finite(values.fees).toFixed(2)} USDT`],
    ['Operaciones ganadoras',values.win===null?'—':`${finite(values.win).toFixed(1)}%`],
    ['Expectativa neta / cierre',complete?optionalMoney(report.expectancy_usdt_per_close):'—'],
    ['Ganancia media',complete?optionalMoney(report.average_win_usdt):'—'],
    ['Pérdida media',complete?optionalMoney(report.average_loss_usdt):'—'],
    ['Comisiones / |P&amp;L neto|',complete&&report.fees_to_abs_net_pnl_pct!=null?`${finite(report.fees_to_abs_net_pnl_pct).toFixed(1)}%`:'—'],
    ['Muestras de equity',finite(values.points).toFixed(0)],
    ['P&amp;L abierto estimado',complete?optionalMoney(report.estimated_open_pnl_usdt):'—'],
    ['Exposición abierta con precio reciente',complete?optionalMoney(report.open_exposure_usdt):'—'],
    ['Factor de beneficio realizado',complete?profitFactorLabel(report.profit_factor):'—'],
    ['MAE / MFE por operación',report?.mae_mfe_available===true?'DISPONIBLE':'PENDIENTE DE TELEMETRÍA']
  ];
  const cards=items=>items.map(([label,value])=>`<article><span>${label}</span><strong>${value}</strong></article>`).join('');
  panel.innerHTML=cards(metrics.slice(0,4));
  document.getElementById('paperMoreMetrics').innerHTML=cards(metrics.slice(4));
  const benchmark=report?.benchmark,comparison=document.getElementById('paperBenchmark');
  comparison.textContent=benchmark?.paper_return_pct!=null&&benchmark?.btc_net_return_pct!=null?
    `Mismo período desde ${shortTime(benchmark.started_at)} (${benchmark.observed_days} días, ${benchmark.matched_points} muestras): equity ${evidenceMode} ${pct(benchmark.paper_return_pct)} · BTC con costos de referencia ${pct(benchmark.btc_net_return_pct)} · diferencia ${Number(benchmark.net_difference_pp)>=0?'+':''}${Number(benchmark.net_difference_pp).toFixed(2)} puntos porcentuales. BTC usa el 100% del capital; no hay libro de aportes/retiros ni evidencia suficiente para operar con dinero real.`:
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
    `Historial de preflight: ${finite(preflight.checked).toFixed(0)} candidatas ${evidenceMode}; ${finite(preflight.estimated_compatible).toFixed(0)} compatibles con los filtros comprobados, ${finite(preflight.incompatible).toFixed(0)} incompatibles o bloqueadas y ${finite(preflight.unknown).toFixed(0)} sin reglas suficientes. Incluye versiones anteriores y no cuenta órdenes ejecutadas. ${latest.length?`Diagnósticos registrados: ${latest.map(row=>`${row.symbol} (${Array.isArray(row.reasons)?row.reasons.join(', '):'sin detalle'})`).join(' · ')}. `:''}Cada nueva entrada TESTNET vuelve a comprobar cantidad y mínimos del propio entorno; la ejecución exige además confirmación y conciliación.`:
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
    `Los ${Number(attribution.research_symbols?.length||5)} activos Spot estudiados concentran ${finite(covered).toFixed(0)} de ${finite(report.closed_trades).toFixed(0)} cierres ${evidenceMode}. La cobertura corresponde al último informe completo.`:
    `Esperando historial completo para medir su cobertura de las operaciones ${evidenceMode}.`;
  if (report?.omitted_assets) note.textContent+=` ${report.omitted_assets} activos agrupados en «Otros»; su resultado y cierres están incluidos en el total.`;
}

function renderFuturesChart(points) {
  const canvas=document.getElementById('futuresEquityChart');
  if(!canvas)return;
  const ctx=canvas.getContext('2d'), dpr=window.devicePixelRatio||1;
  const width=canvas.clientWidth||520, height=190;
  canvas.width=width*dpr; canvas.height=height*dpr; ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,width,height);
  const rows=(points||[]).map(futuresEquityValue).filter(value=>value!=null);
  if(rows.length<2){ctx.fillStyle='#7890ad';ctx.font='12px Segoe UI';ctx.fillText('Esperando muestras de Futures',14,28);return;}
  const min=Math.min(...rows), max=Math.max(...rows), span=Math.max(max-min,1);
  ctx.strokeStyle='#263b55';ctx.lineWidth=1;
  for(let i=1;i<4;i++){const y=(height-24)*i/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
  ctx.strokeStyle='#4de3b0';ctx.lineWidth=2;ctx.beginPath();
  rows.forEach((value,i)=>{const x=8+(width-16)*(i/(rows.length-1));const y=8+(height-28)*(1-(value-min)/span);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
  ctx.stroke();
  retriggerMotion(canvas,'motion-chart');
}

function renderDualEvidence(spot, futures, status={}) {
  const score=futures?.scorecard||{};
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  set('spotObservedDays', Number(spot?.observed_days||0).toFixed(1));
  set('spotClosedTrades', String(Number(spot?.closed_trades||0)));
  set('spotObservedPnl', money(spot?.net_realized_pnl_usdt||0));
  set('spotObservedReturn',status.return_pct==null?'—':pct(status.return_pct));
  set('spotObservedQuality',(spot?.win_rate_pct==null?'—':Number(spot.win_rate_pct).toFixed(1)+'%')+' / '+profitFactorLabel(spot?.profit_factor));
  set('spotObservedExpectancy',spot?.expectancy_usdt_per_close==null?'—':money(spot.expectancy_usdt_per_close));
  set('spotObservedOpenPnl',spot?.estimated_open_pnl_usdt==null?'—':money(spot.estimated_open_pnl_usdt));
  set('spotObservedDrawdown', finite(spot?.sampled_max_drawdown_pct).toFixed(2)+'%');
  set('futuresObservedDays', finite(score.observed_days).toFixed(1));
  set('futuresObservedTrades', score.strategy_closed_trades==null?'—':String(finite(score.strategy_closed_trades).toFixed(0)));
  set('futuresTechnicalTrades', score.technical_closed_trades==null?'—':String(finite(score.technical_closed_trades).toFixed(0)));
  set('futuresObservedReturn', score.account_return_pct==null?'—':pct(score.account_return_pct));
  const finance=score.financial||{};
  set('futuresObservedPnl', finance.net_realized_pnl_usdt==null?'—':money(finance.net_realized_pnl_usdt));
  set('futuresStrategyPnl',finance.strategy_net_pnl_usdt==null?'—':money(finance.strategy_net_pnl_usdt));
  set('futuresObservedExpectancy',finance.strategy_net_expectancy_usdt==null?'—':money(finance.strategy_net_expectancy_usdt));
  const last=(futures?.equity||[]).at(-1);
  set('futuresObservedOpenPnl',last?.unrealized_pnl==null?'—':money(last.unrealized_pnl));
  set('futuresObservedDrawdown', finite(score.sampled_max_drawdown_pct).toFixed(2)+'%');
  set('futuresObservedQuality', (finance.strategy_net_win_rate_pct==null?'—':finite(finance.strategy_net_win_rate_pct).toFixed(1)+'%')+' / '+profitFactorLabel(finance.strategy_net_profit_factor));
  set('futuresDirectionSplit','L '+finite(score.long_closed_trades).toFixed(0)+' ('+money(score.long_gross_pnl_usdt||0)+') · S '+finite(score.short_closed_trades).toFixed(0)+' ('+money(score.short_gross_pnl_usdt||0)+')');
  const cycles=finite(score.cycle_total),incidents=finite(score.incident_total),attempts=finite(score.failure_attempt_total);
  set('futuresErrorRate',incidents.toFixed(0)+' incidentes · '+attempts.toFixed(0)+' intentos fallidos · '+cycles.toFixed(0)+' ciclos');
  const spotDays=finite(spot?.observed_days),spotTrades=finite(spot?.closed_trades);
  const futuresDays=finite(score.observed_days),futuresTrades=finite(score.strategy_closed_trades);
  const checks=[
    [spotDays>=30,'Spot: '+spotDays.toFixed(1)+' / 30 días'],
    [spotTrades>=30,'Spot: '+spotTrades.toFixed(0)+' / 30 cierres'],
    [futuresDays>=30,'Futures: '+futuresDays.toFixed(1)+' / 30 días'],
    [futuresTrades>=30,'Futures: '+futuresTrades.toFixed(0)+' / 30 cierres'],
    [finite(score.consecutive_errors)===0,'Futures: sin errores consecutivos activos'],
  ];
  const list=document.getElementById('dualReadinessChecks');
  if(list){list.replaceChildren();for(const [ok,label] of checks){const li=document.createElement('li');li.textContent=(ok?'✓':'○')+' '+label;list.append(li);}}
  const ready=spotDays>=30&&spotTrades>=30&&futuresDays>=30&&futuresTrades>=30&&score.consecutive_errors===0;
  const state=document.getElementById('dualEvidenceState');
  if(state){state.textContent=ready?'LISTO PARA REVISIÓN':'ACUMULANDO DATOS';state.className='state '+(ready?'warning':'neutral');}
  const note=document.getElementById('dualEvidenceNote');
  if(note)note.textContent=ready?
    'Ambos motores alcanzaron el mínimo de observación. Esto habilita una revisión humana de resultados, no Binance LIVE.':
    'Se están acumulando datos separados de Spot y Futures. Evitaremos cambiar estrategia o riesgo por ruido de pocos días; solo corregiremos fallos operativos o de seguridad.';
}
function renderFuturesParity(futures) {
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const score=futures?.scorecard||{};
  const guard=futures?.guardrails||{};
  const positions=Array.isArray(futures?.positions)?futures.positions:[];
  const pos=positions.length===1?positions[0]:positions.length===0?futures?.position||null:null;
  const last=(futures?.equity||[]).at(-1)||{};
  const card=document.getElementById('futuresPositionCard');
  if(card)card.hidden=positions.length>1;
  const accountPnl=optionalNumber(last.unrealized_pnl);
  set('futuresAccountUnrealized',accountPnl==null?'—':money(accountPnl));
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;

  const limitState=document.getElementById('futuresLimitState');
  if(limitState){
    limitState.textContent=futures?.killed?'PAUSADO':score.risk_halt?.active?'ENTRADAS BLOQUEADAS POR PÉRDIDA':(futures?.enabled?'PROTECCIONES ACTIVAS':'INACTIVO');
    limitState.className='state'+((futures?.killed||score.risk_halt?.active||!futures?.enabled)?' warning':'');
  }
  const trial=futures?.leverage_trials;
  const leverageLabel=trial?.levels?.length>1?trial.levels.map(l=>String(l)+'x').join(' / '):
    (futures?.automatic_leverage==null?'—':String(futures.automatic_leverage)+'x');
  set('futuresLimitLeverage',leverageLabel);
  set('futuresConfiguredSymbols',Array.isArray(futures?.symbols)?futures.symbols.map(s=>s.replace(/USDT$/,'')).join(' / '):'—');
  set('futuresConfiguredTimeframe',guard.forward_timeframe?String(guard.forward_timeframe).toUpperCase():'—');
  set('futuresConfiguredLeverage',leverageLabel);
  set('futuresConfiguredPositions',guard.max_positions==null?'—':String(guard.max_positions)+' posiciones máx.');
  const portfolio=futures?.portfolio_budget;
  const totalLimit=guard.forward_total_notional_usdt??portfolio?.notional_limit_usdt;
  const lossLimit=guard.forward_total_stop_loss_usdt??portfolio?.stop_loss_limit_usdt;
  set('futuresPortfolioBudget',totalLimit==null?'Esperando límites de cartera del motor.':
    'Cartera: '+(portfolio?money(portfolio.notional_usdt)+' / ':'')+money(totalLimit)+' de notional bruto · '+
    'Pérdida estimada hasta stops: '+(portfolio?money(portfolio.stop_loss_usdt)+' / ':'')+money(lossLimit)+
    ' (incluye reserva de costos). Límites para nuevas entradas; fills, gaps y costos reales pueden superar la estimación.'+
    (portfolio?' Medido '+portfolio.at+'.':''));
  const trials=document.getElementById('futuresLeverageTrials');
  if(trials){
    trials.innerHTML=trial?.levels?.length>1?'<p>Próxima entrada: '+esc(String(trial.next_leverage))+'x · Máximo '+num(trial.notional_limit_usdt,0)+' USDT de valor por operación.</p>'+
      '<div class="health-grid">'+(trial.results||[]).map(r=>'<article><strong>'+esc(String(r.leverage))+'x</strong><p>'+String(r.closed_trades)+' cierres de estrategia · '+num(r.gross_pnl_usdt,4)+' USDT brutos</p></article>').join('')+'</div>'+
      '<p class="settings-help">Prueba operativa con valor de posición constante: cambia el margen requerido. P&amp;L bruto sin comisiones ni funding; entradas distintas, sin comparación de rentabilidad equivalente.</p>':
      '<p class="settings-help">Pruebas de apalancamiento pendientes de activación en Windows.</p>';
  }
  set('futuresLimitMarginType',guard.margin_type?String(guard.margin_type).toUpperCase():'—');
  set('futuresLimitPositions',guard.max_positions==null?'—':String(guard.max_positions));
  set('futuresLimitBudget',guard.forward_margin_usdt==null?'—':money(guard.forward_margin_usdt));
  set('futuresLimitScore',guard.forward_min_score==null?'—':String(guard.forward_min_score)+'/100');
  set('futuresLimitStop',(guard.forward_minimum_stop_pct==null?'—':(100*Number(guard.forward_minimum_stop_pct)).toFixed(1)+'%')+
      (guard.forward_stop_atr_multiple==null?'':' · '+Number(guard.forward_stop_atr_multiple).toFixed(1)+'× ATR'));
  set('futuresLimitRR',guard.forward_reward_to_risk==null?'—':'1 : '+Number(guard.forward_reward_to_risk).toFixed(1));

  const positionState=document.getElementById('futuresPositionState');
  if(positionState){
    positionState.textContent=positions.length?(String(positions.length)+' ABIERTA'+(positions.length===1?'':'S')):'SIN POSICIÓN';
    positionState.className='state'+(positions.length?'':' neutral');
  }
  if(pos){
    const qty=Number(pos.quantity);
    const entry=Number(pos.entry_price);
    const direction=String(pos.direction||'—');
    set('futuresPositionContract',String(pos.symbol||futures?.symbol||'BTCUSDT')+' · '+direction);
    set('futuresPositionQty',Number.isFinite(qty)?num(qty,6):'—');
    set('futuresPositionPrices',num(entry,4)+(pos.mark_price==null?'':' / mark '+num(pos.mark_price,4)));
    set('futuresPositionUnrealized',pos.unrealized_after_accrued_costs_usdt!=null?money(pos.unrealized_after_accrued_costs_usdt)+' tras costos acumulados':pos.unrealized_pnl_usdt!=null?money(pos.unrealized_pnl_usdt)+' bruto':'Sin cotización reciente por contrato');
    const pnlNode=document.getElementById('futuresPositionUnrealized');
    if(pnlNode)pnlNode.className='';
    set('futuresPositionProtection',num(pos.stop_price,2)+' / '+num(pos.take_profit,2));
    set('futuresPositionLeverage',String(pos.leverage||futures?.automatic_leverage||1)+'x · '+String(guard.margin_type||'ISOLATED').toUpperCase());
    set('futuresPositionOpened',pos.opened_at?shortTime(pos.opened_at):'—');
  } else {
    for(const id of ['futuresPositionContract','futuresPositionQty','futuresPositionPrices','futuresPositionUnrealized','futuresPositionProtection','futuresPositionLeverage','futuresPositionOpened'])set(id,'—');
    const pnlNode=document.getElementById('futuresPositionUnrealized');if(pnlNode)pnlNode.className='';
  }

  const days=finite(score.observed_days), trades=finite(score.strategy_closed_trades);
  const ready=days>=30&&trades>=30&&finite(score.consecutive_errors)===0;
  const evidence=document.getElementById('futuresEvidenceState');
  if(evidence){evidence.textContent=ready?'LISTO PARA REVISIÓN':'EVIDENCIA INSUFICIENTE';evidence.className='state '+(ready?'warning':'neutral');}
  set('futuresEvidenceNote',
    'Historial Futures Demo: '+days.toFixed(1)+' días y '+trades.toFixed(0)+' cierres de estrategia; '+finite(score.technical_closed_trades).toFixed(0)+' cierres técnicos aparte. 30 días y 30 cierres solo permiten revisión; nunca activan dinero real automáticamente.');
  const metrics=document.getElementById('futuresEvidenceMetrics');
  if(metrics)metrics.innerHTML=
    '<article><span>Días observados</span><strong>'+days.toFixed(1)+'</strong></article>'+
    '<article><span>Cierres de estrategia</span><strong>'+trades.toFixed(0)+'</strong></article>'+
    '<article><span>P&amp;L de estrategia bruto</span><strong>'+(score.strategy_gross_pnl_usdt==null?'—':money(score.strategy_gross_pnl_usdt))+'</strong></article>'+
    '<article><span>Drawdown muestreado</span><strong>'+finite(score.sampled_max_drawdown_pct).toFixed(2)+'%</strong></article>';
  set('futuresEvidenceSummary',
    'Retorno observado '+(score.account_return_pct==null?'—':pct(score.account_return_pct))+
    ' · win rate de estrategia '+(score.strategy_win_rate_pct==null?'—':finite(score.strategy_win_rate_pct).toFixed(1)+'%')+
    ' · profit factor de estrategia '+profitFactorLabel(score.strategy_profit_factor)+
    ' · LONG '+finite(score.long_closed_trades).toFixed(0)+' / SHORT '+finite(score.short_closed_trades).toFixed(0)+', incluyendo técnicos. P&L bruto excluye comisiones y funding.');
  const more=document.getElementById('futuresMoreMetrics');
  if(more)more.innerHTML=
    '<article><span>Expectativa de estrategia / cierre</span><strong>'+(trades>0&&score.strategy_gross_pnl_usdt!=null?money(Number(score.strategy_gross_pnl_usdt)/trades):'—')+'</strong></article>'+
    '<article><span>Cierres técnicos</span><strong>'+finite(score.technical_closed_trades).toFixed(0)+'</strong></article>'+
    '<article><span>P&amp;L total bruto · incluye técnicos</span><strong>'+money(score.gross_realized_pnl_usdt||0)+'</strong></article>'+
    '<article><span>Ganancia media · todos los cierres</span><strong>'+(score.average_win_usdt==null?'—':money(score.average_win_usdt))+'</strong></article>'+
    '<article><span>Pérdida media · todos los cierres</span><strong>'+(score.average_loss_usdt==null?'—':money(score.average_loss_usdt))+'</strong></article>'+
    '<article><span>LONG bruto · incluye técnicos</span><strong>'+money(score.long_gross_pnl_usdt||0)+'</strong></article>'+
    '<article><span>SHORT bruto · incluye técnicos</span><strong>'+money(score.short_gross_pnl_usdt||0)+'</strong></article>'+
    '<article><span>P&amp;L cerrado neto · incluye técnicos</span><strong>'+(score.financial?.net_realized_pnl_usdt==null?'PENDIENTE':money(score.financial.net_realized_pnl_usdt))+'</strong></article>'+
    '<article><span>Comisiones · cuenta Demo</span><strong>'+(score.financial?.account_commissions_usdt==null?'—':money(score.financial.account_commissions_usdt))+'</strong></article>'+
    '<article><span>Funding neto · cuenta Demo</span><strong>'+(score.financial?.account_funding_pnl_usdt==null?'—':money(score.financial.account_funding_pnl_usdt))+'</strong></article>'+
    '<article><span>Conciliación de costos</span><strong>'+esc(score.financial?.status||'PENDING')+' · '+finite(score.financial?.attributed_closed_trades).toFixed(0)+' / '+finite(score.closed_trades).toFixed(0)+' cierres</strong></article>'+
    '<article><span>Incidentes</span><strong>'+finite(score.incident_total).toFixed(0)+'</strong></article>'+
    '<article><span>Intentos fallidos</span><strong>'+finite(score.failure_attempt_total).toFixed(0)+'</strong></article>'+
    '<article><span>Errores consecutivos</span><strong>'+finite(score.consecutive_errors).toFixed(0)+'</strong></article>'+
    '<article><span>MAE / MFE por operación</span><strong>'+(score.mae_mfe_available===true?'DISPONIBLE':'PENDIENTE DE TELEMETRÍA')+'</strong></article>';
  const checks=document.getElementById('futuresReadinessChecks');
  if(checks){
    const rows=[[days>=30,days.toFixed(1)+' / 30 días'],[trades>=30,trades.toFixed(0)+' / 30 cierres'],
      [finite(score.consecutive_errors)===0,'Sin errores consecutivos activos'],
      [futures?.recovery?.durable_order_journal===true,'Journal durable'],
      [futures?.recovery?.startup_position_reconciliation===true,'Reconciliación al reiniciar'],
      [futures?.recovery?.native_exchange_stop_orders===true,'Integración de stops nativos disponible'],
      [positions.length>0&&positions.every(p=>futures?.native_protection?.positions?.[p.symbol]?.status==='ARMED'),
        positions.length?'Órdenes nativas confirmadas para todas las posiciones':'Sin exposición: confirmación nativa al abrir']];
    checks.replaceChildren();
    for(const [ok,label] of rows){const li=document.createElement('li');li.textContent=(ok?'✓':'○')+' '+label;checks.append(li);}
  }
  const assetGrid=document.getElementById('futuresMultiAsset');
  if(assetGrid){
    const symbols=Array.isArray(futures?.symbols)?futures.symbols:['BTCUSDT','ETHUSDT','SOLUSDT'];
    const bySymbol=score.by_symbol_direction||{};
    assetGrid.innerHTML=symbols.map(symbol=>{
      const p=positions.find(row=>row.symbol===symbol);
      const split=bySymbol[symbol]||{};
      const long=split.LONG||{}, short=split.SHORT||{};
      const native=futures?.native_protection?.positions?.[symbol];
      const nativeLabel=p?(native?.status==='ARMED'?'CONFIRMADA EN BINANCE':native?.status||'POR CONFIRMAR'):(native?'CONCILIACIÓN PENDIENTE':'SIN EXPOSICIÓN');
      const evidence=futuresSignalEvidence(futures,symbol);
      return '<article class="futures-asset-card"><h4>'+esc(symbol.replace('USDT',''))+'</h4><dl>'+
        '<div><dt>Estado</dt><dd>'+(p?esc(p.direction)+' · '+esc(String(p.leverage||1))+'x':evidence.issue?'DATOS NO DISPONIBLES':'ESPERANDO')+'</dd></div>'+
        (evidence.issue?'<div><dt>Bloqueo del último ciclo</dt><dd>'+esc(evidence.issue.reason||evidence.issue.status)+'</dd></div>':'')+
        (p?'<div><dt>Cantidad / entrada</dt><dd>'+num(p.quantity,6)+' / '+num(p.entry_price,4)+'</dd></div><div><dt>Mark / P&amp;L abierto bruto</dt><dd>'+(p.mark_price==null?'—':num(p.mark_price,4))+' / '+(p.unrealized_pnl_usdt==null?'—':money(p.unrealized_pnl_usdt))+'</dd></div><div><dt>P&amp;L tras costos acumulados</dt><dd>'+(p.unrealized_after_accrued_costs_usdt==null?'—':money(p.unrealized_after_accrued_costs_usdt))+'</dd></div><div><dt>Stop / objetivo</dt><dd>'+num(p.stop_price,4)+' / '+num(p.take_profit,4)+'</dd></div>':'')+
        '<div><dt>Protección nativa</dt><dd>'+esc(nativeLabel)+'</dd></div>'+
        (native?.confirmed_at?'<div><dt>Última confirmación</dt><dd>'+esc(shortTime(native.confirmed_at))+'</dd></div>':'')+
        (native?.error?'<div><dt>Detalle</dt><dd>'+esc(native.error)+'</dd></div>':'')+
        '<div><dt>LONG · historial total</dt><dd>'+String(long.trades||0)+' · '+money(long.gross_pnl_usdt||0)+'</dd></div>'+
        '<div><dt>SHORT · historial total</dt><dd>'+String(short.trades||0)+' · '+money(short.gross_pnl_usdt||0)+'</dd></div>'+
        '<div><dt>Score LONG / SHORT · sobre 100</dt><dd>'+esc(evidence.score)+'</dd></div>'+
        '<div><dt>Fecha de señal</dt><dd>'+esc(evidence.stamp)+'</dd></div>'+
      '</dl></article>';
    }).join('');
  }
  const signalGrid=document.getElementById('futuresSignalGrid');
  if(signalGrid){
    const symbols=Array.isArray(futures?.symbols)?futures.symbols:[];
    signalGrid.innerHTML=symbols.map(symbol=>{
      const s=(futures?.latest_signals||{})[symbol]||{};
      const r=(futures?.last_ai_reviews||{})[symbol]||{};
      const evidence=futuresSignalEvidence(futures,symbol);
      return '<article class="futures-asset-card"><h4>'+esc(symbol)+'</h4><dl>'+
        '<div><dt>LONG / SHORT · sobre 100</dt><dd>'+esc(evidence.score)+'</dd></div>'+
        '<div><dt>Fecha de señal</dt><dd>'+esc(evidence.stamp)+'</dd></div>'+
        '<div><dt>Dirección del último análisis</dt><dd>'+esc(evidence.fresh?(s.direction||'SIN SEÑAL'):'DATO HISTÓRICO')+'</dd></div>'+
        (evidence.issue?'<div><dt>Bloqueo del último ciclo</dt><dd>'+esc(evidence.issue.reason||evidence.issue.status)+'</dd></div>':'')+
        '<div><dt>RSI</dt><dd>'+(!evidence.fresh||s.rsi==null?'—':num(s.rsi,1))+'</dd></div>'+
        '<div><dt>Última revisión IA</dt><dd>'+esc(r.verdict||'SIN REVISIÓN')+(r.at?' · '+esc(shortTime(r.at)):'')+'</dd></div>'+
      '</dl></article>';
    }).join('');
  }
  const shadow=document.getElementById('futuresShadowStrategies');
  if(shadow){
    const rows=(futures?.shadow_scorecard||[]).filter(row=>!row.legacy_measurement).slice(0,9);
    shadow.innerHTML=rows.length?rows.map(row=>'<div><small>'+esc(row.strategy_key)+'</small><strong>'+num(row.pnl_pct||0,2)+'% · '+String(row.trades||0)+' trades</strong><small>Suma de retornos brutos por cierre; sin costos ni evaluación intravela. No es retorno de cartera.</small></div>').join(''):'<div><small>Shadow lab v2</small><strong>Acumulando muestras nuevas</strong></div>';
  }
  const body=document.getElementById('futuresTradeRows');
  const rows=(futures?.trades||[]).slice(0,12);
  if(body)body.innerHTML=rows.length?rows.map(t=>'<tr><td><strong>'+esc(t.symbol)+' '+esc(t.direction)+' · '+esc(String(t.leverage||1))+'x</strong></td><td>'+num(t.quantity,6)+'</td><td>'+num(t.entry_price,2)+'</td><td>'+num(t.exit_price,2)+'</td><td class="'+(Number(t.gross_pnl)>=0?'positive':'negative')+'">'+(Number(t.gross_pnl)>=0?'+':'')+num(t.gross_pnl,6)+'</td><td>'+esc(t.exit_reason||'—')+'</td></tr>').join(''):emptyRow(6,'Aún no hay cierres Futures.');
}

function spotDiagnostic(health) {
  const error=health?.last_error;
  const recovery=health?.last_recovery;
  const active=Number(health?.consecutive_errors||0)>0;
  const recovered=!active&&Number.isFinite(new Date(recovery?.at).getTime())
    &&(!error||new Date(recovery.at).getTime()>new Date(error.at).getTime());
  const label=recovered?'Sin errores activos · recuperado '+shortTime(recovery.at)
    :error?.code?'['+String(error.code)+'] '+String(error.label||'diagnóstico disponible')+' · '+shortTime(error.at)
    :active?'Errores activos; diagnóstico no disponible':'Sin diagnóstico persistente';
  return {label,recovered};
}

function renderObservationHealth(spotHealth, futuresHealth, futures, status={}) {
  // Continuity alone cannot certify that every contract is available now.
  if(futures?.cycle_diagnostic){
    const stale=!futuresCycleFresh(futures,status);
    const partial=!stale&&futures.cycle_diagnostic.state==='ATTENTION';
    if(stale||partial)futuresHealth={...futuresHealth,
      state:futuresHealth?.state==='ATTENTION'?'ATTENTION':'WATCH',
      reason_codes:[...(futuresHealth?.reason_codes||[]),stale?'cycle_stale':'contract_data_unavailable']};
  }
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const stateClass=value=>value==='OK'?'':value==='ATTENTION'?'offline':'warning';
  const stateLabel=value=>({OK:'ESTABLE',WATCH:'VIGILAR',ATTENTION:'ATENCIÓN',STARTING:'INICIANDO'})[value]||'SIN DATOS';
  const formatGap=value=>value==null?'—':value<60?Math.round(value)+' s':(value/60).toFixed(1)+' min';
  const integrityText=value=>{const entries=Object.entries(value||{});if(!entries.length)return '—';const ok=entries.filter(([,passed])=>passed===true).length;return ok===entries.length?'✓ '+ok+'/'+entries.length+' comprobaciones':ok+'/'+entries.length+' correctas';};
  const renderState=(id,value)=>{const node=document.getElementById(id);if(!node)return;node.textContent=stateLabel(value);node.className='state '+stateClass(value);};
  const reasonLabels={
    cycle_coverage_below_90:'cobertura de ciclos por debajo de 90%',
    errors_observed:'errores registrados durante las últimas 24 h',
    warnings_observed:'avisos registrados durante las últimas 24 h',
    position_count_exceeded:'cantidad de posiciones fuera del límite',
    order_journal_pending:'journal de órdenes pendiente',
    market_prices_stale:'cotizaciones de mercado desactualizadas',
    consecutive_errors_active:'errores consecutivos activos',
    evidence_gap_present:'hay una brecha de evidencia marcada',
    cycle_stale:'último ciclo desactualizado',
    contract_data_unavailable:'datos insuficientes o bloqueo parcial de contratos en el último ciclo'
  };
  const reasonText=(health,stable)=>{
    const reasons=Array.isArray(health?.reason_codes)?health.reason_codes.map(code=>reasonLabels[code]||String(code).replaceAll('_',' ')):[];
    return reasons.length?'Motivo: '+reasons.join(' · '):stable;
  };
  renderState('spotHealthState',spotHealth?.state);
  renderState('futuresHealthState',futuresHealth?.state);
  set('spotCycleCoverage',spotHealth?Number(spotHealth.cycle_coverage_pct||0).toFixed(1)+'%':'—');
  set('spotCycleSamples',spotHealth?String(spotHealth.samples||0)+' / '+String(spotHealth.expected_samples||0):'—');
  set('spotCycleGap',formatGap(spotHealth?.average_cycle_gap_seconds));
  set('spotDailyErrors',spotHealth?String(spotHealth.errors||0)+' errores · '+String(spotHealth.warnings||0)+' avisos':'—');
  set('spotConsecutiveErrors',spotHealth?String(spotHealth.consecutive_errors||0)+' activos':'—');
  const diagnosis=spotDiagnostic(spotHealth);
  set('spotLastError',diagnosis.label);
  set('spotDailyAi',spotHealth?String(spotHealth.ai_reviews||0)+' revisiones · '+String(spotHealth.ai_rejects||0)+' rechazos':'—');
  set('spotDailyTrading',spotHealth?String(spotHealth.closed_trades||0)+' · '+money(spotHealth.realized_pnl_usdt||0):'—');
  set('spotIntegrity',integrityText(spotHealth?.integrity));
  const spotStable=diagnosis.recovered
    ? 'El último error quedó recuperado; no hay errores consecutivos activos.'
    : 'Sin incidencias operativas relevantes en la ventana de 24 h.';
  set('spotHealthReason',reasonText(spotHealth,spotStable));
  set('futuresCycleCoverage',futuresHealth?Number(futuresHealth.cycle_coverage_pct||0).toFixed(1)+'%':'—');
  set('futuresCycleSamples',futuresHealth?String(futuresHealth.samples||0)+' / '+String(futuresHealth.expected_samples||0):'—');
  set('futuresCycleGap',formatGap(futuresHealth?.average_cycle_gap_seconds));
  set('futuresDailyErrors',futuresHealth?String(futuresHealth.consecutive_errors||0)+' activos':'—');
  set('futuresHealthCounters',futuresHealth?String(futuresHealth.incident_total||0)+' / '+String(futuresHealth.failure_attempt_total||0)+' / '+String(futuresHealth.cycle_total||0):'—');
  set('futuresDailyTrading',futuresHealth?String(futuresHealth.closed_trades||0)+' · '+money(futuresHealth.realized_pnl_usdt||0):'—');
  set('futuresIntegrity',integrityText(futuresHealth?.integrity));
  set('futuresHealthReason',reasonText(futuresHealth,'Sin bloqueos de journal, integridad o errores consecutivos.'));
  set('futuresHealthLatest',futures?.cycle_diagnostic?.at?shortTime(futures.cycle_diagnostic.at)+' · '+(futuresCycleFresh(futures,status)?'reciente':'desactualizado'):'Sin diagnóstico del último ciclo');
  const states=[spotHealth?.state,futuresHealth?.state];
  const overall=states.includes('ATTENTION')?'ATTENTION':states.includes('WATCH')?'WATCH':states.every(x=>x==='OK')?'OK':'STARTING';
  renderState('observationHealthState',overall);
  const note=document.getElementById('observationHealthNote');
  if(note)note.textContent=overall==='OK'?'La muestra de las últimas 24 h tiene continuidad e integridad operativa suficientes para seguir observando sin intervenir.':overall==='ATTENTION'?'Hay una condición operativa concreta que requiere atención antes de interpretar resultados. Los motivos aparecen debajo de cada motor.':overall==='WATCH'?'Hay incidencias recuperadas o continuidad parcial para vigilar; no implican por sí solas que el motor esté actualmente fallando.':'La muestra sigue acumulándose; no cambia estrategia ni riesgo durante esta fase.';
}

function renderResearch(report, state) {
  PulsePortal.renderResearch(report?.market_pulse_observation);
  globalThis.CryptoResearchValidation?.render(report?.validation_summary);
  lastResearchReport=report;
  const badge=document.getElementById('researchState');
  const button=document.getElementById('researchButton');
  button.disabled=Boolean(state.running);
  document.getElementById('exportResearch').disabled=!(report.assets?.length);
  button.textContent=state.running?'Analizando…':'Actualizar análisis ahora';
  document.getElementById('researchSchedule').textContent=(state.automatic===undefined?'Actualiza el bot para habilitar el horario diario.':
    `Automático ${state.automatic?'cada 24 h':'desactivado'} · Último completo: ${shortTime(state.last_completed_at||report.generated_at)} · Próximo: ${state.automatic?shortTime(state.next_run_at):'—'} · Requiere Windows y el bot encendidos.`)
    +(state.progress?` · ${state.progress}`:'')+(state.status==='INTERRUPTED'?' · La ejecución anterior se interrumpió; puedes actualizar ahora.':'');
  if(state.error&&report.generated_at)document.getElementById('researchSchedule').textContent+=
    ` Se muestra el informe anterior de ${shortTime(report.generated_at)}: ${report.assets?.length||0} activos Spot y ${report.futures_assets?.length||0} Futures; la ampliación no está validada en este informe.`;
  renderResearchExperiments(report);
  const references=Array.isArray(report.operating_baselines)?report.operating_baselines.filter(b=>b.evidence==='SIGNAL_PARITY_ONLY'):[];
  document.getElementById('researchOperatingReference').hidden=references.length===0;
  document.getElementById('researchOperatingBaselines').innerHTML=references.map(b=>{
    const limits=b.configuration?.limits||{};
    const window=b.windows?.development_oos||{};
    const count=b.market==='SPOT'?limits.max_positions:limits.forward_max_positions;
    const budget=b.market==='SPOT'?`Exposición ≤${num(Number(limits.max_total_exposure_pct||0)*100,0)}%`:
      `Notional ≤${money(limits.forward_total_notional_usdt)} · pérdida estimada hasta stops ≤${money(limits.forward_total_stop_loss_usdt)}`;
    return `<article><span>${esc(b.market)} · ${esc(String(b.timeframe||'').toUpperCase())} · score ${Number(b.configuration?.minimum_score||0)}</span><strong>${Number(window.eligible_signals||0)} señales elegibles</strong><small>En ${Number(window.evaluated_symbol_bars||0)} velas/activo evaluadas fuera de entrenamiento · hasta ${Number(count||0)} posiciones · ${budget}</small></article>`;
  }).join('');
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
    <article><span>Activos Spot / Futures</span><strong>${Number(summary.assets)} / ${Number(report.futures_assets?.length||0)}</strong></article>
    <article><span>Estrategias Spot evaluadas</span><strong>${Number(summary.assets)*Number(summary.strategies_per_asset)}</strong></article>
    <article><span>Folds fuera de muestra</span><strong>${Number(summary.total_walk_forward_folds)}</strong></article>
    <article><span>Candidatos a forward test</span><strong>${Number(summary.forward_test_ready||summary.promotion_candidates||0)}</strong></article>
    <article><span>Ilustración fija por ventanas</span><strong class="${Number(portfolio.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(portfolio.oos_compounded_return_pct)}</strong></article>
    <article><span>Ilustración selector + cash</span><strong class="${Number(adaptivePortfolio.oos_compounded_return_pct)>=0?'positive':'negative'}">${pct(adaptivePortfolio.oos_compounded_return_pct)}</strong></article>
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
  }).join(''):emptyRow(9,state.running?'El análisis está trabajando en segundo plano…':'El primer análisis se iniciará automáticamente; también puedes actualizarlo ahora.');
  const detail=state.error?`Último error: ${state.error}`:(report.generated_at?`Informe generado ${shortTime(report.generated_at)} · Los candidatos siguen bloqueados para operación automática.`:'El estudio descarga aproximadamente 5,000 velas cerradas por activo y puede tardar varios minutos.');
  document.getElementById('researchUpdated').textContent=detail;
}

function researchScenarioKey(p) { return `${p.market}-${p.profile}-${p.leverage}`; }
function renderResearchExperiments(report) {
  const runs=report.joint_portfolios||[];
  const choice=document.getElementById('researchCurveChoice');
  const selected=choice.value;
  choice.innerHTML=runs.map(p=>`<option value="${esc(researchScenarioKey(p))}">${esc(p.market)} · ${esc(p.profile)} · ${Number(p.leverage)}x</option>`).join('');
  choice.value=runs.some(p=>researchScenarioKey(p)===selected)?selected:(runs.length?researchScenarioKey(runs[0]):'');
  document.getElementById('researchPortfolios').innerHTML=runs.length?runs.map(p=>`<tr><td>${esc(p.market)} · ${esc(p.profile)}<small>Riesgo ${num(p.limits?.risk_pct,2)}% · exposición ≤${num(p.limits?.gross_pct,0)}%</small></td><td>${Number(p.leverage)}x</td><td>${pct(p.net_return_pct)}</td><td>${num(p.max_drawdown_pct,2)}%</td><td>${Number(p.closed_trades)}</td><td>${money(p.fees)} / ${money(p.funding_cost)}</td><td>${Number(p.liquidations)}</td><td>${pct(p.holdout?.net_return_pct)} / ${pct(p.double_cost_holdout?.net_return_pct)}</td></tr>`).join(''):emptyRow(8,'Las carteras aparecerán al completar el nuevo análisis.');
  const names={positive_oos:'OOS no positivo',minimum_evidence:'Actividad OOS insuficiente',consistent_folds:'Pocas ventanas positivas',holdout_positive:'Ventana final no positiva',double_costs_positive:'Costos duplicados no positivos',forward_test_independent:'Falta forward independiente',contract_liquidation_calibration:'Liquidación aproximada sin calibración por contrato'};
  document.getElementById('researchFuturesAssets').innerHTML=(report.futures_assets||[]).map(a=>`<tr><td>${esc(a.symbol)}</td><td>${esc(a.champion_candidate)}<small>Elegido solo en entrenamiento inicial</small></td><td>${pct(a.oos_return_pct)}<small>${Number(a.folds?.length||0)} ventanas</small></td><td>${pct(a.holdout?.net_return_pct)} / ${pct(a.double_cost_holdout?.net_return_pct)}</td><td>${(a.discarded_reasons||[]).map(r=>esc(names[r]||r)).join(' · ')}</td></tr>`).join('')||emptyRow(5,'Sin evidencia Futures en este informe.');
  const unavailable=report.coverage?.unavailable||[];
  document.getElementById('researchAssumptions').textContent=runs.length?
    `Velas del estudio: Spot ${String(report.experiment?.spot_timeframe||report.experiment?.timeframe||'sin dato').toUpperCase()} · Futures ${String(report.experiment?.futures_timeframe||report.experiment?.timeframe||'sin dato').toUpperCase()}. `+
    'Futures: histórico público USD-M, mark y funding reales; liquidación como estrés de margen aislado con mantenimiento supuesto del 1% y comisiones/slippage configurados. Requiere calibración por contrato antes de calificar. '+
    (unavailable.length?`Sin datos válidos: ${unavailable.map(a=>`${a.market} ${a.symbol} (${a.reason})`).join(', ')}.`:'Cobertura de datos completa para los activos solicitados.'):'No hay simulaciones conjuntas en el informe anterior.';
  document.getElementById('researchForward').innerHTML=(report.forward_observation||[]).map(f=>{
    const labels={WAITING_NEW_DATA:'Esperando velas posteriores al registro',OBSERVING:'Observando reglas congeladas',DATA_UNAVAILABLE:'Faltan datos de la cohorte',HISTORY_GAP:'Historial incompleto'};
    return `<p><strong>Seguimiento futuro ${esc(f.market)} ${esc(String(f.timeframe||report.experiment?.timeframe||'').toUpperCase())}:</strong> ${esc(labels[f.status]||f.status)} · ${num(f.observed_days,1)}/30 días · ${Number(f.simulation?.closed_trades||0)}/30 cierres · ${f.simulation?pct(f.simulation.net_return_pct):'sin resultado todavía'}. Cohorte de ${Number(f.symbols?.length||0)} activos fijada ${shortTime(f.registered_at)}. Observación simulada con datos nuevos; ninguna promoción automática.</p>`;
  }).join('');
  renderResearchCurve();
}
function renderResearchCurve() {
  const key=document.getElementById('researchCurveChoice').value;
  const p=(lastResearchReport?.joint_portfolios||[]).find(s=>researchScenarioKey(s)===key);
  renderChart((p?.curve||[]).map(c=>({equity:c.equity})), 'researchCurve');
  document.getElementById('researchCurveInfo').textContent=p?`${p.market} · ${p.profile} · ${p.leverage}x · Capital inicial ${money(p.initial_cash)} · OOS ${shortTime(p.start_at)} a ${shortTime(p.end_at)} · Final reservada desde ${shortTime(p.holdout_start_at)}. Curva por vela muestreada; drawdown calculado con todas las velas.`:'';
  document.getElementById('researchDiscardReasons').textContent=p?`Motivos para mantener en investigación: ${(p.discarded_reasons||[]).join(' · ')}.`:'';
  document.getElementById('researchHistory').innerHTML=(lastResearchReport?.history||[]).slice().reverse().map(run=>{
    const item=(run.scenarios||[]).find(s=>researchScenarioKey(s)===key);
    return `<tr><td>${shortTime(run.generated_at)}</td><td>${Number(run.assets)} / ${Number(run.futures_assets||0)}</td><td>${item?pct(item.net_return_pct):'—'}</td><td>${item?num(item.max_drawdown_pct,2)+'%':'—'}</td><td>${item?Number(item.closed_trades):'—'}</td><td>${item?Number(item.liquidations):'—'}</td></tr>`;
  }).join('')||emptyRow(6,'Sin ejecuciones archivadas todavía.');
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
    ${candidates.length&&candidates.every(row=>row.development_oos_return_pct==null)?'<p class="research-updated">Informe anterior: no contiene el desglose OOS por candidata. Vuelve a ejecutar el análisis para obtenerlo; no se sustituyen los datos ausentes por cero.</p>':''}
    <div class="detail-columns"><div><h4>Por régimen · estrategia fija</h4>${regimes.map(row=>`<p><span>${esc(row.regime)} · ${Number(row.folds||0)} folds</span><strong>${Number(row.folds)>0?pct(row.average_return_pct):'Sin muestras'}</strong></p>`).join('')}</div>
    <div><h4>Sensibilidad del score · muestra completa</h4>${sensitivity.map(row=>`<p><span>Umbral ${Number(row.minimum_score)}</span><strong>${pct(row.return_pct)} · DD ${Number(row.max_drawdown_pct||0).toFixed(1)}%</strong></p>`).join('')}</div></div>`;
  panel.scrollIntoView({behavior:'smooth',block:'nearest'});
}

function exportResearchCsv() {
  if (!lastResearchReport?.assets?.length) return;
  const lines=[['Registro','Fecha','Mercado','Activo o perfil','Leverage','Periodo','Retorno neto %','Drawdown %','Cierres','Comisiones','Funding','Liquidaciones','Motivos de descarte']];
  const date=lastResearchReport.generated_at;
  lastResearchReport.assets.forEach(a=>{const fixed=a.fixed_strategy||a.walk_forward||{};
    lines.push(['Activo',date,'SPOT',a.symbol,1,'OOS por ventanas; DD peor ventana',fixed.oos_compounded_return_pct,fixed.worst_fold_drawdown_pct,fixed.trades,'','','',(a.discarded_reasons||[]).join(' | ')]);
  });
  (lastResearchReport.futures_assets||[]).forEach(a=>lines.push(['Activo',date,'FUTURES',a.symbol,1,'OOS por ventanas',a.oos_return_pct,'',a.folds?.reduce((n,f)=>n+Number(f.closed_trades||0),0),'','','',(a.discarded_reasons||[]).join(' | ')]));
  (lastResearchReport.joint_portfolios||[]).forEach(p=>{
    for(const [period,result] of [['OOS',p],['Final reservada',p.holdout],['Final costos x2',p.double_cost_holdout]]){
      if(result)lines.push(['Cartera',date,p.market,p.profile,p.leverage,period,result.net_return_pct,result.max_drawdown_pct,result.closed_trades,result.fees,result.funding_cost,result.liquidations,(p.discarded_reasons||[]).join(' | ')]);
    }
  });
  (lastResearchReport.history||[]).forEach(run=>(run.scenarios||[]).forEach(p=>lines.push(['Historial',run.generated_at,p.market,p.profile,p.leverage,'OOS',p.net_return_pct,p.max_drawdown_pct,p.closed_trades,'','',p.liquidations,''])));
  const csv=lines.map(row=>row.map(value=>{let cell=String(value);if(/^[=+\-@\t\r]/.test(cell))cell="'"+cell;return `"${cell.replaceAll('"','""')}"`;}).join(',')).join('\r\n');
  const link=document.createElement('a'); link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  link.download=`crypto-ai-research-${new Date().toISOString().slice(0,10)}.csv`; link.click(); URL.revokeObjectURL(link.href);
}

function renderSpotCycle(status){
  const badge=document.getElementById('spotCycleState'),summary=document.getElementById('spotCycleSummary'),detail=document.getElementById('spotCycleReasons');
  if(!badge||!summary||!detail)return;
  const c=status?.spot_cycle;
  const labels={RUNNING:'ANALIZANDO',NO_OPPORTUNITIES:'TRABAJANDO · SIN OPORTUNIDADES',FILTERED:'CANDIDATAS DESCARTADAS',
    LIMITED:'ENTRADAS LIMITADAS',OPENED:'ENTRADAS EJECUTADAS',PAUSED:'NUEVAS ENTRADAS PAUSADAS',RISK_HALT:'LÍMITE DE PÉRDIDA',
    ATTENTION:'REQUIERE ATENCIÓN',ERROR:'ERROR EN EL CICLO'};
  const reasons={BELOW_SCORE:'no alcanzan el score mínimo',ALREADY_HELD:'ya tienen una posición abierta',
    MISSING_CANDLES:'sin velas suficientes o disponibles',QUOTE_UNAVAILABLE:'sin cotización válida',PRICE_OUTSIDE_RANGE:'precio fuera del rango de entrada',
    POSITION_COUNT_LIMIT:'máximo de posiciones',TOTAL_EXPOSURE_LIMIT:'máximo de exposición',EQUITY_LIMIT:'capital no disponible',
    AI_CYCLE_LIMIT:'tope de revisiones IA por ciclo',AI_DAILY_LIMIT:'tope de revisiones IA diario',CANDLE_ALREADY_CHECKED:'vela ya evaluada para entrada',
    AI_REJECTED:'descartadas por la revisión IA',AI_UNAVAILABLE:'fallo o indisponibilidad de IA',SIZE_LIMIT:'cantidad limitada por presupuesto o perfil de riesgo',
    PAUSED:'entradas pausadas',LOSS_LIMIT:'límite diario o semanal de pérdida',EXCHANGE_RULES_UNAVAILABLE:'reglas de Binance no disponibles',
    EXCHANGE_FILTER_PREFLIGHT:'cantidad o mínimos incompatibles con Binance',POSITION_SIZE_LIMIT:'tope de tamaño de posición',PER_TRADE_RISK_LIMIT:'tope de riesgo por operación',
    LOCAL_ALLOCATION_LIMIT:'asignación insuficiente',LOCAL_CASH_LIMIT:'efectivo insuficiente',PRICE_MOVED_OUTSIDE_SIGNAL_RANGE:'precio cambió fuera del rango permitido',
    EXCHANGE_FILTER_REJECTED:'Binance rechazó los filtros de cantidad',TESTNET_BALANCE_LIMIT:'saldo USDT insuficiente en Testnet',CYCLE_ERROR:'fallo operativo del ciclo',NATIVE_PROTECTION_BLOCKED:'protección nativa rechazada; salidas vigiladas, entradas bloqueadas'};
  const errors={ORDER_RECONCILIATION_PENDING:'orden pendiente de conciliación',BTC_REGIME_UNAVAILABLE:'datos BTC no disponibles',
    FRESH_PRICES_UNAVAILABLE:'cotizaciones recientes no disponibles',INVALID_SPOT_QUOTE:'cotización inválida',HELD_QUOTE_MISSING:'falta precio de una posición',
    HELD_QUOTE_INVALID:'precio inválido de una posición',UNEXPECTED_VALUE_ERROR:'validación interna inesperada',TESTNET_EXECUTION_ERROR:'fallo de ejecución o conciliación Testnet',UNEXPECTED_ERROR:'fallo operativo inesperado'};
  badge.className='state neutral'; detail.textContent='';
  if(!c||!labels[c.state]){
    badge.textContent='SIN DETALLE AÚN';
    summary.textContent='Esperando el diagnóstico del próximo ciclo; todavía no se puede distinguir falta de oportunidades de un bloqueo.';
    return;
  }
  const age=(Date.now()-Date.parse(c.at))/1000;
  const cycleSeconds=Number(status.cycle_seconds)||900;
  const stale=!c.fresh||!Number.isFinite(age)||age < -120||age>Math.max(cycleSeconds*1.5,cycleSeconds+120);
  const state=stale?'STALE':c.state==='ERROR'?'ERROR':status.killed?'PAUSED':c.state;
  badge.textContent=stale?'SIN DATOS RECIENTES':labels[state];
  badge.className='state'+(['ERROR','STALE'].includes(state)?' offline':['ATTENTION','LIMITED','PAUSED','RISK_HALT'].includes(state)?' warning':state==='RUNNING'?' neutral':'');
  if(state==='RUNNING')summary.textContent='El motor está analizando datos. El resultado aparecerá al terminar el ciclo.';
  else if(stale)summary.textContent='El último diagnóstico quedó desactualizado. Comprueba la conexión y el próximo ciclo.';
  else if(state==='ERROR')summary.textContent='El último ciclo no terminó correctamente: '+(errors[c.error_code]||'fallo operativo')+'.';
  else if(state==='PAUSED')summary.textContent='El bloqueo de nuevas entradas está activo.';
  else if(state==='RISK_HALT'){
    const h=c.risk_halt;
    if(h?.periods?.length){
      const period=h.periods.map(p=>p==='daily'?'diario':'semanal').join(' + ');
      summary.textContent=`Nuevas entradas bloqueadas por el límite ${period}. Retorno diario ${Number(h.daily_return_pct).toFixed(2)}% (límite -${Number(h.daily_limit_pct).toFixed(2)}%) · semanal ${Number(h.weekly_return_pct).toFixed(2)}% (límite -${Number(h.weekly_limit_pct).toFixed(2)}%). Se libera al vencer el bloqueo: ${shortTime(h.resets_at)}.`;
    }else summary.textContent='Las nuevas entradas están bloqueadas por el límite de pérdida; esperando detalle del próximo ciclo.';
  }
  else summary.textContent=`Universo: ${c.universe} monedas · ${c.evaluated} evaluadas · ${c.signals} señales de compra · ${c.candidates} candidatas · ${c.reviews} revisiones IA · ${c.opened} entradas ejecutadas.`;
  const entries=Object.entries(c.reasons||{}).sort(([a],[b])=>Number(a==='BELOW_SCORE')-Number(b==='BELOW_SCORE'));
  detail.textContent='Ciclo: '+shortTime(c.at)+' · score mínimo '+c.minimum_score+'/100'+
    (c.btc_bullish===null?'':c.btc_bullish?' · régimen BTC favorable':' · régimen BTC penaliza entradas')+
    (entries.length?' · '+entries.map(([code,count])=>`${count}: ${reasons[code]||'descarte registrado'}`).join(' · '):'');
}

function renderFuturesCycle(futures,status){
  const badge=document.getElementById('futuresCycleState'),summary=document.getElementById('futuresCycleSummary'),detail=document.getElementById('futuresCycleReasons');
  if(!badge||!summary||!detail)return;
  const c=futures?.cycle_diagnostic;
  const labels={WAITING_CANDLE:'ESPERANDO NUEVA VELA',NO_OPPORTUNITIES:'SIN OPORTUNIDADES',FILTERED:'SEÑALES DESCARTADAS',
    LIMITED:'ENTRADAS LIMITADAS',OPENED:'ENTRADA EJECUTADA',ATTENTION:'REQUIERE ATENCIÓN',RISK_HALT:'LÍMITE DE PÉRDIDA',ACTIVE:'ACTIVO'};
  const reasons={NO_NEW_CANDLE:'esperando el cierre de una nueva vela',FLAT:'sin señal LONG/SHORT',OPEN:'posición ya abierta',
    AI_REJECTED:'rechazada por IA',AI_BUDGET:'tope diario de revisiones IA',POSITION_LIMIT:'máximo de posiciones',
    PRICE_OUTSIDE_RANGE:'precio fuera del stop/objetivo de la señal revisada',
    BUDGET_LIMIT:'presupuesto agregado de riesgo/exposición',MARGIN_LIMIT:'margen Demo insuficiente',TRIAL_MARGIN_RISK_LIMIT:'riesgo incompatible con el leverage de prueba',
    BLOCKED:'contrato bloqueado por preflight',ASSET_UNAVAILABLE:'filtros o referencia del contrato no disponibles',NO_DATA:'sin datos del contrato',
    KILLED:'motor pausado',PENDING_RECONCILIATION:'conciliación de orden pendiente',RISK_HALT:'límite de pérdida activo',OFF:'forward test deshabilitado',
    OPENED:'entrada ejecutada',CLOSED:'posición cerrada',ERROR:'error operativo'};
  badge.className='state neutral';detail.textContent='';
  if(!c||!labels[c.state]){
    badge.textContent='SIN DETALLE AÚN';
    summary.textContent='Esperando el diagnóstico del próximo ciclo Futures.';
    return;
  }
  const stale=!futuresCycleFresh(futures,status);
  if(stale){
    badge.textContent='SIN DATOS RECIENTES';badge.className='state offline';
    summary.textContent='El diagnóstico de Futures quedó desactualizado. Comprueba la conexión de Windows y el próximo ciclo.';
    return;
  }
  badge.textContent=labels[c.state];
  badge.className='state'+(['ATTENTION'].includes(c.state)?' warning':c.state==='RISK_HALT'?' warning':'');
  if(c.state==='WAITING_CANDLE')summary.textContent=`Motor operativo. La estrategia decide con velas ${String(c.timeframe||'—').toUpperCase()}; todavía no cerró una nueva vela desde la última decisión.`;
  else if(c.state==='NO_OPPORTUNITIES')summary.textContent=`${c.evaluated} contratos evaluados en ${String(c.timeframe||'—').toUpperCase()} · 0 señales LONG/SHORT con score mínimo ${c.minimum_score}/100.`;
  else if(c.state==='FILTERED')summary.textContent=`${c.evaluated} contratos evaluados · ${c.signals} señales · ${c.reviews} revisiones IA · ninguna entrada ejecutada.`;
  else if(c.state==='LIMITED')summary.textContent=`Hubo ${c.signals} señales, pero alguna barrera de riesgo, presupuesto o capacidad impidió una nueva entrada.`;
  else if(c.state==='OPENED')summary.textContent=`${c.opened} entrada${c.opened===1?'':'s'} ejecutada${c.opened===1?'':'s'} en el último ciclo.`;
  else if(c.state==='ATTENTION')summary.textContent='El último ciclo encontró un bloqueo operativo o datos insuficientes en al menos un contrato.';
  else if(c.state==='RISK_HALT')summary.textContent='Futures conserva protecciones, pero las nuevas entradas están bloqueadas por su límite de pérdida.';
  else summary.textContent=`Motor Futures activo · ${c.symbols} contratos configurados · timeframe ${String(c.timeframe||'—').toUpperCase()} · score mínimo ${c.minimum_score}/100.`;
  summary.textContent=`Universo: ${c.symbols??'—'} contratos · ${c.evaluated??'—'} evaluados · ${c.signals??'—'} señales · ${c.reviews??'—'} revisiones IA · ${c.opened??'—'} entradas ejecutadas. `+summary.textContent;
  const entries=Object.entries(c.statuses||{}).sort((a,b)=>b[1]-a[1]);
  const issues=Array.isArray(c.issues)?c.issues:[];
  const issueText=issues.map(row=>{
    const symbol=String(row.symbol||'').replace(/USDT$/,'')||'Contrato';
    const raw=String(row.reason||reasons[row.status]||'contrato no disponible')
      .replace(/^FuturesForwardAssetUnavailable:\s*/,'')
      .replace(/^FuturesTestnetExecutionError:\s*/,'');
    return symbol+': '+raw;
  });
  detail.textContent='Ciclo: '+shortTime(c.at)
    +(entries.length?' · '+entries.map(([code,count])=>`${count}: ${reasons[code]||code.toLowerCase()}`).join(' · '):'')
    +(issueText.length?' · Detalle: '+issueText.join(' · '):'');
}

/* Seven workspaces share the existing API reads, controls and engine renderers. */
const CommandCenterPortal = (() => {
  const routes=Object.freeze({
    'command-center':'Command Center','portfolio-capital':'Portfolio & Capital','trading-engines':'Trading Engines',
    'guardian-ai':'Guardian AI','operations-decisions':'Operations & Decisions','research-lab':'Research Lab','system-settings':'System & Settings'
  });
  const aliases=Object.freeze({
    'platform-overview':'command-center','command-center-heading':'command-center',
    'spot-bot':'trading-engines','futures-bot':'trading-engines','market-pulse':'trading-engines','quant-arbitrage':'trading-engines',
    'spot-analysis':'trading-engines','futures-analysis':'trading-engines','spot-limits':'trading-engines','futures-limits':'trading-engines',
    'spot-positions':'trading-engines','futures-positions':'trading-engines',
    'pulse-live':'trading-engines','pulse-news':'trading-engines','pulse-scanner':'trading-engines','pulse-decisions':'trading-engines','pulse-finance':'trading-engines','pulse-health':'trading-engines',
    'quant-funding':'trading-engines','quant-statistical':'trading-engines','quant-positions':'trading-engines','quant-decisions':'trading-engines','quant-finance':'trading-engines','quant-health':'trading-engines',
    'portfolio-guardian':'guardian-ai','guardian-exposure':'guardian-ai','guardian-overlaps':'guardian-ai','guardian-quality':'guardian-ai',
    'guardian-intelligence':'guardian-ai','intelligence-scopes':'guardian-ai','intelligence-sources':'guardian-ai','intelligence-ai':'guardian-ai','intelligence-conflicts':'guardian-ai','intelligence-journal':'guardian-ai','intelligence-queries':'guardian-ai',
    'comparison-details':'portfolio-capital','spot-finance':'portfolio-capital','futures-finance':'portfolio-capital',
    'capital-lab':'research-lab','capital-lab-audit':'research-lab','research-validation':'research-lab',
    'opportunity-shadow':'guardian-ai','opportunity-capital':'guardian-ai','opportunity-decisions':'guardian-ai',
    'activity-section':'operations-decisions','historyPanel':'operations-decisions',
    'modelSettingsPanel':'system-settings','diagnosticsPanel':'system-settings','observation-details':'system-settings',
    'updates':'system-settings','updatePanel':'system-settings','password':'system-settings','passwordPanel':'system-settings'
  });
  const targets=Object.freeze({updates:'updatePanel',password:'passwordPanel'});
  const names=Object.freeze({SPOT:'Spot Bot',FUTURES:'Futures Bot',AI_MARKET_PULSE:'AI Market Pulse',QUANT_ARBITRAGE:'Quant Arbitrage'});
  const scopeIds=Object.keys(names);
  const panes=()=>[...(document.querySelectorAll?.('[data-workspace]')||[])].filter(node=>Object.hasOwn(routes,node.dataset.workspace));
  const hasViews=()=>panes().length===7;
  const resolve=id=>typeof id==='string'&&id.length<=100?(Object.hasOwn(routes,id)?id:Object.hasOwn(aliases,id)?aliases[id]:null):null;
  const targetId=id=>Object.hasOwn(targets,id)?targets[id]:id;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const html=(id,value)=>{const node=document.getElementById(id);if(node)node.innerHTML=value;};
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const number=value=>finite(value)?value.toLocaleString('en-US',{maximumFractionDigits:2}):'—';
  const cash=value=>finite(value)?number(value)+' USDT':'—';
  const short=value=>typeof value==='string'?value.slice(0,280):'Sin detalle disponible';
  const rows=(value,limit)=>Array.isArray(value)?value.filter(item=>item&&typeof item==='object').slice(0,limit):[];
  const stamp=value=>typeof value==='string'&&Number.isFinite(Date.parse(value))?value:null;
  const time=value=>stamp(value)?new Date(value).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'}):'Hora no disponible';
  const metric=values=>values.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const validGuardian=g=>g?.schema===1&&g.engine==='PORTFOLIO_GUARDIAN'&&g.mode==='OBSERVER'&&g.controls_enabled===false&&g.can_veto===false&&g.execution_enabled===false&&['OBSERVING','PARTIAL','DEGRADED'].includes(g.state);
  let initialized=false;
  function selectFor(id){
    const route=resolve(id);if(!route||!hasViews())return false;
    for(const pane of panes())pane.hidden=pane.dataset.workspace!==route;
    for(const link of document.querySelectorAll('.platform-nav a')){
      if(link.getAttribute('href')==='#'+route)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    }
    const choice=document.getElementById('workspaceChoice');if(choice)choice.value=route;
    set('workspaceAnnouncement',routes[route]);
    window.PulsePortal?.redrawVisibleCharts();
    return true;
  }
  function navigate(id,{historyMode='push',scroll=true,focus=false}={}){
    if(!resolve(id)||!hasViews())return false;
    if(!window.PulsePortal?.revealSection(id,scroll))return false;
    if(historyMode!=='none'){
      const url=`${location.pathname}${location.search||''}#${id}`;
      if(historyMode==='replace')history.replaceState({},'',url);
      else if(location.hash!=='#'+id)history.pushState({},'',url);
    }
    if(focus&&document.querySelector('.shell')?.hidden!==true){
      const heading=document.getElementById(resolve(id)+'-heading');heading?.focus({preventScroll:true});
    }
    return true;
  }
  function restore(){
    if(!hasViews())return;
    let id='command-center';
    try{const decoded=decodeURIComponent(location.hash.slice(1));if(resolve(decoded))id=decoded;}catch{}
    navigate(id,{historyMode:'none',scroll:document.querySelector('.shell')?.hidden!==true});
  }
  function init(){
    if(initialized||!hasViews())return;initialized=true;
    for(const link of document.querySelectorAll('.platform-nav a,.platform-detail,.pulse-subnav a,.workspace-links a,.command-link,.skip-link'))link.addEventListener('click',event=>{
      if(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      const id=link.getAttribute('href')?.slice(1);if(!resolve(id))return;
      event.preventDefault();
      // The established update action performs authentication and release checks.
      if(id==='updates'){document.getElementById('updateButton')?.click();return;}
      navigate(id,{focus:true});
    });
    document.getElementById('workspaceChoice')?.addEventListener('change',event=>navigate(event.target.value,{focus:true}));
    for(const [button,id] of [['modelSettingsButton','modelSettingsPanel'],['diagnosticsButton','diagnosticsPanel'],['historyButton','historyPanel'],['updateButton','updates'],['portalPasswordButton','password']]){
      document.getElementById(button)?.addEventListener('click',()=>navigate(id,{scroll:false}),true);
    }
    window.addEventListener('popstate',restore);window.addEventListener('hashchange',restore);restore();
  }
  function renderCapital(platform){
    const g=platform?.portfolio_guardian,valid=validGuardian(g),old=valid&&FourEnginePortal.isOld(g.at,platform?.remote_sync_stale===true);
    const seen=new Set(),scopes=valid?rows(g.scopes,4).filter(scope=>scopeIds.includes(scope.id)&&!seen.has(scope.id)&&(seen.add(scope.id),true)):[];
    set('capitalStatus',!valid?'Sin evidencia compatible. Los importes desconocidos no se sustituyen por cero.':old?`Lectura histórica de ${time(g.at)}. Capital y exposición actuales sin verificar.`:`Captura ${time(g.at)} · LEDGER_ONLY · cada entorno conserva su capital y límites.`);
    html('capitalScopes',scopeIds.map(id=>{
      const scope=scopes.find(item=>item.id===id),capital=scope?.capital||{},current=!!scope&&!old&&scope.state==='FRESH',capitalCurrent=current&&capital.state==='FRESH';
      const state=!scope?'SIN EVIDENCIA':old?'LECTURA ANTIGUA':scope.state==='NOT_STARTED'?'SIN INICIAR':current?'VALORACIÓN RECIENTE':'VALORACIÓN INCOMPLETA';
      return `<article class="guardian-scope"><div class="pulse-item-head"><h3>${esc(names[id])}</h3><span class="badge neutral">${state}</span></div><p class="platform-environment">${esc(short(scope?.environment||'Entorno sin confirmar'))} · LEDGER_ONLY</p><dl>${metric([
        ['Equity observada',cash(capitalCurrent?capital.equity_usdt:null)],['Efectivo registrado',cash(capitalCurrent?capital.cash_usdt:null)],
        ['Disponible reportado',cash(capitalCurrent?capital.available_usdt:null)],['Exposición bruta',cash(current?scope.gross_usdt:null)],['Exposición neta',cash(current?scope.net_usdt:null)],
        ['Posiciones / piernas del ledger',current?number(scope.position_count):'—'],['Capital capturado',stamp(capital.at)?time(capital.at):'Sin hora verificable']
      ])}</dl><small>${id==='AI_MARKET_PULSE'||id==='QUANT_ARBITRAGE'?'Capital hipotético Shadow. No son fondos disponibles para Spot o Futures.':'Capital de prueba del ledger; no acredita conciliación completa con todos los saldos del exchange.'}</small></article>`;
    }).join(''));
    set('capitalReservations','NO INTEGRADAS · importe desconocido');
  }
  function render({status={},reviews=[],events=[],marketPulse=null,platform=null,futuresForward={}}={}){
    renderCapital(platform);
    const g=platform?.portfolio_guardian,valid=validGuardian(g),remoteOld=platform?.remote_sync_stale===true;
    const guardianOld=valid&&FourEnginePortal.isOld(g.at,remoteOld);
    set('commandReadingState',remoteOld?'PROYECCIÓN ANTIGUA':'LECTURA RECIBIDA');
    set('commandReadingAt',valid?`Guardian capturado ${time(g.at)}${guardianOld?' · estado actual sin verificar':''}`:'Guardian sin captura compatible; consulta las fuentes de cada motor');
    set('commandGuardianState',valid?(guardianOld?'EVIDENCIA ANTIGUA':g.state==='OBSERVING'?'OBSERVANDO':'EVIDENCIA PARCIAL'):'SIN EVIDENCIA');
    const decisions=[];
    for(const row of rows(reviews,12))decisions.push({engine:'Spot Bot',environment:String(status.mode||'ENTORNO SIN CONFIRMAR'),action:row.verdict,at:row.created_at,reason:row.reason,symbol:row.symbol,href:'operations-decisions',old:remoteOld||['offline','delayed'].includes(status.activity?.state)});
    for(const [symbol,row] of Object.entries(futuresForward?.last_ai_reviews||{}).slice(0,15))if(row&&typeof row==='object')decisions.push({engine:'Futures Bot',environment:'FUTURES DEMO',action:row.verdict,at:row.at,reason:row.reason,symbol,href:'futures-bot',old:remoteOld||!futuresCycleFresh(futuresForward,status)});
    if(marketPulse?.schema===1&&marketPulse.engine==='AI_MARKET_PULSE'&&marketPulse.mode==='SHADOW'&&marketPulse.execution_enabled===false)for(const row of rows(marketPulse.decisions,12))decisions.push({engine:'AI Market Pulse',environment:'SHADOW',action:row.action,at:row.at,reason:row.reason,symbol:row.symbol,href:'pulse-decisions',old:remoteOld||marketPulse.remote_sync_stale===true||marketPulse.freshness?.state!=='FRESH'||FourEnginePortal.isOld(marketPulse.at,false)});
    const q=platform?.quant;
    if(q?.schema===1&&q.engine==='QUANT_ARBITRAGE'&&q.mode==='SHADOW'&&q.execution_enabled===false&&q.promotion_allowed===false)for(const row of rows(q.decisions,12))decisions.push({engine:'Quant Arbitrage',environment:'SHADOW',action:row.action,at:row.at,reason:row.reason,symbol:row.instrument,href:'quant-decisions',old:FourEnginePortal.quantStale(q,remoteOld)});
    const recent=decisions.filter(row=>stamp(row.at)&&Date.parse(row.at)<=Date.now()+5000).sort((a,b)=>Date.parse(b.at)-Date.parse(a.at)).slice(0,6);
    set('commandDecisionState',recent.length?`${recent.length} ÚLTIMOS REGISTROS DISPONIBLES`:'SIN REGISTROS DISPONIBLES');
    set('commandDecisionAt',recent.length?`Último registro ${time(recent[0].at)} · no implica nueva ejecución`:'La ausencia de decisiones no demuestra un fallo');
    html('commandDecisions',recent.map(row=>`<article class="command-record"><div><span class="command-record-source">${esc(row.engine)} · ${esc(short(row.environment))}${row.old?' · fuente antigua':''}</span><strong>${esc(short(row.action||'Decisión sin clasificar'))} · ${esc(short(row.symbol||'Activo sin identificar'))}</strong><p>${esc(short(row.reason))}</p></div><time>${esc(time(row.at))}</time><a class="command-link" href="#${row.href}">Ver evidencia →</a></article>`).join('')||'<p class="empty">Sin decisiones con hora verificable en esta lectura. La inactividad puede ser normal.</p>');
    const alertNames={GROSS_LIMIT_EXCEEDED:'Límite de exposición bruta superado',OBSERVED_STOP_RISK_LIMIT_EXCEEDED:'Límite nominal hasta stop superado',PROTECTIVE_THRESHOLD_CROSSED:'Umbral protector cruzado',NATIVE_PROTECTION_UNCONFIRMED:'Protección nativa sin confirmar',SOURCE_STALE_OR_UNAVAILABLE:'Fuente antigua o no disponible',POSITION_VALUE_UNKNOWN:'Posición sin valoración',AGGREGATE_VALUE_UNKNOWN:'Valoración del entorno incompleta',INVALID_POSITION:'Registro de posición inválido',DUPLICATE_POSITION:'Registro de posición duplicado',GUARDIAN_UNAVAILABLE:'Guardian no disponible'};
    const alerts=valid?rows(g.alerts,20).slice(0,4).map(row=>({title:Object.hasOwn(alertNames,row.code)?alertNames[row.code]:short(row.code||'Observación Guardian'),detail:`${Object.hasOwn(names,row.scope)?names[row.scope]:'Plataforma'}${row.symbol?' · '+short(row.symbol):''} · ${guardianOld?'último registro antiguo':'Observer; no ejecuta acciones'}`,at:g.at})):[];
    for(const row of rows(events,20).filter(row=>['WARN','ERROR','CRITICAL'].includes(row.level)).slice(0,4))alerts.push({title:row.level,detail:short(row.message)+(remoteOld?' · último registro remoto':''),at:row.created_at});
    html('commandAlerts',alerts.slice(0,6).map(row=>`<article class="command-record"><div><strong>${esc(row.title)}</strong><p>${esc(row.detail)}</p></div><time>${esc(time(row.at))}</time></article>`).join('')||`<p class="empty">${!valid?'Guardian sin evidencia compatible; no se infiere ausencia de alertas.':guardianOld?'Sin alertas en la última proyección; situación actual sin verificar.':'Sin alertas en esta evidencia. Consulta las protecciones y frescura de cada motor.'}</p>`);
  }
  function disconnected(){
    set('commandReadingState','LECTURA NO DISPONIBLE');set('commandReadingAt','No confirma una caída de los motores. Comprueba conexión y sincronización.');
    set('commandGuardianState','SIN LECTURA ACTUAL');set('commandDecisionState','REGISTROS SIN ACTUALIZAR');set('commandDecisionAt','La actividad actual no está verificada');
    html('commandDecisions','<p class="empty">La lectura no está disponible. Consulta de nuevo para ver los registros recientes.</p>');
    html('commandAlerts','<p class="empty">Alertas actuales sin verificar; una interrupción del portal no demuestra que los motores estén detenidos.</p>');renderCapital(null);
  }
  return {init,hasViews,resolve,targetId,selectFor,navigate,restore,render,disconnected};
})();
window.CommandCenterPortal=CommandCenterPortal;

/* Shared supervised engine view. External event text is always escaped, never executable. */
const PulsePortal = (() => {
  let pendingControl=null;
  const foldIds=new Set(['spot-analysis','futures-analysis','pulse-live','pulse-news','pulse-scanner','pulse-decisions','pulse-finance','pulse-health','guardian-exposure','guardian-overlaps','guardian-quality','intelligence-scopes','intelligence-sources','intelligence-ai','intelligence-conflicts','intelligence-journal','intelligence-queries','quant-funding','quant-statistical','quant-positions','quant-decisions','quant-finance','quant-health','observation-details','comparison-details','spot-limits','futures-limits','spot-positions','futures-positions','spot-finance','futures-finance','diagnosticsPanel','research-lab','capital-lab','capital-lab-audit','research-validation','opportunity-shadow','opportunity-capital','opportunity-decisions']);
  const navIds=new Set(['platform-overview','spot-bot','futures-bot','market-pulse','portfolio-guardian','quant-arbitrage','activity-section','modelSettingsPanel',...foldIds]);
  const foldStorageKey='crypto-ai-trader.ui.folds.v1';
  let redrawQueued=false;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const html=(id,value)=>{const node=document.getElementById(id);if(node)node.innerHTML=value;};
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const n=(value,digits=2)=>finite(value)?value.toLocaleString('en-US',{maximumFractionDigits:digits}):'—';
  const cash=value=>finite(value)?`${n(value)} USDT`:'—';
  const percent=value=>finite(value)?`${value>0?'+':''}${n(value)}%`:'—';
  const time=value=>value&&Number.isFinite(Date.parse(value))?new Date(value).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'}):'—';
  const rows=(value,limit=12)=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object').slice(0,limit):[];
  const label=value=>({SHADOW:'SHADOW',PAUSED:'PAUSADO',WARMING_UP:'ACUMULANDO MUESTRAS',DEGRADED:'DATOS PARCIALES',NOT_STARTED:'SIN INICIAR',FRESH:'RECIENTE',STALE:'ANTIGUO',UNAVAILABLE:'SIN DATOS',FORWARD_ONLY:'SOLO EVIDENCIA PROSPECTIVA',positive:'POSITIVO',negative:'NEGATIVO',neutral:'NEUTRAL',uncertain:'INCIERTO',official:'ANUNCIO OFICIAL',confirmed:'REPORTE CONFIRMADO',rumor:'RUMOR',speculative:'ESPECULATIVO'})[value]||String(value||'SIN DATOS');
  const state=(id,text,warning=false)=>{const node=document.getElementById(id);if(node){node.textContent=text;node.className='state '+(warning?'warning':'neutral');}};
  const empty=message=>`<p class="empty">${esc(message)}</p>`;
  const metrics=values=>values.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const safeUrl=value=>{try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}};
  const ordered=value=>rows(value).sort((a,b)=>(Date.parse(b.received_at||b.at)||0)-(Date.parse(a.received_at||a.at)||0));
  function opportunity(row,decision=false){
    const favorable=Array.isArray(row.favorable)?row.favorable.slice(0,8):[];
    const risks=Array.isArray(row.risks)?row.risks.slice(0,8):[];
    // Frozen quantitative context is displayed as data, including strings that resemble instructions.
    const evidence=decision&&row.evidence&&typeof row.evidence==='object'?JSON.stringify(row.evidence,null,2).slice(0,16000):null;
    return `<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(row.symbol||'Activo pendiente')} · ${esc(row.action||'SIN DECISIÓN')}</strong><time>${esc(time(row.at))}</time></div><p class="pulse-evidence">Score ${esc(n(row.score,1))}/100 · confianza ${esc(finite(row.confidence)?percent(row.confidence*100):'—')}</p><p>${esc(row.reason||'Sin justificación registrada')}</p>${favorable.length?`<p><strong>Evidencia favorable:</strong> ${favorable.map(esc).join(' · ')}</p>`:''}${risks.length?`<p><strong>Factores de riesgo:</strong> ${risks.map(esc).join(' · ')}</p>`:''}${decision?`<details><summary>Información disponible al decidir</summary><p>Decisión: ${esc(time(row.at))} · ID ${esc(row.id||'—')}. Snapshot de evidencia conservado; no se añade información posterior.</p>${evidence?`<pre>${esc(evidence)}</pre>`:'<p>Evidencia detallada no disponible en esta proyección. No se reconstruye con datos posteriores.</p>'}</details>`:''}</article>`;
  }
  function render(pulse,status={},futures={},positions=[]){
    const p=pulse&&pulse.schema===1?pulse:{};
    const available=p.schema===1, perf=p.performance||{},health=p.health||{},stats=p.stats||{};
    const snapshotAge=(Date.now()-Date.parse(p.at))/1000;
    const projectionStale=p.remote_sync_stale===true||(Number.isFinite(snapshotAge)&&snapshotAge>120);
    const dataAge=finite(p.freshness?.age_seconds)?p.freshness.age_seconds+Math.max(Number.isFinite(snapshotAge)?snapshotAge:0,0):null;
    const stale=p.freshness?.state==='STALE'||projectionStale||(dataAge!==null&&dataAge>30);
    const valuation=stale?{...perf,cash:null,equity:null,net_pnl:null,return_pct:null,exposure:null}:perf;
    const freshness=available?(projectionStale?'PROYECCIÓN ANTIGUA':stale?'ANTIGUO':label(p.freshness?.state)):'SIN DATOS';
    const pulseState=available?label(p.state):'SIN DATOS';
    if(pendingControl&&((pendingControl.action==='pause'&&p.state==='PAUSED')||(pendingControl.action==='resume'&&available&&p.state!=='PAUSED'))){
      set('pulseControlMessage','Windows confirmó el estado '+pulseState.toLowerCase()+'.');pendingControl=null;
    }
    if(pendingControl&&Date.now()-pendingControl.at>90000){set('pulseControlMessage','La solicitud sigue sin confirmación de estado. Consulta Actividad antes de repetirla.');pendingControl=null;}
    state('pulseState',pulseState,stale||p.state==='DEGRADED');
    state('summaryPulseState',pulseState,stale||p.state==='DEGRADED');
    set('pulseFreshness',freshness+(finite(dataAge)?` · ${n(dataAge,0)} s`:''));
    set('pulseHealthState',freshness);
    set('pulseStatusNote',available?`${pulseState} · ${freshness.toLowerCase()} · última evaluación ${time(p.updated_at)}. ${projectionStale?'La proyección no es reciente; no demuestra que el motor se haya detenido. ':''}Ledger SHADOW independiente, sin órdenes al exchange. La falta de oportunidades puede ser una observación normal.`:'Market Pulse todavía no ha sincronizado un estado compatible. Spot y Futures conservan su operación; no se infiere un fallo por ausencia de datos.');
    const sourceRows=Object.entries(p.sources||{}).slice(0,5);
    const activeSources=sourceRows.filter(([,s])=>!['STANDBY','DISABLED'].includes(s?.state));
    const sourceReady=s=>['CONNECTED','FRESH','OK','ACTIVE','READY'].includes(s?.state);
    const standby=sourceRows.filter(([,s])=>s?.state==='STANDBY').length;
    set('summaryPulseSources',available?`${stale?'Último estado: ':''}${activeSources.filter(([,s])=>sourceReady(s)).length}/${activeSources.length} fuentes activas${standby?' · respaldo disponible':''} · ${freshness.toLowerCase()}`:'Sin estado de fuentes');
    set('summaryPulseEvents',`${n(stats.events_analyzed,0)} / ${n(stats.relevant_news,0)}`);
    set('summaryPulseOpportunities',`${n(stats.opportunities,0)} · ${n(stats.accepted,0)} / ${n(stats.rejected,0)}`);
    set('summaryPulsePositions',`${available&&Array.isArray(p.positions)?p.positions.length:'—'} / ${n(perf.closed_trades,0)}`);
    set('summaryPulseReturn',percent(valuation.return_pct));
    set('summaryPulseEvaluation',`${time(ordered(p.events)[0]?.received_at)} / ${time(p.updated_at)}`);
    for(const [id,paused] of [['pauseMarketPulse',false],['resumeMarketPulse',true]]){
      const button=document.getElementById(id);
      if(button&&!window.portalButtonBusy?.(id))button.disabled=!!pendingControl||projectionStale||!available||p.enabled!==true||p.controls_available!==true||!paperControlsAvailable()||(p.state==='PAUSED')!==paused;
    }
    html('pulseMarket',rows(p.market,15).map(m=>`<article class="pulse-market-card"><div class="pulse-item-head"><h4>${esc(m.symbol)}</h4><span class="badge">${m.fresh===true&&!projectionStale&&Number.isFinite(Date.parse(m.at))&&(Date.now()-Date.parse(m.at))/1000<=15?(m.complete===true?'RECIENTE':'MUESTRA PARCIAL'):'ANTIGUO / SIN DATOS'}</span></div><dl>${metrics([
      ['Precio',n(m.price,6)],['Cambio 1 min / 5 min',`${percent(m.change_1m_pct)} / ${percent(m.change_5m_pct)}`],['Volumen relativo / anomalía z',`${n(m.relative_volume)}× / ${n(m.anomaly_z)}`],['Momentum / aceleración',`${n(m.momentum,4)} / ${n(m.acceleration,4)}`],['Volatilidad realizada',percent(m.volatility_pct)],['Spread / profundidad',`${n(m.spread_bps)} bps / ${cash(m.depth_quote)}`],['Desequilibrio / cambio de liquidez',`${n(m.imbalance,3)} / ${percent(m.liquidity_change_pct)}`],['Observado',time(m.at)]])}</dl></article>`).join('')||empty('Esperando suficientes observaciones de mercado; las ventanas necesitan calentamiento.'));
    html('pulseNews',ordered(p.events).map(event=>{
      const url=safeUrl(event.url);
      return `<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(event.symbol||'Mercado')} · ${esc(label(event.impact))}</strong><span class="badge">${esc(label(event.kind))}</span></div><h4>${esc(event.title||'Evento sin título')}</h4><p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(event.source||new URL(url).hostname)} ↗</a>`:esc(event.source||'Fuente pendiente de verificación')} · credibilidad ${esc(finite(event.credibility)?percent(event.credibility*100):'—')}</p><dl class="pulse-times">${metrics([['Publicado',time(event.published_at)],['Recibido',time(event.received_at)],['Reacción observada',percent(event.market_reaction_pct)]])}</dl><p><strong>${esc(event.decision||'DECISIÓN PENDIENTE')}</strong> · ${esc(event.reason||'Pendiente de confirmación independiente')}</p></article>`;
    }).join('')||empty('Aún no hay noticias verificables registradas. La ausencia de noticias no es un error del motor.'));
    const providers=rows(p.news_providers,5),providerGrid=document.getElementById('pulseNewsProviders');
    if(providerGrid)providerGrid.hidden=!providers.length;
    const providerStates={READY:'DISPONIBLE',ERROR:'REVISAR FUENTE',STANDBY:'EN ESPERA',DISABLED:'DESHABILITADA'};
    set('pulseProviderSummary',providers.length?(stale?`Último estado: ${providers.filter(sourceReady).length}/${providers.length} listas · antiguo`:`${providers.filter(sourceReady).length}/${providers.length} fuentes disponibles${providers.some(provider=>provider.state==='ERROR')?' · revisión pendiente':''}`):'Publicación → recepción → decisión');
    html('pulseNewsProviders',providers.map(provider=>{
      const url=safeUrl(provider.url);
      return `<article class="pulse-source"><strong>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(provider.name||provider.id)} ↗</a>`:esc(provider.name||provider.id||'Fuente sin identificar')}</strong><span>${stale?'Último estado: ':''}${esc(providerStates[provider.state]||'SIN ESTADO')}${stale?' · ANTIGUO':''} · ${esc(({official:'OFICIAL',regulatory:'REGULATORIA',editorial:'EDITORIAL'})[provider.kind]||provider.kind||'procedencia pendiente')}</span><small>Última recepción: ${esc(time(provider.last_update))}</small>${provider.last_error?`<small>Diagnóstico: ${esc(provider.last_error)}</small>`:''}</article>`;
    }).join(''));
    const universeNode=document.getElementById('pulseUniverse');
    if(universeNode){universeNode.hidden=!p.universe;universeNode.textContent=p.universe?`Selección fijada ${time(p.universe.selected_at)} · ${p.universe.source||'fuente sin registrar'} · ${p.universe.selection||'metodología pendiente'}. La fecha identifica la selección; no implica un ranking actualizado continuamente.`:'';}
    html('pulseOpportunities',ordered(p.opportunities).map(row=>opportunity(row)).join('')||empty('Aún no hay oportunidades registradas. Esperar es una decisión válida.'));
    html('pulseDecisions',ordered(p.decisions).map(row=>opportunity(row,true)).join('')||empty('Aún no hay decisiones registradas.'));
    set('pulseFinanceQuality',available?(stale?'VALORACIÓN ANTIGUA':label(perf.data_quality)):'SIN DATOS');
    const financial=[['Capital hipotético inicial',cash(perf.initial_capital)],['Efectivo hipotético',cash(valuation.cash)],['Equity hipotético',cash(valuation.equity)],['P&L neto simulado',cash(valuation.net_pnl)],['Retorno simulado',percent(valuation.return_pct)],['Drawdown',percent(perf.drawdown_pct)],['Cierres hipotéticos',n(perf.closed_trades,0)],['Win rate',percent(perf.win_rate_pct)],['Profit factor',n(perf.profit_factor)],['Exposición hipotética',cash(valuation.exposure)],['Días observados',n(perf.observation_days)],['Costos simulados acumulados',cash(perf.costs)]];
    html('pulsePerformance',metrics(financial));
    html('pulseComparison',metrics([financial[4],financial[3],financial[5],financial[6],financial[7],financial[8],financial[9],financial[10],['Calidad / completitud',available?(stale?'Valoración antigua':label(perf.data_quality)):'Sin datos'],['Entorno / método','SHADOW · ejecución conservadora simulada']]));
    const benchmark=stale?null:perf.benchmark_buy_hold;
    const benchmarks=benchmark&&typeof benchmark==='object'?Object.entries(benchmark).filter(([symbol,value])=>/^[A-Z0-9]{2,24}USDT$/.test(symbol)&&finite(value)).slice(0,10):[];
    set('pulseBenchmark',stale?'Valoración y benchmarks actuales no disponibles: la proyección es antigua. Los conteos y costos conservados corresponden al último registro, no certifican el estado actual.':benchmarks.length?`Buy-and-hold con costos hipotéticos: ${benchmarks.map(([symbol,value])=>`${symbol} ${percent(value)}`).join(' · ')}. Efectivo: ${percent(perf.benchmark_cash_return_pct)}. Referencia descriptiva: esta proyección no contiene fechas ni muestras emparejadas que certifiquen un período comparable. Shadow, Spot Testnet y Futures Demo no son una sola cartera. Costos de API de IA excluidos del P&L de trading.`:`Efectivo: ${percent(perf.benchmark_cash_return_pct)}. Buy-and-hold: sin suficientes muestras emparejadas. Shadow, Spot Testnet y Futures Demo no son comparables como una sola cartera. Costos de API de IA excluidos del P&L de trading.`);
    html('pulsePositions',rows(p.positions).map(position=>`<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(position.symbol)} · SHADOW${stale?' · ÚLTIMO REGISTRO':''}</strong><time>${esc(time(position.opened_at))}</time></div><dl>${metrics([['Cantidad',n(position.quantity,8)],['Entrada / mark',`${n(position.entry_price,6)} / ${n(stale?null:position.mark_price,6)}`],['Stop / objetivo',`${n(position.stop,6)} / ${n(position.target,6)}`],['P&L abierto hipotético',cash(stale?null:position.unrealized_pnl)]])}</dl></article>`).join('')||empty(available?'Sin posiciones hipotéticas abiertas.':'Ledger Shadow no disponible.'));
    html('pulseSources',sourceRows.map(([key,source])=>`<article class="pulse-source"><strong>${esc(({binance_ws:'Binance WebSocket',binance_rest:'Binance REST',news:'Noticias verificables'})[key]||key)}</strong><span>${stale?'Último estado: ':''}${esc(source?.state==='STANDBY'?'RESPALDO EN ESPERA':source?.state==='READY'?'DISPONIBLE':label(source?.state))}${stale?' · ANTIGUO':''}</span><small>${esc(time(source?.last_update))}</small></article>`).join('')||empty('Sin estado de fuentes.'));
    html('pulseHealth',metrics([['Latencia de datos',finite(health.latency_ms)?`${n(health.latency_ms,0)} ms`:'—'],['Reconexiones',n(health.reconnects,0)],['Errores acumulados',n(health.errors,0)],['Mensajes WebSocket',n(health.ws_messages,0)],['Llamadas REST / noticias',`${n(health.rest_calls,0)} / ${n(health.news_calls,0)}`],['Revisiones / errores IA',`${n(health.ai_reviews,0)} / ${n(health.ai_errors,0)}`],['Cuota diaria IA · usadas / máximo',`${n(health.ai_used_today,0)} / ${n(health.ai_daily_cap,0)}`],['Intervalo mínimo IA',finite(health.ai_min_interval_seconds)?`${n(health.ai_min_interval_seconds,0)} s`:'—'],['Límites IA · salida / entrada',`${n(health.ai_max_output_tokens,0)} tokens / ${n(health.ai_max_input_bytes,0)} bytes`],['Buffer / uptime',`${n(health.buffer_seconds,0)} s / ${n(health.uptime_seconds,0)} s`],['Última evaluación',time(p.updated_at)]]));
    set('pulseLastError',health.last_error?`Último diagnóstico: ${health.last_error}`:'Sin diagnóstico de error reportado. Los fallos de sincronización remota se evalúan por separado del motor.');
    set('pulseResearch',`${label(p.research?.state)} · hipótesis ${p.research?.hypothesis_version||'pendiente'}. ${(Array.isArray(p.research?.limitations)?p.research.limitations:[]).join(' ')} Las señales se conservan con su evidencia temporal. La promoción y ejecución Testnet requieren autorización expresa; ninguna métrica las activa.`);
    renderSummary(status,futures,positions,p,projectionStale);
  }
  function renderSummary(status,futures,positions,p,projectionStale){
    const activity=status.activity||{},fPositions=rows(futures.positions,15),score=futures.scorecard||{};
    const spotState=status.killed?'PAUSADO':activityLabel(activity.state);
    state('summarySpotState',spotState,status.killed||activity.state==='delayed'||activity.state==='offline');
    set('summarySpotEnvironment',status.mode?`${String(status.mode).toUpperCase()} · cuenta Spot independiente`:'Entorno pendiente');
    for(const [key,value] of [['Capital',cash(status.equity)],['Exposure',cash(status.exposure)],['Positions',n(status.positions,0)],['Return',percent(status.return_pct)],['Evaluation',time(activity.last_cycle_at)]])set('summarySpot'+key,value);
    const native=status.native_protection?.positions;
    const spotPaper=String(status.mode||'').toUpperCase()==='PAPER';
    set('summarySpotProtection',spotPaper?(status.positions===0?'Sin exposición · stops simulados PAPER':'Stops simulados · PAPER'):native?(positions.length?`${positions.filter(pos=>native[pos.symbol]?.status==='ARMED').length}/${positions.length} OCO confirmados${status.killed?' · entradas pausadas':''}`:'Sin exposición · verificación al abrir'):'Confirmación nativa pendiente');
    const fEnabled=futures.enabled===true;
    const fState=futures.enabled==null?'SIN ESTADO':!fEnabled?'NO OPERATIVO':futures.killed?'PAUSADO':futures.cycle_diagnostic&&!futuresCycleFresh(futures,status)?'SIN ANÁLISIS RECIENTE':futures.cycle_diagnostic?.state==='ATTENTION'?'DATOS PARCIALES':fPositions.length?'CON POSICIONES':'ESPERANDO SEÑAL';
    state('summaryFuturesState',fState,futures.killed||fState==='SIN ANÁLISIS RECIENTE'||fState==='DATOS PARCIALES');
    const last=rows(futures.equity,120).at(-1),budget=futures.portfolio_budget||{};
    set('summaryFuturesCapital',last?cash(futuresEquityValue(last)):'—');
    set('summaryFuturesExposure',`${cash(budget.notional_usdt)} / ${cash(budget.stop_loss_usdt)}`);
    const leverages=[...new Set(fPositions.map(pos=>finite(pos.leverage)?pos.leverage+'x':'—'))];
    set('summaryFuturesPositions',Array.isArray(futures.positions)?`${fPositions.filter(pos=>pos.direction==='LONG').length} / ${fPositions.filter(pos=>pos.direction==='SHORT').length}${leverages.length?' · '+leverages.join(', '):''}`:'—');
    set('summaryFuturesReturn',percent(score.account_return_pct));set('summaryFuturesEvaluation',time(futures.cycle_diagnostic?.at));
    const fNative=futures.native_protection?.positions;
    set('summaryFuturesProtection',`${fNative?(fPositions.length?fPositions.filter(pos=>fNative[pos.symbol]?.status==='ARMED').length+'/'+fPositions.length+' stops confirmados':'Sin exposición · verificación al abrir'):'Confirmación nativa pendiente'} · ${n(score.consecutive_errors,0)} errores activos`);
    const alerts=[];
    if(['offline','delayed'].includes(activity.state))alerts.push('Spot: '+spotState.toLowerCase());
    if(['SIN ANÁLISIS RECIENTE','DATOS PARCIALES'].includes(fState))alerts.push('Futures: '+fState.toLowerCase());
    if(p.freshness?.state==='STALE'||p.state==='DEGRADED')alerts.push('Market Pulse: '+label(p.state).toLowerCase()+' · '+label(p.freshness?.state).toLowerCase());
    if(projectionStale)alerts.push('Market Pulse: proyección antigua; operación actual sin verificar');
    if(p.schema!==1)alerts.push('Market Pulse: todavía sin estado compatible');
    set('platformAlerts',alerts.length?alerts.join(' · '):'Sin alertas operativas reportadas en esta lectura. La ausencia de operaciones puede ser normal.');
    set('spotComparisonExposure',cash(status.exposure));set('spotComparisonQuality',status.observation_health?.state||'Sin cobertura reportada');
    set('futuresComparisonExposure',cash(budget.notional_usdt));set('futuresComparisonQuality',futures.observation_health?.state||'Sin cobertura reportada');
  }
  function renderResearch(observation){
    const block=document.getElementById('researchMarketPulse');if(!block)return;
    const valid=observation&&observation.engine==='AI_MARKET_PULSE'&&observation.mode==='SHADOW';
    block.hidden=!valid;
    if(!valid){for(const id of ['researchPulseObservation','researchPulseReplay','researchPulseLimitations'])set(id,'');return;}
    set('researchPulseState','EVIDENCIA PROSPECTIVA');
    set('researchPulseObservation',`${n(observation.decisions,0)} decisiones · ${n(observation.events,0)} eventos · ${n(observation.closed_trades,0)} cierres hipotéticos · ${n(observation.observation_days,2)} días. Hipótesis ${observation.hypothesis_version||'pendiente'} · capturado ${time(observation.captured_at)}.`);
    const replay=observation.replay;
    set('researchPulseReplay',replay?`Replay de evidencia congelada: ${n(replay.checked,0)} decisiones comprobadas · ${n(replay.mismatches,0)} divergencias · ${n(replay.invalid_timestamps,0)} timestamps inválidos. Reproducir un score no valida rentabilidad fuera de muestra.`:'Replay de evidencia congelada: sin auditoría disponible en este informe.');
    set('researchPulseLimitations',`Backtest histórico válido: no acreditado. Validación fuera de muestra: pendiente. Promoción automática bloqueada. ${(Array.isArray(observation.limitations)?observation.limitations.filter(item=>typeof item==='string').slice(0,6):[]).join(' ')}`);
  }
  function disconnected(){
    for(const name of ['Spot','Futures','Pulse'])state('summary'+name+'State','LECTURA NO DISPONIBLE',true);
    set('platformAlerts','El portal no pudo actualizar esta lectura. Los valores anteriores son históricos; esto no demuestra que los motores se hayan detenido.');
    for(const id of ['pauseMarketPulse','resumeMarketPulse']){const button=document.getElementById(id);if(button)button.disabled=true;}
  }
  function redrawVisibleCharts(){
    if(redrawQueued||!lastPortalChartData)return;
    redrawQueued=true;
    const schedule=window.requestAnimationFrame||((callback)=>setTimeout(callback,0));
    schedule(()=>{
      redrawQueued=false;
      const spot=document.getElementById('equityChart'),futures=document.getElementById('futuresEquityChart'),research=document.getElementById('researchCurve');
      if(spot?.clientWidth>0)renderChart(lastPortalChartData.spot);
      if(futures?.clientWidth>0)renderFuturesChart(lastPortalChartData.futures);
      if(research?.clientWidth>0&&lastResearchReport)renderResearchCurve();
    });
  }
  function restoreFolds(){
    const folds=[...document.querySelectorAll('details[data-remember-fold]')].filter(node=>foldIds.has(node.id));
    let saved={};
    try{const raw=window.localStorage?.getItem(foldStorageKey);if(typeof raw==='string'&&raw.length<=4096){const parsed=JSON.parse(raw);if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed))saved=parsed;}}catch{}
    const persist=()=>{const values={};for(const node of folds)values[node.id]=node.open===true;try{window.localStorage?.setItem(foldStorageKey,JSON.stringify(values));}catch{}};
    for(const node of folds){
      if(typeof saved[node.id]==='boolean')node.open=saved[node.id];
      node.addEventListener('toggle',()=>{persist();if(node.open)redrawVisibleCharts();});
    }
  }
  function revealSection(id,scroll=true){
    const workspaces=CommandCenterPortal.hasViews();
    if(!navIds.has(id)&&!(workspaces&&CommandCenterPortal.resolve(id)))return false;
    if(workspaces&&!CommandCenterPortal.selectFor(id))return false;
    const target=document.getElementById(CommandCenterPortal.targetId(id));if(!target)return false;
    target.hidden=false;
    for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
    if(target.dataset?.navFold&&foldIds.has(target.dataset.navFold)){const fold=document.getElementById(target.dataset.navFold);if(fold)fold.open=true;}
    if(!workspaces&&id==='activity-section'){const diagnostics=document.getElementById('diagnosticsPanel');if(diagnostics)diagnostics.open=true;}
    if(scroll)target.scrollIntoView({behavior:motionReduced()?'auto':'smooth',block:'start'});
    if(!workspaces)for(const item of document.querySelectorAll('.platform-nav a')){if(item.getAttribute('href')==='#'+id)item.setAttribute('aria-current','location');else item.removeAttribute('aria-current');}
    redrawVisibleCharts();return true;
  }
  function revealHash(){if(CommandCenterPortal.hasViews()){CommandCenterPortal.restore();return;}try{const shell=document.querySelector('.shell');revealSection(decodeURIComponent(location.hash.slice(1)),shell?.hidden!==true);}catch{}}
  async function onPortalReady(){
    await refresh();
    const shell=document.querySelector('.shell');
    if(shell&&!shell.hidden)revealHash();
  }
  function init(){
    restoreFolds();
    if(!CommandCenterPortal.hasViews())for(const link of document.querySelectorAll('.platform-nav a,.platform-detail,.pulse-subnav a'))link.addEventListener('click',event=>{
      const id=link.getAttribute('href')?.slice(1);if(!navIds.has(id))return;
      event.preventDefault();if(revealSection(id))history.replaceState({},'',`${location.pathname}${location.search||''}#${id}`);
    });
    if(!CommandCenterPortal.hasViews()){window.addEventListener('hashchange',revealHash);revealHash();}
    for(const [id,action] of [['pauseMarketPulse','pause'],['resumeMarketPulse','resume']]){
      const button=document.getElementById(id);if(!button)continue;
      button.addEventListener('click',async()=>{
        if(button.disabled||button.dataset.pending==='true')return;
        pendingControl={action,at:Date.now()};button.dataset.pending='true';button.disabled=true;
        const sibling=document.getElementById(action==='pause'?'resumeMarketPulse':'pauseMarketPulse');if(sibling)sibling.disabled=true;
        set('pulseControlMessage','Enviando solicitud al supervisor…');
        try{const result=await api('/api/market-pulse/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          set('pulseControlMessage',result.status==='pending'?'Solicitud recibida; pendiente de confirmación de Windows. El estado se mostrará cuando el motor sincronice.':'Solicitud procesada por Windows. Consultando el estado del motor…');await refresh();
        }catch(error){pendingControl=null;set('pulseControlMessage','No se confirmó el cambio: '+error.message);await refresh();}
        finally{delete button.dataset.pending;}
      });
    }
  }
  return {render,renderResearch,disconnected,init,safeUrl,revealSection,restoreFolds,onPortalReady,redrawVisibleCharts};
})();
window.PulsePortal=PulsePortal;

/* Optional four-engine diagnostics. It only renders allowlisted, read-only evidence. */
const FourEnginePortal = (() => {
  let quantPending=null;
  const ids=new Set(['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE']);
  const names={SPOT:'Spot',FUTURES:'Futures',AI_MARKET_PULSE:'AI Market Pulse',QUANT_ARBITRAGE:'Quant Arbitrage'};
  const labels={OBSERVING:'OBSERVER ACTIVO',PARTIAL:'OBSERVACIÓN PARCIAL',DEGRADED:'OBSERVACIÓN NO DISPONIBLE',NOT_STARTED:'SIN INICIAR',FRESH:'RECIENTE',UNKNOWN:'SIN EVIDENCIA',UNAVAILABLE:'SIN DATOS',WITHIN:'Dentro del límite observado',EXCEEDED:'Límite observado excedido',OBSERVED_WITHIN:'Estimación observada dentro del límite',OBSERVED_EXCEEDED:'Estimación observada excedida'};
  const codes={GUARDIAN_UNAVAILABLE:'Guardian no dispone de una lectura compatible',GROSS_LIMIT_EXCEEDED:'Exposición observada superior al límite',OBSERVED_STOP_RISK_LIMIT_EXCEEDED:'Estimación inclusiva observada superior al límite de stop',PROTECTIVE_THRESHOLD_CROSSED:'Precio observado atravesó el umbral protector',NATIVE_PROTECTION_UNCONFIRMED:'Protección nativa sin confirmar',POSITION_VALUE_UNKNOWN:'Valor de posición sin precio reciente',SOURCE_STALE_OR_UNAVAILABLE:'Fuente antigua o no disponible',AGGREGATE_VALUE_UNKNOWN:'Exposición completa desconocida',INVALID_POSITION:'Registro de posición no válido',DUPLICATE_POSITION:'Posición duplicada en el ledger'};
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const html=(id,value)=>{const node=document.getElementById(id);if(node)node.innerHTML=value;};
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const number=(value,digits=2)=>finite(value)?value.toLocaleString('en-US',{maximumFractionDigits:digits}):'—';
  const cash=value=>finite(value)?`${number(value)} USDT`:'—';
  const time=value=>typeof value==='string'&&Number.isFinite(Date.parse(value))?new Date(value).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'}):'—';
  const bounded=(value,max)=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object').slice(0,max):[];
  const label=value=>labels[value]||'SIN EVIDENCIA';
  const metric=values=>values.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const badge=(id,value,warning=false)=>{const node=document.getElementById(id);if(node){node.textContent=value;node.className='state '+(warning?'warning':'neutral');}};
  function isOld(value,remote=false){const stamp=Date.parse(value);return remote||!Number.isFinite(stamp)||Date.now()-stamp>120000||stamp-Date.now()>5000;}
  const short=value=>typeof value==='string'?value.slice(0,160):'—';
  const pct=value=>finite(value)?`${number(value,4)}%`:'—';
  const rate=value=>finite(value)?pct(value*100):'—';
  const strategyName=value=>({FUNDING_CARRY:'Funding Carry',STATISTICAL_ARBITRAGE:'Statistical Arbitrage'})[value]||'Estrategia sin identificar';
  const quantControlsAvailable=()=>typeof window.quantControlsAvailable==='function'?window.quantControlsAvailable()===true:['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname);
  const quantReason=value=>({COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED:'Esperar: cointegración sin validación independiente',COLLECTING_ALIGNED_HISTORY:'Acumulando historia alineada',COLLECTING_FUNDING_HISTORY:'Acumulando historial de funding',PROJECTED_CARRY_BELOW_ALL_COSTS:'Funding proyectado inferior a los costes',NO_PAIR_DISLOCATION:'Sin dislocación del par',NONPOSITIVE_OR_EXTREME_FUNDING:'Funding no positivo o extremo',SOURCE_STALE_OR_UNAVAILABLE:'Referencia antigua o no disponible',OWNER_PAUSED:'Nuevas entradas pausadas',ACCEPTED_HYPOTHETICAL_PAIR:'Par hipotético aceptado'})[value]||short(value);
  function quantStale(value,remote=false){
    const age=(Date.now()-Date.parse(value?.updated_at))/1000, snapshotAge=(Date.now()-Date.parse(value?.at))/1000;
    return remote||value?.remote_sync_stale===true||value?.freshness?.state!=='FRESH'||!finite(value?.freshness?.age_seconds)||value.freshness.age_seconds<0||value.freshness.age_seconds>90||!Number.isFinite(age)||age < -5||age>90||!Number.isFinite(snapshotAge)||snapshotAge < -5||snapshotAge>120;
  }
  function clearQuantDetails(message){
    for(const id of ['quantMarket','quantFundingSignals','quantFunding','quantStatisticalSignals','quantPositions','quantDecisions','quantJournal','quantSources'])html(id,`<p class="empty">${esc(message)}</p>`);
    html('quantPerformance',metric([['Capital / equity / P&L','—'],['Exposición / cierres','—']]));
    html('quantComparison',metric([['Estado','Sin evidencia financiera'],['Capital / P&L / exposición','—']]));
    html('quantHealth',metric([['Estado','Sin evidencia actual']]));html('quantRisk',metric([['Riesgo actual','Sin evidencia disponible']]));set('quantRiskMethod','Baseline y límites actuales sin evidencia disponible.');set('quantQuality',message);set('quantLastError','');set('quantBenchmarks','Referencias comparables no disponibles.');
  }
  function quantSignal(row,statistical,old){
    const m=row.metrics&&typeof row.metrics==='object'?row.metrics:{};
    const fields=statistical?[
      ['Z-score exploratorio',number(m.z_score,3)],['Ratio de cobertura',number(m.hedge_ratio,4)],['ADF residual exploratorio',number(m.residual_adf_lag1_t,3)],
      ['Semivida · muestras',number(m.approximate_half_life_observations,1)],['Correlación train / holdout',`${number(m.train_return_correlation,3)} / ${number(m.holdout_return_correlation,3)}`],['Cambio de media · sigma',number(m.holdout_mean_shift_sigma,3)]
    ]:[['Tasa funding observada',rate(m.observed_funding_rate)],['Funding proyectado condicional',cash(m.projected_funding_usdt)],['Neto condicional estimado',cash(m.conditional_net_estimate_usdt)],['Costes ida/vuelta · ambas piernas',cash(m.roundtrip_cost_usdt)],['Reserva basis',cash(m.basis_cost_reserve_usdt)],['Pérdida estimada bajo estrés',cash(m.estimated_stress_loss_usdt)]];
    return `<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(short(row.instrument))} · ${esc(short(row.action))}</strong><time>${esc(time(row.at))}</time></div><p>${esc(quantReason(row.reason))}${old?' · REGISTRO HISTÓRICO':''}</p><dl>${metric(fields)}</dl><p class="platform-note">${statistical?'Screen exploratorio; no valida cointegración ni habilita entradas.':'Proyección disponible en ese instante; no es funding liquidado ni ganancia garantizada.'}</p></article>`;
  }
  function renderQuant(value,remote=false){
    const identity=value?.schema===1&&value.engine==='QUANT_ARBITRAGE'&&value.mode==='SHADOW'&&value.execution_enabled===false&&value.promotion_allowed===false;
    const scaffold=identity&&value.initialized===false&&value.enabled===false&&value.controls_available===false&&['NOT_STARTED','DEGRADED'].includes(value.state);
    const initialized=identity&&value.initialized===true&&typeof value.enabled==='boolean'&&typeof value.controls_available==='boolean'&&['SHADOW','PAUSED','DEGRADED'].includes(value.state);
    const old=initialized&&quantStale(value,remote);
    const riskState=value?.risk_halt?.state;
    const text=initialized?`${value.enabled===false?'NO HABILITADO':value.state==='SHADOW'&&riskState==='HALTED'?'LÍMITE DE PÉRDIDA':value.state==='SHADOW'&&riskState==='UNKNOWN'?'VALORACIÓN PENDIENTE':({SHADOW:'SHADOW ACTIVO',PAUSED:'ENTRADAS PAUSADAS',DEGRADED:'DATOS PARCIALES'})[value.state]}${old?' · ANTIGUO':''}`:scaffold?(value.state==='NOT_STARTED'?'SIN INICIAR':'LEDGER NO DISPONIBLE'):'SIN DATOS';
    badge('summaryQuantState',text,old||value?.state==='DEGRADED'||riskState==='HALTED'||riskState==='UNKNOWN');badge('quantState',text,old||value?.state==='DEGRADED'||riskState==='HALTED'||riskState==='UNKNOWN');
    if(quantPending&&initialized&&!old&&((quantPending.action==='pause'&&value.state==='PAUSED')||(quantPending.action==='resume'&&value.state!=='PAUSED'))){set('quantControlMessage','Windows confirmó el estado '+text.toLowerCase()+'.');quantPending=null;}
    if(quantPending&&Date.now()-quantPending.at>90000){set('quantControlMessage','La solicitud aún no tiene confirmación reciente. Consulta Actividad antes de repetirla.');quantPending=null;}
    for(const [id,action] of [['pauseQuant','pause'],['resumeQuant','resume']]){const button=document.getElementById(id);if(button)button.disabled=!initialized||old||value.enabled!==true||value.controls_available!==true||!paperControlsAvailable()||!quantControlsAvailable()||!!quantPending||(action==='pause'?value.state==='PAUSED':value.state!=='PAUSED');}
    if(!initialized){
      for(const field of ['Capital','Positions','Return','Evaluation'])set('summaryQuant'+field,'—');
      const message=scaffold&&value.state==='NOT_STARTED'?'Quant aún no tiene un motor ni ledger inicializado. Capital, posiciones y resultados no disponibles.':scaffold?'El ledger Shadow no está disponible; no se reconstruye un capital ficticio.':'No hay un contrato Quant compatible. Su ausencia no modifica la operación de Spot, Futures o Market Pulse.';
      set('quantStatusNote',`${remote?'Última identidad sincronizada: ':''}${message}`);clearQuantDetails(message);
      for(const id of ['quantFundingState','quantStatisticalState'])set(id,scaffold&&value.state==='NOT_STARTED'?'SIN INICIAR':'SIN DATOS');
      return;
    }
    const perf=value.performance||{}, positions=bounded(value.positions,2), financial=old?{...perf,equity:null,cash:null,collateral_usdt:null,net_pnl:null,return_pct:null,gross_exposure_usdt:null}:perf;
    set('summaryQuantCapital',cash(financial.equity));set('summaryQuantReturn',cash(financial.net_pnl));
    set('summaryQuantPositions',Array.isArray(value.positions)?`${positions.length} pares / ${number(perf.closed_trades,0)} cierres${old?' · último registro':''}`:'—');set('summaryQuantEvaluation',time(value.last_evaluation));
    set('quantStatusNote',`${text} · ${old?'proyección o mercado antiguos; operación actual sin verificar':'última evaluación '+time(value.last_evaluation)}. Ledger virtual independiente. Todas las piernas, cierres y asientos de funding son hipotéticos; ninguna orden llega al exchange.`);
    const strategies=bounded(value?.strategies,2);
    for(const [id,identifier,statistical] of [['quantFundingState','FUNDING_CARRY',false],['quantStatisticalState','STATISTICAL_ARBITRAGE',true]]){
      const strategy=strategies.find(row=>row.id===identifier);
      set(id,strategy?(statistical?'SCREEN · ENTRADAS BLOQUEADAS':old?'ÚLTIMO REGISTRO':strategy.state==='OBSERVING'?'OBSERVANDO':'SIN DATOS'):'SIN DATOS');
      const signals=bounded(strategy?.signals,6);
      html(statistical?'quantStatisticalSignals':'quantFundingSignals',signals.map(row=>quantSignal(row,statistical,old)).join('')||'<p class="empty">Todavía no hay señales registradas. Esperar es una decisión válida.</p>');
    }
    html('quantMarket',bounded(value.market,3).map(row=>{
      const current=!old&&row.state==='FRESH'&&!quantStale({...value,updated_at:row.at},false)&&!quantStale({...value,updated_at:row.received_at},false);
      return `<article class="guardian-scope"><div class="pulse-item-head"><h3>${esc(short(row.symbol))}</h3><span class="badge">${current?'RECIENTE':'ANTIGUO / SIN DATOS'}</span></div><dl>${metric([['Spot / Futures de referencia',`${cash(current?row.spot_price:null)} / ${cash(current?row.futures_price:null)}`],['Basis',finite(row.basis_bps)&&current?`${number(row.basis_bps,2)} bps`:'—'],['Tasa funding observada',current?rate(row.observed_funding_rate):'—'],['Próximo evento de funding',current?time(row.next_funding_at):'—'],['Intervalo observado',current&&finite(row.funding_interval_seconds)?`${number(row.funding_interval_seconds/3600,1)} h`:'—'],['Mercado / recepción',`${time(row.at)} / ${time(row.received_at)}`]])}</dl></article>`;
    }).join('')||'<p class="empty">Sin referencias de mercado disponibles.</p>');
    html('quantFunding',bounded(value.funding,10).filter(row=>row.state==='SETTLED_SIMULATION').map(row=>`<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(short(row.symbol))} · ASIENTO SHADOW</strong><time>${esc(time(row.funding_at))}</time></div><dl>${metric([['Tasa histórica observada',rate(row.rate)],['Flujo asentado en simulación',cash(row.simulated_cashflow_usdt)],['Recibido',time(row.received_at)]])}</dl><p class="platform-note">Evento histórico observado aplicado una vez al ledger virtual; no es un ingreso real del exchange.</p></article>`).join('')||'<p class="empty">Sin asientos hipotéticos de funding registrados. Una proyección no se contabiliza como ingreso.</p>');
    html('quantPositions',positions.map(position=>`<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(short(position.instrument))} · ${esc(strategyName(position.strategy))}</strong><time>${esc(time(position.opened_at))}</time></div><p>Par SHADOW · ejecución no atómica${old?' · ÚLTIMO REGISTRO':''}</p><dl>${metric([['Exposición bruta / neta',`${cash(old?null:position.gross_exposure_usdt)} / ${cash(old?null:position.net_exposure_usdt)}`],['P&L con costes estimados de salida',cash(old||value.data_quality?.funding==='PENDING_AUTHORITATIVE_EVENTS'?null:position.net_pnl_usdt)],['Comisiones / deslizamiento de entrada',`${cash(position.entry_fees_usdt)} / ${cash(position.entry_slippage_usdt)}`],['Costes estimados de salida',cash(old?null:position.estimated_exit_cost_usdt)],['Funding asentado simulado',cash(position.funding_usdt)],['Presupuesto estimado de riesgo',cash(position.risk_budget_usdt)]])}</dl><div class="quant-leg-grid">${bounded(position.legs,2).map(leg=>{
      const slip=finite(leg.quantity)&&finite(leg.entry_price)&&finite(leg.entry_reference)?leg.quantity*Math.abs(leg.entry_price-leg.entry_reference):null;
      const legCurrent=!old&&leg.state==='FRESH'&&!quantStale({...value,updated_at:leg.priced_at},false)&&!quantStale({...value,updated_at:leg.received_at},false);
      return `<div class="quant-leg"><strong>${esc(short(leg.symbol))} · ${esc(short(leg.direction))}</strong><p>${esc(short(leg.venue))} · pierna hipotética</p><dl>${metric([['Cantidad',number(leg.quantity,8)],['Entrada / mark',`${number(leg.entry_price,6)} / ${number(legCurrent?leg.mark_price:null,6)}`],['Comisión / deslizamiento de entrada',`${cash(leg.entry_fee_usdt)} / ${cash(slip)}`],['Precio / recepción',`${time(leg.priced_at)} / ${time(leg.received_at)}`]])}</dl></div>`;
    }).join('')}</div></article>`).join('')||'<p class="empty">Sin pares hipotéticos abiertos en el último registro.</p>');
    html('quantDecisions',bounded(value.decisions,12).map(row=>`<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(strategyName(row.strategy))} · ${esc(short(row.instrument))} · ${esc(short(row.action))}</strong><time>${esc(time(row.at))}</time></div><p>${esc(quantReason(row.reason))}</p><details><summary>Evidencia disponible al decidir</summary><p>Regla ${esc(short(row.rule_version))}. Corte: ${esc(time(row.available_at_decision?.observation_cutoff))}. Muestras alineadas: ${esc(number(row.available_at_decision?.aligned_observations,0))}.</p><pre>${esc(JSON.stringify({available_at_decision:row.available_at_decision||{},metrics:row.metrics||{},qualification:row.qualification||null},null,2).slice(0,6000))}</pre><p class="platform-note">Identidad y métricas de la evidencia conservada; no se incorpora información posterior a la decisión.</p></details></article>`).join('')||'<p class="empty">Sin decisiones Quant registradas.</p>');
    const journalNames={COHORT_STARTED:'Cohorte Shadow inicializada',PAIR_OPENED_SIMULATION:'Par hipotético abierto',PAIR_CLOSED_SIMULATION:'Par hipotético cerrado',FUNDING_SETTLED_SIMULATION:'Asiento de funding simulado',PAUSE_CHANGED:'Pausa de entradas modificada',LEG_FAILURE_UNWIND_SIMULATION:'Fallo de pierna y deshacer simulado',EXIT_WAIT_FOR_FRESH_LEGS:'Cierre pendiente de precios recientes',MARGIN_STRESS_COST_SIMULATION:'Coste de estrés de margen simulado',RISK_BASELINE_OBSERVED:'Referencia de riesgo registrada',ENTRY_LOSS_HALT:'Entradas bloqueadas por pérdida'};
    html('quantJournal',bounded(value.journal,12).map(row=>`<article class="pulse-item"><div class="pulse-item-head"><strong>${esc(journalNames[row.kind]||short(row.kind))} · SHADOW</strong><time>${esc(time(row.at))}</time></div><p>${esc(short(row.reason||row.position_id||row.decision_id||row.id))}</p><dl>${metric([['Coste de estrés simulado',row.stress_costs_usdt],['Comisiones simuladas',row.fees_usdt],['Deslizamiento simulado',row.slippage_usdt]].filter(([,amount])=>finite(amount)).map(([title,amount])=>[title,cash(amount)]))}</dl></article>`).join('')||'<p class="empty">Journal no disponible en esta proyección. No se infiere ausencia de registros persistentes.</p>');
    const metrics=[['Capital virtual inicial',cash(perf.initial_capital)],['Equity virtual',cash(financial.equity)],['Efectivo virtual',cash(financial.cash)],['Colateral virtual',cash(financial.collateral_usdt)],['P&L neto simulado',cash(financial.net_pnl)],['Retorno simulado',pct(financial.return_pct)],['Exposición bruta',cash(financial.gross_exposure_usdt)],['Drawdown registrado',pct(perf.drawdown_pct)],['Cierres hipotéticos',number(perf.closed_trades,0)],['Win rate / profit factor',`${pct(perf.win_rate)} / ${number(perf.profit_factor,2)}`],['Costes simulados registrados',cash(perf.costs_usdt)],['Funding asentado simulado',cash(perf.simulated_funding_usdt)],['Días de observación',number(perf.observation_days,2)],['Coste de estrés simulado · incluido en costes',cash(perf.stress_costs_usdt)]];
    html('quantPerformance',metric(metrics));html('quantComparison',metric([metrics[5],metrics[4],metrics[7],metrics[8],metrics[9],metrics[6],metrics[12],['Calidad / metodología',old?'Valoración antigua':'Shadow · dos piernas no atómicas']]));
    const benchmarks=bounded(value.benchmarks,3).filter(row=>finite(row.buy_hold_return_pct)&&!old);
    set('quantBenchmarks',benchmarks.length?`Referencia buy-and-hold Spot bruta: ${benchmarks.map(row=>`${short(row.symbol)} ${pct(row.buy_hold_return_pct)}`).join(' · ')}. No descuenta costes ni equivale a la estrategia neta; requiere comparar períodos emparejados. Efectivo: referencia descriptiva independiente.`:'Buy-and-hold y efectivo: sin referencia reciente comparable disponible. No se reconstruye rentabilidad con datos posteriores.');
    html('quantSources',bounded(value.sources,12).map(row=>`<article class="pulse-source"><strong>${esc(short(row.id))}</strong><span>${old?'Último estado: ':''}${esc(short(row.state))}</span>${row.error?`<small>${esc(short(row.error))}</small>`:''}</article>`).join('')||'<p class="empty">Sin estado de fuentes disponible.</p>');
    const health=value.health||{};html('quantHealth',metric([['Edad del mercado',finite(value.freshness?.age_seconds)?`${number(value.freshness.age_seconds,1)} s`:'—'],['Llamadas / errores de referencia',`${number(health.calls,0)} / ${number(health.errors,0)}`],['Última evaluación',time(value.last_evaluation)],['Última recepción correcta',time(health.last_success_at)],['Intervalo de evaluación',finite(value.limits?.evaluation_interval_seconds)?`${number(value.limits.evaluation_interval_seconds,0)} s`:'—'],['Calidad de funding',value.data_quality?.funding==='PENDING_AUTHORITATIVE_EVENTS'?'Pendiente de eventos históricos verificables':value.data_quality?.funding==='COMPLETE_OBSERVED_SCHEDULE'?'Calendario observado completo':'Sin evidencia']]));
    const risk=value.risk_halt||{},riskMetrics=[['Entradas por límite de pérdida',old?'Último estado histórico':risk.state==='HALTED'?'Bloqueadas hasta reinicio del período':risk.state==='READY'?'Sin bloqueo de pérdida observado':'Bloqueadas: valoración o baseline desconocidos']];
    for(const [key,name] of [['daily','Diario'],['weekly','Semanal']]){
      const period=risk[key]||{};
      riskMetrics.push([`${name} · retorno / límite`,`${pct(old?null:period.return_pct)} / ${pct(period.limit_pct)}`],[`${name} · equity de referencia`,cash(period.baseline_equity)],[`${name} · primera muestra válida`,time(period.baseline_at)],[`${name} · próximo período UTC`,time(period.resets_at)]);
    }
    html('quantRisk',metric(riskMetrics));
    set('quantRiskMethod','La referencia es la primera equity válida observada dentro del día o semana UTC; puede empezar después de medianoche. Un bloqueo permanece hasta cambiar el período y no impide cierres protectores hipotéticos. Pausar o reanudar no cambia límites ni elimina ese bloqueo.');
    const retrospectiveBars=Array.isArray(value.limitations)&&value.limitations.includes('HISTORICAL_CLOSED_BARS_RECEIVED_DURING_OBSERVATION_NOT_FORWARD_OOS');
    set('quantQuality',`${old?'Datos antiguos. ':''}Mercado: ${short(value.data_quality?.market)}. ${retrospectiveBars?'Velas históricas cerradas recibidas durante la observación; no son evidencia prospectiva fuera de muestra. ':''}Funding pendiente puede impedir valorar equity y P&L. La salida por estrés usa colateral virtual a 1x; no reproduce la liquidación de Binance ni garantiza un fill intravela. Simulación no atómica, StatArb exploratorio sin validación independiente y promoción bloqueada.`);
    set('quantLastError',health.last_error?`Último diagnóstico: ${short(health.last_error)}`:'Sin diagnóstico de error reportado. La falta de pares puede ser una observación normal.');
  }
  function render(platform){
    const remote=platform?.remote_sync_stale===true;
    renderQuant(platform?.quant,remote);
    const g=platform?.portfolio_guardian;
    const valid=g?.schema===1&&g.engine==='PORTFOLIO_GUARDIAN'&&g.mode==='OBSERVER'&&g.controls_enabled===false&&g.can_veto===false&&g.execution_enabled===false&&['OBSERVING','PARTIAL','DEGRADED'].includes(g.state);
    const old=valid&&isOld(g.at,remote);
    set('summaryGuardianStatus',valid?`Guardian Observer: ${old?'lectura antigua':label(g.state).toLowerCase()} · sin veto de entradas.`:'Guardian Observer: sin lectura compatible · sin veto de entradas.');
    badge('guardianState',valid?(old?'OBSERVER · LECTURA ANTIGUA':label(g.state)):'SIN DATOS',old||valid&&g.state!=='OBSERVING');
    set('guardianStatusNote',valid?`Observer · ${old?'proyección antigua; estado actual sin verificar':'capturado '+time(g.at)}. Observa ledgers separados; no reserva capital, veta entradas ni cambia límites. La sincronización remota no certifica que un motor esté detenido.`:'Guardian todavía no ha sincronizado una lectura compatible. Los motores conservan sus controles y protecciones. Observer no interviene en sus decisiones.');
    const seen=new Set();
    const scopes=valid?bounded(g.scopes,4).filter(scope=>ids.has(scope.id)&&!seen.has(scope.id)&&(seen.add(scope.id),true)):[];
    html('guardianScopes',scopes.map(scope=>{
      const current=!old&&scope.state==='FRESH',capital=scope.capital||{},limits=scope.limits||{},budget=scope.budget_status||{};
      const capitalCurrent=!old&&capital.state==='FRESH';
      const assets=bounded(scope.assets,40);
      const native=assets.filter(asset=>asset.native_protection==='ARMED').length;
      const title=names[scope.id];
      return `<article class="guardian-scope"><div class="pulse-item-head"><h3>${esc(title)}</h3><span class="badge">${esc(old?'ÚLTIMO REGISTRO':label(scope.state))}</span></div><p class="platform-environment">${esc(scope.environment||'Entorno sin confirmar')} · inventario del ledger</p><dl>${metric([
        ['Posiciones / sin precio',`${number(scope.position_count,0)} / ${number(scope.unpriced_positions,0)}`],
        ['Equity / efectivo',`${cash(capitalCurrent?capital.equity_usdt:null)} / ${cash(!old?capital.cash_usdt:null)}`],
        ['Exposición bruta / neta',`${cash(current?scope.gross_usdt:null)} / ${cash(current?scope.net_usdt:null)}`],
        ['Distancia nominal a stops',cash(current?scope.nominal_stop_risk_usdt:null)],
        ['Límite bruto / riesgo inclusivo',`${cash(limits.gross_usdt)} / ${cash(limits.stop_risk_usdt)}`],
        ['Presupuesto bruto',old?'Lectura antigua':label(budget.gross)],['Presupuesto de stop inclusivo',old?'Lectura antigua':label(budget.stop_risk)],
        ['Estados nativos registrados',scope.id==='SPOT'||scope.id==='FUTURES'?`${native} ARMED / ${number(scope.position_count,0)} posiciones`:'No aplica · Shadow']
      ])}</dl><small>${esc(old?'Cantidades, límites y protecciones corresponden al último registro; no confirman el estado actual.':'El inventario del ledger no acredita conciliación completa de la cuenta. Los estados nativos registrados no son una confirmación actual independiente del exchange ni garantizan una pérdida máxima.')}</small></article>`;
    }).join('')||'<p class="empty">Sin exposición verificable disponible. No se sustituye por cero.</p>');
    const alerts=valid?bounded(g.alerts,20):[];
    set('guardianAlertSummary',valid?`${old?'Último registro: ':''}${alerts.length?`${alerts.length} alertas observadas`:'Sin alertas en la evidencia disponible'} · ${scopes.filter(scope=>scope.state==='FRESH').length}/${scopes.length} ledgers con valoración completa${old?' en esa lectura':''}. Reservas no integradas; no hay veto de entradas.`:'Sin evidencia Guardian disponible. Reservas y control de entradas no integrados.');
    html('guardianAlerts',alerts.map(alert=>`<article class="pulse-item"><strong>${esc(codes[alert.code]||'Diagnóstico no reconocido')}</strong><p>${esc(names[alert.scope]||'Plataforma')}${typeof alert.symbol==='string'?' · '+esc(alert.symbol.slice(0,24)):''} · ${old?'última lectura antigua':'observación; no ejecuta acciones'}</p></article>`).join('')||'<p class="empty">Sin alertas registradas en esta proyección.</p>');
    const overlaps=valid?bounded(g.overlaps,10):[];
    html('guardianOverlaps',overlaps.map(row=>`<article class="pulse-item"><strong>${esc(typeof row.symbol==='string'?row.symbol.slice(0,24):'Activo sin identificar')}</strong><p>${bounded(Array.isArray(row.scopes)?row.scopes.map(id=>({id})):[],4).map(item=>esc(names[item.id]||'Entorno desconocido')).join(' / ')} · coincidencia entre ledgers separados. No acredita cobertura ni capital compartido.</p></article>`).join('')||'<p class="empty">Sin coincidencias observadas; no demuestra ausencia de correlación.</p>');
    html('guardianQuality',metric([['Correlación','No calculada'],['Pérdida diaria / semanal','Sin evidencia agregada'],['Drawdown global','No calculado'],['Reservas compartidas','No integradas'],['Control de entradas','Sin veto · Observer'],['Captura',valid?time(g.at):'—']]));
    set('guardianLimitations','No existe una cartera financiera conjunta entre Spot Testnet, Futures Demo y Shadow. La distancia nominal a stop excluye costes, gaps y funding; no es una pérdida máxima. Coincidir en un activo no prueba una cobertura. Correlación, drawdown, liquidación y reservas requieren evidencia e integración adicionales.');
  }
  function disconnected(){
    set('summaryGuardianStatus','Guardian Observer: lectura no disponible · datos anteriores históricos · sin veto.');
    badge('summaryQuantState','LECTURA NO DISPONIBLE',true);badge('quantState','LECTURA NO DISPONIBLE',true);badge('guardianState','LECTURA NO DISPONIBLE',true);
    set('guardianStatusNote','El portal no pudo actualizar la lectura. Los valores conservados son históricos y no confirman el estado actual de los motores.');
    set('guardianAlertSummary','Alertas y coincidencias actuales no disponibles. Consulta una lectura reciente; no se infiere que los motores estén detenidos.');
    for(const field of ['Capital','Positions','Return','Evaluation'])set('summaryQuant'+field,'—');
    for(const id of ['quantFundingState','quantStatisticalState'])set(id,'LECTURA NO DISPONIBLE');
    set('quantStatusNote','No se pudo actualizar el contrato Quant. Su estado actual no está verificado; ejecución y promoción siguen sin controles disponibles en esta pantalla.');
    clearQuantDetails('Lectura Quant actual no disponible. Consulta una proyección reciente.');
    for(const id of ['pauseQuant','resumeQuant']){const button=document.getElementById(id);if(button)button.disabled=true;}
    html('guardianScopes','<p class="empty">Valoración actual no disponible. Consulta una lectura reciente antes de evaluar exposición.</p>');
    html('guardianAlerts','<p class="empty">Alertas actuales no disponibles.</p>');html('guardianOverlaps','<p class="empty">Coincidencias actuales no disponibles.</p>');
    html('guardianQuality',metric([['Calidad actual','Lectura no disponible'],['Control de entradas','Sin veto · Observer']]));
  }
  function init(){
    for(const [id,action] of [['pauseQuant','pause'],['resumeQuant','resume']]){
      const button=document.getElementById(id);if(!button)continue;
      button.addEventListener('click',async()=>{
        if(button.disabled||!quantControlsAvailable()||!paperControlsAvailable()||quantPending||button.dataset.pending==='true')return;
        quantPending={action,at:Date.now()};button.dataset.pending='true';
        for(const name of ['pauseQuant','resumeQuant']){const sibling=document.getElementById(name);if(sibling)sibling.disabled=true;}
        set('quantControlMessage','Enviando solicitud al supervisor…');
        try{const result=await api('/api/quant-arbitrage/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          set('quantControlMessage',result.status==='pending'?'Solicitud recibida; pendiente de confirmación de Windows.':'Solicitud procesada. Consultando confirmación del estado Shadow…');await refresh();
        }catch(error){quantPending=null;set('quantControlMessage','No se confirmó el cambio: '+error.message);await refresh();}
        finally{delete button.dataset.pending;}
      });
    }
  }
  return {render,disconnected,isOld,init,quantStale};
})();
window.FourEnginePortal=FourEnginePortal;

/* Advisory evidence only. Queries are closed local intents, never APIs or commands. */
const GuardianIntelligencePortal = (() => {
  const engines=['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'];
  const names={SPOT:'Spot Bot',FUTURES:'Futures Bot',AI_MARKET_PULSE:'AI Market Pulse',QUANT_ARBITRAGE:'Quant Arbitrage'};
  const flags=['controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'];
  const intents=['SUMMARY','REGIME','SCOPE_RISK','CONFLICTS','DATA_QUALITY','ORIGINAL_REVIEW','LIMITATIONS','COUNTERFACTUAL','EXPOSURE','LAST_DECISION','CAPITAL_BLOCKS','PERFORMANCE','WHY_NO_ENTRY'];
  const riskLabels={CAUTION:'Cautela · revisar evidencia',RISK_REDUCED:'Revisar margen de presupuesto observado',ENTRY_HALTED:'Revisar pausa o exceso observado',RECOVERY_REQUIRED:'Revisar protección y conciliación'};
  const regimeLabels={BULLISH:'Sesgo alcista observado',BEARISH:'Sesgo bajista observado',SIDEWAYS:'Movimiento lateral observado',HIGH_VOLATILITY:'Volatilidad elevada observada',LIQUIDITY_STRESS:'Estrés de liquidez observado',INSUFFICIENT_DATA:'Evidencia insuficiente'};
  const allocations={KEEP_UNASSIGNED:'Mantener sin asignación sugerida',REVIEW_PROTECTION_AND_RECONCILIATION:'Revisar protección y conciliación',REVIEW_CURRENT_BUDGET_EXCESS:'Revisar exceso de presupuesto existente',REVIEW_EXISTING_PAUSE:'Revisar la pausa original del motor',REVIEW_NO_OBSERVED_GROSS_HEADROOM:'Revisar techo bruto observado'};
  const reasons={ACCOUNT_IDENTITY_AND_FULL_ORDER_INVENTORY_UNVERIFIED:'Identidad de cuenta e inventario completo sin verificar',INCLUSIVE_GLOBAL_RISK_NOT_CERTIFIED:'Riesgo inclusivo global no certificado',INCOMPLETE_OR_UNAVAILABLE_SOURCE:'Fuente incompleta o no disponible',STALE_OR_UNPRICED_SOURCE:'Fuente antigua o sin precio verificable',PROTECTION_OR_INVENTORY_REVIEW_REQUIRED:'Protección o inventario requieren revisión',EXISTING_ENGINE_BUDGET_EXCEEDED:'Límite existente del motor excedido',ORIGINAL_ENGINE_ENTRY_PAUSE_OBSERVED:'Pausa original de entradas observada',EXISTING_GROSS_CEILING_REACHED:'Techo bruto existente alcanzado',CLOSED_BAR_WINDOW_UNAVAILABLE:'Faltan cierres contiguos disponibles en el corte',INVALID_CLOSED_BAR_EVIDENCE:'Evidencia de cierres inválida',CONFLICTING_OR_DUPLICATE_CLOSED_BAR:'Cierres duplicados o contradictorios',STALE_CLOSED_BAR_WINDOW:'Ventana de cierres antigua',NONCONTIGUOUS_CLOSED_BAR_WINDOW:'Ventana de cierres con huecos',INITIAL_DESCRIPTIVE_PROXY_ONLY:'Hipótesis descriptiva inicial sin calibrar'};
  const sourceAges={SPOT:600,FUTURES:600,AI_MARKET_PULSE:30,QUANT_ARBITRAGE:90};
  const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const number=(value,digits=2)=>finite(value)?value.toLocaleString('en-US',{maximumFractionDigits:digits}):'—';
  const stamp=value=>typeof value==='string'&&value.length<=40&&/T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
  const time=value=>stamp(value)?new Date(value).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'}):'Hora no disponible';
  const short=(value,max=180)=>typeof value==='string'?value.slice(0,max):'Sin evidencia';
  const rows=(value,max)=>Array.isArray(value)?value.filter(object).slice(0,max):[];
  const mapped=(map,key,fallback='Sin evidencia')=>typeof key==='string'&&Object.hasOwn(map,key)?map[key]:fallback;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const html=(id,value)=>{const node=document.getElementById(id);if(node)node.innerHTML=value;};
  const metrics=values=>values.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const reason=value=>mapped(reasons,value,short(value,100));
  const empty=value=>`<p class="empty">${esc(value)}</p>`;
  const authority=value=>object(value)&&value.schema===1&&value.engine==='GUARDIAN_INTELLIGENCE'&&value.mode==='SHADOW'&&value.autonomy_level===0&&flags.every(key=>value[key]===false);
  let current=null,queryEvidence={portfolio:null,opportunities:null,remote:false},initialized=false,querySerial=0,answerAssessment=null,answerSource=null;
  const queries=[];
  const asciiSize=value=>JSON.stringify(value).replace(/[\u007f-\uffff]/g,char=>'\\u'+char.charCodeAt(0).toString(16).padStart(4,'0')).length;
  const count=value=>Number.isSafeInteger(value)&&value>=0&&value<=1000000000;
  const nonnegative=value=>finite(value)&&value>=0&&value<=1e18;
  const scopeEnvironment=(engine,environment)=>({SPOT:['SPOT_TESTNET','PAPER','UNKNOWN'],FUTURES:['FUTURES_DEMO'],AI_MARKET_PULSE:['SHADOW'],QUANT_ARBITRAGE:['SHADOW']}[engine]||[]).includes(environment);
  const sourceRecent=(at,maximum)=>stamp(at)&&Date.now()-Date.parse(at)>=-5000&&Date.now()-Date.parse(at)<=maximum*1000;
  function exposureEvidence(value){
    // Validate and copy only evidence used by this query. The projection has no
    // durable record ID; its timestamp must not be attributed to another report.
    try{
      if(!object(value)||value.schema!==1||value.engine!=='PORTFOLIO_GUARDIAN'||value.mode!=='OBSERVER'
        ||['controls_enabled','can_veto','execution_enabled'].some(key=>value[key]!==false)
        ||!['OBSERVING','PARTIAL','DEGRADED'].includes(value.state)||!stamp(value.at)||asciiSize(value)>15000
        ||!Array.isArray(value.scopes)||value.scopes.length!==4||new Set(value.scopes.map(scope=>scope?.id)).size!==4)return null;
      let assets=0;
      const scopes=value.scopes.map(scope=>{
        if(!object(scope)||!engines.includes(scope.id)||scope.engine!==scope.id||!scopeEnvironment(scope.id,scope.environment)
          ||scope.inventory_scope!=='LEDGER_ONLY'||!['FRESH','PARTIAL','UNAVAILABLE','NOT_STARTED'].includes(scope.state)
          ||!(scope.position_count===null||count(scope.position_count))||!(scope.unpriced_positions===null||count(scope.unpriced_positions))
          ||!count(scope.assets_omitted)||!Array.isArray(scope.assets)||scope.assets.length>40
          ||new Set(scope.assets.map(asset=>asset?.symbol)).size!==scope.assets.length
          ||scope.position_count===null&&(scope.assets.length||scope.assets_omitted)
          ||scope.position_count!==null&&(scope.assets.length+scope.assets_omitted>scope.position_count||scope.unpriced_positions>scope.position_count))throw Error();
        const selected=scope.assets.map(asset=>{
          if(!object(asset)||typeof asset.symbol!=='string'||!/^[A-Z0-9]{2,24}USDT$/.test(asset.symbol)
            ||!['LONG','SHORT','UNKNOWN'].includes(asset.direction)||!['FRESH','UNKNOWN'].includes(asset.state)
            ||!(asset.notional_usdt===null||nonnegative(asset.notional_usdt))||!(asset.priced_at===null||stamp(asset.priced_at)))throw Error();
          return {symbol:asset.symbol,direction:asset.direction,state:asset.state,notional_usdt:asset.notional_usdt,priced_at:asset.priced_at};
        });
        assets+=selected.length;
        return {id:scope.id,environment:scope.environment,state:scope.state,position_count:scope.position_count,unpriced_positions:scope.unpriced_positions,assets_omitted:scope.assets_omitted,assets:selected};
      });
      return assets<=40?{at:value.at,scopes}:null;
    }catch{return null;}
  }
  function captureQueryEvidence(platform){
    const portfolio=exposureEvidence(platform?.portfolio_guardian);
    let opportunities=null;
    try{
      const value=platform?.opportunity_shadow;
      if(window.CryptoOpportunityContract?.validOpportunityShadow(value)===true
        &&value.recent_records.every(row=>Date.parse(row.at)<=Date.parse(value.at)&&Date.parse(row.recorded_at)<=Date.parse(value.at)))opportunities=JSON.parse(JSON.stringify(value));
    }catch{}
    queryEvidence={portfolio,opportunities,remote:platform?.remote_sync_stale===true};
  }
  function evidenceReference(source){
    if(source==='PORTFOLIO_GUARDIAN')return queryEvidence.portfolio?.at||null;
    if(source==='OPPORTUNITY_SHADOW')return queryEvidence.opportunities?.at||null;
    return null;
  }
  function validWrapper(value){
    try{return authority(value)&&['NOT_STARTED','INITIALIZED','OBSERVING','PARTIAL','STALE','DEGRADED','RETENTION_FULL','STOPPED'].includes(value.state)&&stamp(value.at)&&JSON.stringify(value).replace(/[\u007f-\uffff]/g,char=>'\\u'+char.charCodeAt(0).toString(16).padStart(4,'0')).length<=12000;}catch{return false;}
  }
  function validReport(value,wrapper){
    return authority(value)&&hash(value.assessment_id)&&object(value.policy)&&typeof value.policy.id==='string'&&value.policy.id.length<=100&&value.policy.calibrated===false
      &&stamp(value.at)&&stamp(value.captured_at)&&stamp(value.cutoff_at)&&Date.parse(value.cutoff_at)<=Date.parse(wrapper.at)+5000&&Date.parse(value.at)<=Date.parse(wrapper.at)+5000
      &&Math.abs(Date.parse(value.captured_at)-Date.parse(value.cutoff_at))<=1000&&Math.abs(Date.parse(value.cutoff_at)-Date.parse(wrapper.updated_at))<=1000
      &&['OBSERVING','PARTIAL'].includes(value.state)&&Array.isArray(value.scopes)&&value.scopes.length===4&&new Set(value.scopes.map(scope=>scope?.id)).size===4
      &&value.scopes.every(scope=>object(scope)&&engines.includes(scope.id)&&scope.authoritative===false&&scope.assessment==='WOULD_REVIEW'&&Object.hasOwn(riskLabels,scope.risk_state)&&['FRESH','UNKNOWN'].includes(scope.data_state))
      &&object(value.evidence)&&value.evidence.input_valid===true&&hash(value.evidence.source_digest);
  }
  function isOld(value,remote=false){
    const age=(Date.now()-Date.parse(value?.updated_at))/1000,projectionAge=(Date.now()-Date.parse(value?.at))/1000;
    return remote||value?.state==='STOPPED'||value?.freshness?.state!=='FRESH'||!finite(value?.freshness?.age_seconds)||value.freshness.age_seconds<0||value.freshness.age_seconds>90||!finite(age)||age < -5||age>90||!finite(projectionAge)||projectionAge < -5||projectionAge>120;
  }
  function scopeCurrent(scope,report,old){
    const age=(Date.now()-Date.parse(scope.source_at))/1000;
    return !old&&scope.data_state==='FRESH'&&scope.inventory_complete===true&&stamp(scope.source_at)&&stamp(scope.available_at)&&Date.parse(scope.source_at)<=Date.parse(report.cutoff_at)&&Date.parse(scope.available_at)<=Date.parse(report.cutoff_at)&&age>=-5&&age<=sourceAges[scope.id];
  }
  function reviewText(scope,report){
    const review=scope.latest_original_review;
    if(!object(review)||review.state!=='OBSERVED_METADATA_ONLY'||!stamp(review.at)||Date.parse(review.at)>Date.parse(report.cutoff_at)||!(scope.id==='SPOT'?['ALLOW','REJECT','REDUCE']:scope.id==='FUTURES'?['ALLOW','REJECT']:[]).includes(review.verdict))return 'Sin metadatos de revisión individual verificables en este reporte.';
    return `${review.verdict} · ${time(review.at)} · ${short(review.model,80)}${finite(review.confidence)&&review.confidence>=0&&review.confidence<=1?' · confianza declarada '+number(review.confidence*100)+'%':''}. Metadatos originales; no equivalen a una propuesta completa ni a permiso actual de ejecución.`;
  }
  function clear(message){
    for(const id of ['intelligenceScopes','intelligenceSources','intelligenceConflicts','intelligenceJournal','intelligenceAi'])html(id,empty(message));
    html('intelligenceRegimeMetrics',metrics([['Retorno / volatilidad','—'],['Cierres','—']]));set('intelligenceRegime','Sin evidencia suficiente');set('intelligenceRegimeNote','Hipótesis inicial sin calibrar; no es una señal de entrada.');
    html('intelligenceEvidence',metrics([['Assessment','Sin evidencia'],['Corte','—']]));html('intelligenceHealth',metrics([['Salud del observador','Sin lectura disponible']]));set('intelligenceQuality',message);set('intelligenceError','');
  }
  function renderAi(annotation,report,old,asOf){
    if(!object(annotation)){html('intelligenceAi',empty('Sin interpretación opcional publicada. El reporte determinista conserva su validez independiente.'));return;}
    const advisory=annotation.advisory_only===true&&annotation.controls_enabled===false&&annotation.execution_enabled===false;
    if(['COMPLETED','CACHED_HISTORICAL'].includes(annotation.state)&&advisory&&hash(annotation.assessment_id)&&object(annotation.commentary)){
      const c=annotation.commentary,postures={OBSERVE:'Observar',REVIEW_DATA:'Revisar datos',REVIEW_CONCENTRATION:'Revisar concentración',REVIEW_PROTECTION:'Revisar protección'};
      const valid=typeof c.summary==='string'&&c.summary.length<=280&&Object.hasOwn(postures,c.posture)&&Array.isArray(c.cautions)&&c.cautions.length<=4&&c.cautions.every(item=>typeof item==='string'&&item.length<=120)&&Array.isArray(c.evidence_ids)&&c.evidence_ids.length>0&&c.evidence_ids.length<=4&&c.evidence_ids.every(id=>id===annotation.assessment_id)&&stamp(annotation.at)&&Date.parse(annotation.at)<=Date.parse(asOf)+5000;
      if(!valid){html('intelligenceAi',empty('Comentario no compatible; no altera la evaluación determinista.'));return;}
      const historical=old||annotation.state==='CACHED_HISTORICAL'||annotation.assessment_id!==report.assessment_id;
      const usage=object(annotation.usage)?annotation.usage:{};
      html('intelligenceAi',`<article class="pulse-item"><div class="pulse-item-head"><strong>${historical?'COMENTARIO HISTÓRICO':'INTERPRETACIÓN OPCIONAL'} · ${esc(postures[c.posture])}</strong><time>${esc(time(annotation.at))}</time></div><p>${esc(c.summary)}</p>${c.cautions.map(item=>`<p>${esc(item)}</p>`).join('')}<dl class="intelligence-evidence">${metrics([['Modelo',short(annotation.model,80)],['Assessment original',annotation.assessment_id],['Edad de caché',finite(annotation.cache_age_seconds)?number(annotation.cache_age_seconds)+' s':'No reportada'],['Tokens entrada / salida',`${number(usage.input_tokens,0)} / ${number(usage.output_tokens,0)}`],['Tokens de caché',number(usage.cached_tokens,0)],['Coste API estimado de esa respuesta',finite(usage.estimated_cost_usd)?number(usage.estimated_cost_usd,6)+' USD':'Desconocido'],['Fecha de referencia de precios',short(usage.pricing_verified_at,10)]])}</dl><p class="platform-note">Texto no autoritativo vinculado a su assessment original; no modifica estados, tamaños o límites. Los costes estimados no son una factura ni certifican gasto completo; la falta de usage no significa coste cero.</p></article>`);return;
    }
    html('intelligenceAi',empty(`Interpretación no disponible o desactivada. ${short(annotation.reason||annotation.state,100)}. El observador no depende de ella.`));
  }
  function render(platform){
    captureQueryEvidence(platform);
    if(answerSource&&(queryEvidence.remote||answerSource.at!==evidenceReference(answerSource.name)))set('intelligenceAnswerFreshness','Respuesta anterior sobre una proyección histórica; consulta de nuevo para citar la evidencia actual.');
    const value=platform?.guardian_intelligence;
    if(!validWrapper(value)){current=null;set('intelligenceState',value?'REPORTE NO COMPATIBLE':'SIN EVIDENCIA');set('intelligenceStatus','Sin reporte Intelligence compatible. No se infiere un fallo de los motores; Observer conserva su lectura independiente.');clear('Intelligence aún no ha publicado evidencia compatible. Los valores desconocidos no se sustituyen por cero.');html('intelligenceAnswer',empty('Sin reporte actual verificable para responder. Las consultas anteriores sólo figuran en el historial local.'));return;}
    const old=isOld(value,platform?.remote_sync_stale===true),valid=validReport(value.report,value),report=valid?value.report:null;
    current=report?{wrapper:value,report,old,remote:platform?.remote_sync_stale===true}:null;
    if(answerAssessment&&(old||answerAssessment!==report?.assessment_id))set('intelligenceAnswerFreshness','Respuesta anterior sobre un assessment histórico; no representa el estado actual.');
    const labels={NOT_STARTED:'SIN INICIAR',INITIALIZED:'INICIALIZADO · SIN REPORTE',OBSERVING:'OBSERVANDO · SHADOW',PARTIAL:'EVIDENCIA PARCIAL',STALE:'LECTURA ANTIGUA',DEGRADED:'OBSERVADOR CON DIAGNÓSTICO',RETENTION_FULL:'RETENCIÓN LLENA · REVISAR CAPACIDAD',STOPPED:'OBSERVADOR DETENIDO · ÚLTIMA EVIDENCIA'};
    set('intelligenceState',value.state==='STOPPED'?labels.STOPPED:report&&old?'ÚLTIMO REPORTE HISTÓRICO':labels[value.state]);
    set('intelligenceStatus',`LEVEL 0 · ${report?`${old?'último corte histórico':'corte'} ${time(report.cutoff_at)} · captura ${time(report.captured_at)}`:'sin evaluación verificable'} · proyección ${time(value.at)}. Sin veto, reservas, ejecución ni promoción.`);
    if(!report)clear(value.state==='NOT_STARTED'?'Sin journal Intelligence inicializado. No se inventa un reporte vacío.':'No hay assessment verificable en esta lectura; consulta el diagnóstico del observador.');
    const health=value.health||{};
    html('intelligenceHealth',metrics([['Registros / máximo',`${number(health.records,0)} / ${number(health.max_records,0)}`],['Corpus comprimido / máximo',`${number(health.compressed_corpus_bytes,0)} / ${number(health.max_corpus_bytes,0)} bytes`],['Capacidad',mapped({AVAILABLE:'Disponible',WARNING:'Aviso de capacidad',FULL:'Retención llena; revisar capacidad',UNKNOWN:'Desconocida'},health.capacity_state)],['Uso de capacidad',finite(health.capacity_fraction)?number(health.capacity_fraction*100)+'%':'—'],['Heartbeat observador',time(health.heartbeat_at)],['Lease observador',mapped({ACTIVE:'Activo en esa lectura',EXPIRED:'Vencido',NONE:'Sin propietario',RELEASED:'Liberado',UNAVAILABLE:'Sin evidencia'},health.lease_state)],['Errores registrados',number(health.errors,0)],['Intentos IA hoy / límite',`${number(health.ai_calls_today,0)} / ${number(health.ai_daily_limit,0)}`]]));
    set('intelligenceError',health.last_error?`Diagnóstico del observador: ${short(health.last_error)}. No demuestra parada de los motores.`:'Sin diagnóstico de error reportado. El heartbeat del observador no certifica el estado de los motores.');
    if(!report)return;
    const regime=object(report.regime)?report.regime:{},regimeKnown=Object.hasOwn(regimeLabels,regime.state)&&regime.state!=='INSUFFICIENT_DATA';
    set('intelligenceRegime',`${old?'Último registro: ':''}${mapped(regimeLabels,regime.state,'Evidencia insuficiente')}`);
    set('intelligenceRegimeNote',`${reason(regime.reason)}. Proxy BTC Spot / 60 minutos; no interpreta todas las monedas ni habilita entradas.${old?' Estado actual desconocido.':''}`);
    html('intelligenceRegimeMetrics',metrics([['Retorno BTC 60m',!old&&regimeKnown&&finite(regime.return_pct)?number(regime.return_pct)+'%':'—'],['Volatilidad realizada 60m',!old&&regimeKnown&&finite(regime.realized_volatility_pct)?number(regime.realized_volatility_pct)+'%':'—'],['Cierres disponibles',number(regime.observation_count,0)],['Último cierre / disponibilidad',`${time(regime.last_market_at)} / ${time(regime.latest_available_at)}`]]));
    html('intelligenceScopes',engines.map(id=>{
      const scope=report.scopes.find(row=>row.id===id),fresh=scopeCurrent(scope,report,old),why=Array.isArray(scope.reasons)?scope.reasons.filter(item=>typeof item==='string').slice(0,6):[];
      return `<article class="guardian-scope"><div class="pulse-item-head"><h3>${esc(names[id])}</h3><span class="badge neutral">${old?'HISTÓRICO':fresh?'EVIDENCIA RECIENTE':'EVIDENCIA INCOMPLETA'}</span></div><p class="platform-environment">${esc(short(scope.environment,40))} · evaluación Shadow</p><h4>${esc(mapped(riskLabels,scope.risk_state))}</h4><p class="settings-help">${esc(mapped(allocations,scope.allocation))} · sin cambio aplicado por Guardian.</p><p class="settings-help">${why.map(item=>esc(reason(item))).join(' · ')}</p><dl>${metrics([['Estado del motor reportado',short(scope.reported_engine_state,40)],['Inventario en ese corte',scope.inventory_complete===true?'Completo según la captura':'Sin completitud verificable'],['Posiciones observadas',fresh?number(scope.position_count,0):'—'],['Última revisión individual',reviewText(scope,report)]])}</dl></article>`;
    }).join(''));
    html('intelligenceSources',report.scopes.map(scope=>`<article class="guardian-scope"><h3>${esc(names[scope.id])}</h3><dl>${metrics([['Fuente',short(scope.source_id,40)],['Hora del dato',time(scope.source_at)],['Disponible localmente',time(scope.available_at)],['Captura de la fuente',time(scope.captured_at)],['Calidad actual',scopeCurrent(scope,report,old)?'Reciente en esta lectura':'Actualidad no verificable'],['Evidencia',hash(scope.evidence_id)?scope.evidence_id:'Sin ID válido']])}</dl></article>`).join(''));
    const liquidity=object(regime.liquidity)?regime.liquidity:{};
    set('intelligenceQuality',`${old?'Reporte histórico. ':''}Hipótesis ${short(report.policy.id,100)} sin calibrar. Liquidez BTC: ${old?'último estado ':''}${mapped({STRESS:'estrés observado',OBSERVED:'observación disponible',UNKNOWN:'desconocida'},liquidity.state,'desconocida')}; captura ${time(liquidity.at)}. Spread y profundidad son observaciones parciales. Captura multiledger no atómica; no certifica identidad de cuenta, inventario completo del exchange ni riesgo inclusivo. Coincidencias omitidas: ${number(report.truncation?.conflicts_omitted,0)}.`);
    html('intelligenceConflicts',rows(report.conflicts,10).map(conflict=>`<article class="pulse-item"><strong>${esc(short(conflict.symbol,24))} · ${conflict.classification==='OPPOSING_CROSS_SCOPE_OBSERVATION'?'Direcciones opuestas observadas':'Coincidencia entre ámbitos'}</strong><p>${rows(conflict.members,8).filter(member=>engines.includes(member.engine)&&['LONG','SHORT','UNKNOWN'].includes(member.direction)).map(member=>esc(names[member.engine]+' '+member.direction)).join(' / ')}</p><p>${old?'Último registro histórico. ':''}Cobertura no verificada; capitales y entornos separados. Revisión sugerida sin montos ni acciones automáticas.</p></article>`).join('')||empty(old?'Sin coincidencias en la última proyección; situación actual desconocida.':'Sin coincidencias en esta evidencia. No demuestra diversificación ni ausencia de correlación.'));
    html('intelligenceEvidence',metrics([['Assessment',report.assessment_id],['Corte del reporte',time(report.cutoff_at)],['Digest de la captura',report.evidence.source_digest],['Integridad disponible','Identidad publicada; la UI no vuelve a verificar el corpus'],['Completitud previa a la orden','No es captura completa previa a envío']]));
    html('intelligenceJournal',rows(value.journal,3).filter(row=>hash(row.id)&&hash(row.report_digest)&&stamp(row.cutoff_at)&&stamp(row.committed_at)).map(row=>`<article class="pulse-item"><strong>Registro persistido${old?' · histórico':''}</strong><dl class="intelligence-evidence">${metrics([['ID',row.id],['Corte',time(row.cutoff_at)],['Asentado',time(row.committed_at)],['Digest del reporte',row.report_digest]])}</dl></article>`).join('')||empty('Sin identidad de journal incluida en esta proyección acotada. No se afirma persistencia a partir de la tarjeta.'));
    renderAi(value.ai,report,old,value.at);
  }
  function resolveIntent(question='',selected='SUMMARY',selectedScope='ALL'){
    if(typeof question!=='string'||question.length>280||!intents.includes(selected)||!['ALL',...engines].includes(selectedScope))return {state:'UNSUPPORTED',reason:'Consulta o parámetros no compatibles.'};
    const text=question.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
    if(/[\x00-\x1f]|\b(?:compra|comprar|vende|vender|ejecuta|ejecutar|ordena|ordenes|cierra|cerrar|activa|activar|cambia|cambiar|aumenta|aumentar|reduce|reducir|pausa|pausar|reanuda|reanudar|transfiere|retira|sql|insert|delete|drop|python|shell|password|token|secreto|credenciales)\b|\bselect\s|sk-[a-z0-9]|api[_ -]?key/.test(text))return {state:'UNSUPPORTED',reason:'Sólo se permiten explicaciones de lectura del reporte; no órdenes, secretos, SQL ni herramientas.'};
    const scopes=[];if(/\bspot\b/.test(text))scopes.push('SPOT');if(/future|futuro/.test(text))scopes.push('FUTURES');if(/pulse/.test(text))scopes.push('AI_MARKET_PULSE');if(/quant/.test(text))scopes.push('QUANT_ARBITRAGE');
    const choices=[];
    if(/sin ia|habria|evitad|contrafactual/.test(text))choices.push('COUNTERFACTUAL');
    else if(/por que.*(?:no\s+(?:compro|entro|opero|abrio)|rechaz)|por que.*(?:compro|entro|opero|abrio).*no/.test(text))choices.push('WHY_NO_ENTRY');
    else if(/exposicion|expuesto|expuesta|posiciones? en/.test(text))choices.push('EXPOSURE');
    else if(/capital.*(?:bloque|rechaz|insufic)|(?:bloque|rechaz).*capital|fondos.*insufic/.test(text))choices.push('CAPITAL_BLOCKS');
    else if(/ultima.*(?:decision|operacion|intencion|evaluacion)|ultimo.*(?:evento|resultado)/.test(text))choices.push('LAST_DECISION');
    else if(/rendimiento|rentabilidad|mejor.*(?:motor|estrategia)|resultado.*(?:ajustad|riesgo)/.test(text))choices.push('PERFORMANCE');
    else if(/coincid|conflict|cobertura|hedge|correlacion/.test(text))choices.push('CONFLICTS');
    else if(/revision|veredicto|revisor|modelo|que dijo la ia/.test(text))choices.push('ORIGINAL_REVIEW');
    else if(/falta|fuente|fresc|antigu|calidad|datos/.test(text))choices.push('DATA_QUALITY');
    else if(/riesgo|revisar|cautela|pausad|presupuesto/.test(text))choices.push('SCOPE_RISK');
    else if(/mercado|regimen|volatil|tendencia/.test(text))choices.push('REGIME');
    else if(/autoridad|puede|nivel|limite/.test(text))choices.push('LIMITATIONS');
    else if(/resumen|observando|observa|estado general/.test(text))choices.push('SUMMARY');
    if(text&&!choices.length)return {state:'UNSUPPORTED',reason:'No se identificó una consulta de lectura cerrada. Elige una consulta guiada o reformula.'};
    const intent=choices[0]||selected;
    if(scopes.length>1&&['SCOPE_RISK','ORIGINAL_REVIEW','WHY_NO_ENTRY'].includes(intent))return {state:'AMBIGUOUS',reason:'Selecciona un solo motor para esta consulta.'};
    const symbols=['CONFLICTS','EXPOSURE','LAST_DECISION','CAPITAL_BLOCKS','WHY_NO_ENTRY'].includes(intent)?[...new Set([...(question.match(/\b[A-Z0-9]{2,24}USDT\b/g)||[]),...[...question.matchAll(/\b(?:en|de|para|a)\s+([A-Z0-9]{2,24})\b/gi)].map(match=>match[1]).filter(value=>value===value.toUpperCase()),...(text.match(/\b(?:btc|eth|sol|bnb|xrp|ada|doge|trx|link|avax)(?:usdt)?\b/g)||[])].filter(value=>!['IA','AI','SPOT','FUTURES','PULSE','QUANT','GUARDIAN','MARKET','BOT','BOTS','LA','EL','LAS','LOS','HOY','AYER'].includes(value)).map(value=>value.toUpperCase().replace(/USDT$/,'')+'USDT'))]:[];
    if(symbols.length>1)return {state:'AMBIGUOUS',reason:'Consulta un solo activo a la vez.'};
    return {state:'SUPPORTED',intent,scope:scopes[0]||selectedScope,symbol:symbols[0]||null};
  }
  function answerObserved(resolved){
    const result={...resolved,state:'UNKNOWN',assessment_id:null,cutoff_at:null,record_id:null,source:null,source_at:null,evidence_ids:[]};
    if(resolved.intent==='PERFORMANCE')return {...result,text:'Desconocido: falta una cohorte comparable validada con el mismo período, entorno, metodología y costes. No se puede identificar la mejor estrategia ajustada por riesgo ni atribuir beneficios a IA o Guardian.'};
    if(resolved.intent==='EXPOSURE'){
      const value=queryEvidence.portfolio;
      if(!resolved.symbol)return {...result,text:'Indica un solo activo, por ejemplo «exposición a BTC». No se suman entornos ni cuentas.'};
      if(!value)return {...result,text:'Sin proyección Portfolio Guardian compatible para valorar ese activo. Exposición desconocida; no se sustituye por cero.'};
      const old=queryEvidence.remote||!sourceRecent(value.at,120);
      Object.assign(result,{source:'PORTFOLIO_GUARDIAN',source_at:value.at,cutoff_at:value.at,state:old?'HISTORICAL':'ANSWERED'});
      let incomplete=false;
      const scopes=value.scopes.filter(scope=>resolved.scope==='ALL'||scope.id===resolved.scope);
      const explanations=scopes.map(scope=>{
        const label=`${names[scope.id]} / ${scope.environment}`,asset=scope.assets.find(row=>row.symbol===resolved.symbol);
        const complete=!old&&scope.state==='FRESH'&&scope.environment!=='UNKNOWN'&&scope.assets_omitted===0&&scope.unpriced_positions===0&&count(scope.position_count)&&(scope.id==='QUANT_ARBITRAGE'||scope.assets.length===scope.position_count);
        if(!complete){incomplete=true;return `${label}: exposición actual desconocida; inventario del ledger incompleto, sin precio o antiguo.`;}
        if(!asset)return `${label}: activo sin posición publicada en el ledger de este corte; no certifica el inventario de Binance.`;
        if(asset.state!=='FRESH'||!nonnegative(asset.notional_usdt)||!sourceRecent(asset.priced_at,sourceAges[scope.id])||Date.parse(asset.priced_at)>Date.parse(value.at)){
          incomplete=true;return `${label}: posición publicada, valor actual desconocido por calidad o antigüedad del precio.`;
        }
        return `${label}: exposición bruta ${number(asset.notional_usdt,6)} USDT; dirección ${asset.direction==='UNKNOWN'?'mixta o no desglosada':asset.direction}; precio conocido ${time(asset.priced_at)}.`;
      });
      if(incomplete&&!old)result.state='UNKNOWN';
      result.text=`${resolved.symbol} · ${old?'proyección histórica, cantidades actuales desconocidas. ':''}${explanations.join(' ')} Ámbitos separados; sin suma global, neteo ni cobertura supuesta. Sólo inventario del ledger; proyección ${time(value.at)}, sin ID durable de captura publicado.`;
      return result;
    }
    const value=queryEvidence.opportunities;
    if(!value)return {...result,text:'Sin journal Opportunity Shadow compatible. Últimas decisiones y restricciones de capital no verificables en esta lectura.'};
    const old=queryEvidence.remote||value.freshness.state!=='FRESH'||value.health.worker_alive!==true||!sourceRecent(value.at,30)||!sourceRecent(value.health.heartbeat_at,20);
    Object.assign(result,{source:'OPPORTUNITY_SHADOW',source_at:value.at,cutoff_at:value.at});
    let records=value.recent_records.filter(row=>resolved.scope==='ALL'||row.engine===resolved.scope);
    if(resolved.symbol){
      const origins=new Set(records.filter(row=>row.legs.some(leg=>leg.symbol===resolved.symbol)).map(row=>row.engine+':'+row.environment+':'+row.origin_digest));
      records=records.filter(row=>origins.has(row.engine+':'+row.environment+':'+row.origin_digest));
    }
    records=records.slice().sort((a,b)=>Date.parse(b.at)-Date.parse(a.at)||Date.parse(b.recorded_at)-Date.parse(a.recorded_at)||a.id.localeCompare(b.id));
    if(resolved.intent==='CAPITAL_BLOCKS'){
      const rejected=records.filter(row=>row.kind==='ENTRY_INTENT'&&row.assessment.hypothetical_state==='REJECTED_UNVERIFIED');
      result.evidence_ids=rejected.map(row=>row.id);
      result.text=`${old?'Última proyección histórica. ':''}En ${records.length} registros recientes publicados: ${rejected.length} intenciones con hipótesis rechazadas${rejected.length?' ('+[...new Set(rejected.map(row=>row.assessment.reason))].join(', ')+')':''}. Guardian no aplica vetos ni reservas efectivas. Estos resultados simulados no acreditan órdenes nativas bloqueadas por capital. El total de bloqueos reales es desconocido; la muestra acotada no es el historial completo.`;
      return result;
    }
    const record=records[0];
    if(!record)return {...result,text:'Sin observación reciente publicada para ese ámbito o activo. La ausencia de registros en una muestra acotada no demuestra ausencia de operaciones.'};
    Object.assign(result,{state:old?'HISTORICAL':'ANSWERED',cutoff_at:record.at,record_id:record.id,evidence_ids:[record.id]});
    const stage=record.stage==='EXCHANGE_RESPONSE'?'Respuesta del exchange; FILLED no demuestra commit del ledger ni protección nativa.'
      :record.stage==='LEDGER_COMMIT'?'Commit del ledger observado; no acredita por sí solo conciliación completa o protección nativa.'
      :['FINAL_ENTRY_INTENT','HYPOTHETICAL_ENTRY_INTENT'].includes(record.stage)?'Intención de entrada observada; no equivale a una operación ejecutada.'
      :'Etapa del ciclo de vida observada; consultar la evidencia, sin inferir ejecución.';
    result.text=`${old?'Observación histórica; situación actual desconocida. ':''}${names[record.engine]} / ${record.environment} · ${record.stage} · ${record.state} · ${time(record.at)}. ${stage} Asentada ${time(record.recorded_at)}. Último registro de la muestra publicada; no necesariamente la última decisión IA o ejecución global. ID ${record.id}; origen ${record.origin_digest}. La UI valida el contrato, sin volver a verificar el corpus persistido.`;
    return result;
  }
  function answer(question='',selected='SUMMARY',selectedScope='ALL'){
    const resolved=resolveIntent(question,selected,selectedScope);
    if(resolved.state!=='SUPPORTED')return {...resolved,text:resolved.reason};
    if(['EXPOSURE','LAST_DECISION','CAPITAL_BLOCKS','PERFORMANCE'].includes(resolved.intent))return answerObserved(resolved);
    if(!current)return {...resolved,state:'UNKNOWN',text:'Sin assessment compatible disponible. No se puede responder usando datos inventados.'};
    const {report,wrapper}=current,old=isOld(wrapper,current.remote),selectedRows=report.scopes.filter(scope=>resolved.scope==='ALL'||scope.id===resolved.scope),regime=report.regime||{};
    const output={...resolved,state:old?'HISTORICAL':'ANSWERED',assessment_id:report.assessment_id,cutoff_at:report.cutoff_at,record_id:rows(wrapper.journal,3).find(row=>stamp(row.cutoff_at)&&Date.parse(row.cutoff_at)===Date.parse(report.cutoff_at)&&hash(row.id)&&row.id===report.evidence.source_digest)?.id||null};
    const texts={SUMMARY:()=>`Guardian observa cuatro ámbitos separados. ${mapped(regimeLabels,regime.state,'Régimen desconocido')}. ${selectedRows.filter(scope=>scopeCurrent(scope,report,old)).length}/${selectedRows.length} fuentes seleccionadas recientes; sin autoridad de ejecución.`,REGIME:()=>`${mapped(regimeLabels,regime.state,'Régimen desconocido')}. Proxy descriptivo BTC Spot de 60 minutos, no señal para todos los activos. ${reason(regime.reason)}.`,SCOPE_RISK:()=>selectedRows.map(scope=>`${names[scope.id]}: evaluación Shadow ${mapped(riskLabels,scope.risk_state)}. ${mapped(allocations,scope.allocation)}; no es un cambio aplicado por Guardian.`).join(' '),CONFLICTS:()=>`Coincidencias publicadas: ${rows(report.conflicts,10).length}. Son observaciones entre ámbitos separados, no una cobertura verificada. Correlación desconocida; no se calcula una cartera neta común.`,DATA_QUALITY:()=>selectedRows.map(scope=>`${names[scope.id]}: ${scopeCurrent(scope,report,old)?'fuente reciente':'actualidad desconocida'}; inventario ${scope.inventory_complete===true?'completo según esa captura':'sin completar'}; dato ${time(scope.source_at)}, disponible ${time(scope.available_at)}.`).join(' '),ORIGINAL_REVIEW:()=>selectedRows.map(scope=>`${names[scope.id]}: ${reviewText(scope,report)}`).join(' '),WHY_NO_ENTRY:()=>selectedRows.map(scope=>`${names[scope.id]}: ${reviewText(scope,report)}`).join(' ')+' Causa de la ausencia de entradas durante el día: desconocida. Una revisión puntual no acredita el historial completo ni su vínculo con el activo o la propuesta preguntados.',LIMITATIONS:()=>`LEVEL 0 · SHADOW. Sin veto, reservas, asignación, cambios de riesgo, promoción u órdenes. La revisión individual y los cierres protectores de los motores siguen independientes.`,COUNTERFACTUAL:()=>`Desconocido: no existe una cohorte contrafactual comparable validada. No se pueden estimar pérdidas evitadas ni ganancias sin IA a partir de este reporte.`};
    output.text=(old?'Último reporte histórico; estado actual sin verificar. ':'')+texts[resolved.intent]();
    if(resolved.intent==='CONFLICTS'&&resolved.symbol){
      const matches=rows(report.conflicts,10).filter(row=>row.symbol===resolved.symbol);
      output.text=(old?'Último reporte histórico. ':'')+`${resolved.symbol}: ${matches.length?matches.length+' coincidencia(s) publicadas entre '+matches.flatMap(row=>rows(row.members,8).map(member=>names[member.engine]||'Ámbito desconocido')).join(' / '):'sin coincidencias registradas en esta proyección'}. No prueba una cobertura, ausencia real de exposición ni correlación. Los registros omitidos o fuentes incompletas limitan la respuesta.`;
      if(!matches.length)output.state='UNKNOWN';
    }
    if(['COUNTERFACTUAL','WHY_NO_ENTRY'].includes(resolved.intent))output.state='UNKNOWN';
    return output;
  }
  function init(){
    if(initialized)return;const form=document.getElementById('intelligenceQueryForm');if(!form)return;initialized=true;
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const result=answer(document.getElementById('intelligenceQuestion')?.value||'',document.getElementById('intelligenceIntent')?.value||'SUMMARY',document.getElementById('intelligenceScope')?.value||'ALL');
      answerAssessment=result.assessment_id||null;
      answerSource=result.source&&result.source_at?{name:result.source,at:result.source_at}:null;
      const id='browser-'+(++querySerial),at=new Date().toISOString();
      queries.unshift({id,at,intent:result.intent||result.state,assessment:result.assessment_id||null});queries.splice(6);
      html('intelligenceAnswer',`<article class="pulse-item"><strong>Respuesta local · ${esc(mapped({ANSWERED:'EVIDENCIA DISPONIBLE',HISTORICAL:'HISTÓRICA',UNKNOWN:'DESCONOCIDO',UNSUPPORTED:'NO SOPORTADO',AMBIGUOUS:'ELEGIR ÁMBITO'},result.state))}</strong><p id="intelligenceAnswerFreshness" class="platform-note">${result.state==='HISTORICAL'?'Respuesta sobre un reporte histórico.':'Respuesta vinculada al corte citado; no se actualiza como si fuera un assessment nuevo.'}</p><p>${esc(result.text)}</p><dl class="intelligence-evidence">${metrics([['Consulta local',id],['Hora',time(at)],['Fuente',result.source||'GUARDIAN_INTELLIGENCE'],['Proyección de la fuente',time(result.source_at)],['Assessment',result.assessment_id||'No disponible para esta fuente'],['Corte',time(result.cutoff_at)],['Registro persistido vinculado',result.record_id||'No incluido en esta proyección'],['Referencias publicadas',(result.evidence_ids||[]).join(' / ')||'Sin referencias adicionales']])}</dl>${result.assessment_id?'<a class="command-link" href="#intelligence-journal">Ver identidad de la evidencia →</a>':result.source==='OPPORTUNITY_SHADOW'?'<a class="command-link" href="#opportunity-decisions">Ver observaciones publicadas →</a>':result.source==='PORTFOLIO_GUARDIAN'?'<a class="command-link" href="#guardian-exposure">Ver exposición por ámbito →</a>':''}<p class="platform-note">Historial de esta pestaña; no es auditoría durable. La respuesta conserva su fuente y corte; no se reasigna a otra captura.</p></article>`);
      html('intelligenceQueryHistory',queries.map(query=>`<p class="settings-help">${esc(query.id)} · ${esc(query.intent)} · ${esc(time(query.at))} · assessment ${esc(query.assessment||'no disponible')}</p>`).join(''));
      // Deliberately do not store raw questions, invoke APIs, tools or model calls.
    });
  }
  function disconnected(){current=null;queryEvidence={portfolio:null,opportunities:null,remote:false};set('intelligenceState','LECTURA NO DISPONIBLE');set('intelligenceStatus','La conexión del portal no confirma una parada de los motores. Observer y las protecciones mantienen sus mecanismos independientes.');clear('Sin lectura actual verificable; consulta de nuevo para obtener evidencia reciente.');html('intelligenceAnswer',empty('La respuesta anterior no representa el estado actual. Sin conexión verificable.'));}
  return {render,disconnected,init,resolveIntent,answer,isOld,validWrapper};
})();
window.GuardianIntelligencePortal=GuardianIntelligencePortal;

/* Research-only protocol evidence. No account, order, query or control API. */
const CapitalLabPortal = (() => {
  const recipes=[
    ['SIM_ATOMIC_PAIR','Reserva atómica de dos patas','RESERVED',['TWO_LEGS_ATOMIC','TWO_LEGS_PRESENT']],
    ['SIM_ACCOUNT_CONFLICT','Conflicto de activo en una cuenta simulada','RESERVED',['SAME_ACCOUNT_ASSET_REJECTED','ONE_RESERVATION']],
    ['SIM_CONCURRENT_BUDGET','Dos participantes compiten por el mismo presupuesto','RESERVED',['ONE_PARENT_BUDGET_WINNER','NO_DOUBLE_ALLOCATION']],
    ['SIM_RESTART_UNKNOWN_TTL','Reinicio y TTL conservan una intención incierta','UNKNOWN',['TTL_RELEASES_NOTHING','INTENTION_UNKNOWN']],
    ['SIM_PARTIAL_CANCEL','Cancelación parcial conserva principal y costes','RECOVERY_REQUIRED',['ONLY_UNUSED_PRINCIPAL_RELEASED','OPEN_COMMITMENT_PRESERVED','EXIT_COST_BUFFER_RETAINED']],
    ['SIM_MULTILEG_UNWIND','Fallo de una pata exige cierre simulado explícito','CLOSED',['RESIDUAL_REQUIRES_UNWIND','EXPLICIT_CLOSE_RELEASES_CAPITAL','BOTH_COSTS_BOOKED']],
    ['SIM_LOSS_SHORTFALL','Fees y pérdida confirmada no ocultan déficit','RECOVERY_REQUIRED',['NEGATIVE_EQUITY_NOT_HIDDEN','SHORTFALL_VISIBLE']]
  ];
  const checks={
    TWO_LEGS_ATOMIC:['Reserva del conjunto','money',204000000],TWO_LEGS_PRESENT:['Piernas presentes','count',2],
    SAME_ACCOUNT_ASSET_REJECTED:['Conflicto detectado','code','ACCOUNT_ASSET_ALREADY_RESERVED'],ONE_RESERVATION:['Reserva única','money',102000000],
    ONE_PARENT_BUDGET_WINNER:['Participantes aceptados','count',1],NO_DOUBLE_ALLOCATION:['Reserva sin doble asignación','money',402000000],
    TTL_RELEASES_NOTHING:['Recursos retenidos al vencer TTL','money',102000000],INTENTION_UNKNOWN:['Intención persistida','code','UNKNOWN'],
    ONLY_UNUSED_PRINCIPAL_RELEASED:['Principal no usado liberado','money',60000000],OPEN_COMMITMENT_PRESERVED:['Compromiso abierto retenido','money',40000000],
    EXIT_COST_BUFFER_RETAINED:['Buffer de salida retenido','money',1600000],RESIDUAL_REQUIRES_UNWIND:['Compromiso antes del cierre','money',100000000],
    EXPLICIT_CLOSE_RELEASES_CAPITAL:['Compromiso tras cierre explícito','money',0],BOTH_COSTS_BOOKED:['Costes registrados','money',1500000],
    NEGATIVE_EQUITY_NOT_HIDDEN:['Valor contable con pérdida','money',-204000000],SHORTFALL_VISIBLE:['Déficit registrado','money',204000000]
  };
  const books={book_equity_units:'Valor contable sintético',reserved_units:'Reservado simulado',committed_units:'Comprometido simulado',free_units_signed:'Libre con signo',available_units:'Disponible para reservas simuladas',shortfall_units:'Déficit',fees_paid_units:'Comisiones pagadas simuladas',realized_pnl_units:'P&L realizado simulado'};
  const expectedBooks=[
    [1000000000,204000000,0,796000000,796000000,0,0,0],
    [1000000000,102000000,0,898000000,898000000,0,0,0],
    [1000000000,402000000,0,598000000,598000000,0,0,0],
    [1000000000,102000000,0,898000000,898000000,0,0,0],
    [999600000,1600000,40000000,958000000,958000000,0,400000,0],
    [998000000,0,0,998000000,998000000,0,1500000,-500000],
    [-204000000,0,0,-204000000,0,204000000,4000000,-1200000000]
  ];
  const limitations=['SYNTHETIC_PROTOCOL_SCENARIOS_ONLY','NO_EXISTING_FUNDS_OR_ACCOUNT_READ','NO_ENGINE_CANDIDATE_OR_ORDER_HOOK','NOT_OWNER_FINANCIAL_AUTHORIZATION','BOOK_CAPITAL_NOT_MARKET_EQUITY_OR_GROSS_NOTIONAL','SCENARIO_VALIDATION_NOT_JOURNAL_REPLAY','NO_STATISTICAL_EDGE_OR_PROMOTION'];
  const expectedPolicy={policy_id:'SIM_CAPITAL_LAB_POLICY_V1',approved_actor:'SIM_RECIPE_AUTHOR',approved_at:1792281600,funding_source:'EXPLICIT_NEW_SIMULATION_COHORT',initial_balance_units:1000000000,total_allocated_limit_units:600000000,reserved_limit_units:600000000,committed_limit_units:600000000,stop_risk_limit_units:20000000,strategy_limits:[['SIM_SPOT',600000000,20000000],['SIM_PULSE',600000000,20000000]],balance_max_age_seconds:120,max_active_requests:10};
  const states={RESERVED:'Reservado',SUBMITTING:'Envío simulado pendiente',PARTIAL:'Parcial',FILLED:'Completado simulado',UNKNOWN:'Desconocido',CANCEL_PENDING:'Cancelación pendiente',CANCELLED:'Cancelado',CLOSED:'Cerrado',RECOVERY_REQUIRED:'Recuperación requerida',SCENARIO_ERROR:'Ensayo interrumpido'};
  const wrapperKeys=['schema','engine','mode','synthetic','execution_enabled','autonomy_level','real_account_adapter','state','at','report_id','report_digest','source_version','policy_id','policy','unit','units_per_usdt','scenarios','limitations'];
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const exact=(v,keys)=>object(v)&&Object.keys(v).length===keys.length&&keys.every(key=>Object.hasOwn(v,key));
  const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const sim=v=>typeof v==='string'&&/^SIM_[A-Za-z0-9_-]{1,80}$/.test(v);
  const equal=(a,b)=>typeof a===typeof b&&a===b;
  const money=v=>typeof v==='number'&&Number.isSafeInteger(v)&&Math.abs(v)<=9000000000000000;
  const instant=v=>typeof v==='string'&&v.length<=40&&/(Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v));
  const time=v=>instant(v)?new Date(v).toLocaleString('es-MX',{dateStyle:'short',timeStyle:'medium'}):'Hora desconocida';
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const html=(id,value)=>{const node=document.getElementById(id);if(node)node.innerHTML=value;};
  const metrics=values=>values.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  let lastReport=null;
  function formatUnits(value){
    if(value===null||value===undefined)return '— · desconocido';
    if(!money(value))return 'Contrato incompatible';
    const units=BigInt(value),absolute=units<0n?-units:units;
    return (units<0n?'−':'')+new Intl.NumberFormat('en-US').format(absolute/1000000n)+'.'+String(absolute%1000000n).padStart(6,'0')+' USDT · LAB SIM';
  }
  function checkValue(value,kind){
    if(value==='NOT_EVALUATED')return 'No evaluado';
    if(kind==='money')return formatUnits(value);
    if(kind==='count')return typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?String(value)+' · contador simulado':'Desconocido';
    return value==='ACCOUNT_ASSET_ALREADY_RESERVED'?'Activo ya reservado en la cuenta simulada':value==='UNKNOWN'?'Desconocido':'Código sin evidencia';
  }
  function conserved(book){
    if(!exact(book,Object.keys(books))||!Object.values(book).every(money)||['reserved_units','committed_units','available_units','shortfall_units','fees_paid_units'].some(key=>book[key]<0))return false;
    // Validate the producer's identities exactly; never apply new fills or
    // infer a wallet. Intermediate sums must not use binary Number rounding.
    const n=key=>BigInt(book[key]),free=n('free_units_signed');
    return n('book_equity_units')===1000000000n+n('realized_pnl_units')-n('fees_paid_units')&&n('book_equity_units')===free+n('reserved_units')+n('committed_units')&&n('available_units')===(free>0n?free:0n)&&n('shortfall_units')===(free<0n?-free:0n);
  }
  function validWrapper(value){
    try{
      if(!exact(value,wrapperKeys)||value.schema!==1||value.engine!=='CAPITAL_PROTOCOL_LAB'||value.mode!=='RESEARCH_ONLY'||value.synthetic!==true||value.autonomy_level!==0||value.execution_enabled!==false||value.real_account_adapter!==false||value.unit!=='MICRO_USDT'||value.units_per_usdt!==1000000||value.policy_id!=='SIM_CAPITAL_LAB_POLICY_V1'||!instant(value.at)||Date.parse(value.at)>Date.now()+5000||!Array.isArray(value.scenarios)||JSON.stringify(value.limitations)!==JSON.stringify(limitations))return false;
      if(JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).length>8000)return false;
      if(['NOT_RUN','UNAVAILABLE'].includes(value.state))return value.scenarios.length===0&&['report_id','report_digest','source_version','policy'].every(key=>value[key]===null);
      if(!['PASSED','FAILED'].includes(value.state)||!/^SIM_[a-f0-9]{32}$/.test(value.report_id)||!hash(value.report_digest)||value.scenarios.length!==7)return false;
      const source=value.source_version;
      if(!exact(source,['protocol','protocol_sha256','lab_sha256','recipe_version','recipe_sha256'])||source.protocol!=='CAPITAL_MANAGER_SHADOW_SIMULATION_V1'||source.recipe_version!=='capital-protocol-lab-v1'||source.recipe_sha256!=='794994c2035a4813c6985970d04ef2d1d308565af752acf74e546157de7aacc4'||!['protocol_sha256','lab_sha256','recipe_sha256'].every(key=>hash(source[key])))return false;
      const policy=value.policy;
      if(!exact(policy,Object.keys(expectedPolicy))||!Object.entries(expectedPolicy).every(([key,expected])=>key==='strategy_limits'?JSON.stringify(policy[key])===JSON.stringify(expected):equal(policy[key],expected)))return false;
      return value.scenarios.every((row,index)=>{
        const recipe=recipes[index];
        if(!exact(row,['id','label','scope','state','actual_state','expected_state','matches','conservation_matches','book','checks','record_id','record_digest'])||row.id!==recipe[0]||row.label!==recipe[1]||row.expected_state!==recipe[2]||!Object.hasOwn(states,row.actual_state)||!['PASSED','FAILED'].includes(row.state)||typeof row.matches!=='boolean'||typeof row.conservation_matches!=='boolean'||!exact(row.scope,['scenario_environment','simulated_account_id','currency'])||row.scope.scenario_environment!=='SHADOW'||row.scope.simulated_account_id!==row.id||row.scope.currency!=='USDT'||!Array.isArray(row.checks)||row.checks.length!==recipe[3].length)return false;
        if(!row.checks.every((check,i)=>exact(check,['code','actual','expected','matches'])&&check.code===recipe[3][i]&&equal(check.expected,checks[check.code][2])&&(['string','boolean'].includes(typeof check.actual)||money(check.actual))&&String(check.actual).length<=100&&typeof check.matches==='boolean'&&check.matches===equal(check.actual,check.expected)))return false;
        const conservation=conserved(row.book);
        if(row.book!==null&&!conservation||row.conservation_matches!==conservation)return false;
        const matches=row.actual_state===row.expected_state&&row.checks.every(check=>check.matches)&&row.book!==null&&Object.keys(books).every((key,i)=>row.book[key]===expectedBooks[index][i]);
        if(row.matches!==matches||(row.state==='PASSED')!==(matches&&conservation))return false;
        return row.book===null?row.actual_state==='SCENARIO_ERROR'&&row.record_id===null&&row.record_digest===null:sim(row.record_id)&&hash(row.record_digest);
      })&&(value.state==='PASSED')===value.scenarios.every(row=>row.state==='PASSED');
    }catch{return false;}
  }
  function unavailable(state,note){
    lastReport=null;set('capitalLabState',state);set('capitalLabStatus',note);html('capitalLabEvidence','');html('capitalLabCases','<p class="empty">Sin libro sintético verificable. Los importes son desconocidos; no se construye una wallet ni se consulta una cuenta.</p>');
  }
  function render(platform){
    const value=platform?.capital_lab;
    if(value===null||value===undefined){unavailable('SIN REPORTE','Laboratorio sin escenario publicado o sin proyección compatible de esta versión.');return;}
    if(!validWrapper(value)){unavailable('NO DISPONIBLE','Reporte del laboratorio incompatible. No modifica el estado de los motores ni las reservas de Guardian.');return;}
    if(value.state==='NOT_RUN'){unavailable('SIN EJECUTAR','No existe un reporte de recetas. Abrir esta sección no ejecuta el laboratorio ni crea fondos.');return;}
    if(value.state==='UNAVAILABLE'){unavailable('NO DISPONIBLE','No se puede verificar el reporte guardado del laboratorio. Los importes siguen desconocidos.');return;}
    lastReport=value;
    const historical=platform?.remote_sync_stale===true;
    set('capitalLabState',value.state==='PASSED'?'ENSAYOS CONFORMES':'ENSAYOS CON FALLOS');
    set('capitalLabStatus',`${historical?'Último reporte recibido · sincronización antigua; no se sabe si existe uno posterior. ':''}Reporte fechado ${time(value.at)} · 7 ensayos de protocolo.`);
    html('capitalLabEvidence',metrics([['Reporte LAB SIM',value.report_id],['Ejecutado el',time(value.at)],['Recetas',value.source_version.recipe_version],['Política sintética',value.policy_id],['Financiación','Nueva cohorte sintética explícita; sin fondos existentes'],['Actor de la receta · sin autorización real',value.policy.approved_actor],['Digest del reporte',value.report_digest],['Fuente de protocolo',value.source_version.protocol_sha256],['Fuente del laboratorio',value.source_version.lab_sha256],['Digest de recetas',value.source_version.recipe_sha256]]));
    const open=new Set(recipes.filter(([id])=>document.getElementById('capital-case-'+id)?.open===true).map(([id])=>id));
    html('capitalLabCases',value.scenarios.map((row,index)=>{
      const recipe=recipes[index],state=row.state==='PASSED'?'CONFORME':'FALLO DEL ENSAYO';
      const book=row.book?`<dl class="capital-lab-book">${metrics(Object.entries(books).map(([key,label])=>[label,formatUnits(row.book[key])]))}</dl>`:'<p class="empty">Libro desconocido: el ensayo se interrumpió. No se infiere saldo cero.</p>';
      return `<article class="capital-lab-case"><div class="capital-lab-case-head"><h3>${esc(recipe[1])}</h3><span class="badge neutral">LAB SIM</span></div><p class="capital-lab-result">${esc(state)} · ${historical?'último reporte recibido':'ensayo fechado'}</p><details id="capital-case-${row.id}" class="capital-lab-detail" ${open.has(row.id)?'open':''}><summary>Libro y comprobaciones · LAB SIM</summary><p class="platform-note">${esc(row.scope.simulated_account_id)} · SHADOW sintético · USDT</p><dl class="capital-lab-protocol">${metrics([['Estado observado · simulado',states[row.actual_state]],['Estado esperado · simulado',states[row.expected_state]]])}</dl>${book}<div class="capital-lab-checks">${row.checks.map(check=>`<div><strong>${esc(checks[check.code][0])}</strong><span>${check.actual==='NOT_EVALUATED'?'NO EVALUADO':check.matches?'CONFORME':'NO COINCIDE'}</span><p>Observado: ${esc(checkValue(check.actual,checks[check.code][1]))}</p><p>Esperado: ${esc(checkValue(check.expected,checks[check.code][1]))}</p></div>`).join('')}</div><dl class="capital-lab-evidence">${metrics([['Registro del escenario',row.record_id||'Sin registro verificable'],['Digest del registro',row.record_digest||'Desconocido']])}</dl><p class="platform-note">TTL o una intención incierta no autorizan liberar fondos.</p></details></article>`;
    }).join(''));
  }
  function disconnected(){
    if(lastReport){render({capital_lab:lastReport,remote_sync_stale:true});set('capitalLabStatus','Portal sin conexión · último ensayo recibido. No se sabe si existe un reporte posterior. Todos los fondos y órdenes mostrados son sintéticos.');}
    else unavailable('SIN CONEXIÓN','Sin reporte verificable recibido. La conexión del laboratorio no determina el estado de los motores.');
  }
  return {render,disconnected,validWrapper,formatUnits};
})();
window.CapitalLabPortal=CapitalLabPortal;

async function refresh() {
  try {
    const [status,positions,trades,reviews,equity,events,research,researchState,paperReport,futuresForward,marketPulse,platform] = await Promise.all([
      api('/api/status'),api('/api/positions'),api('/api/trades'),api('/api/ai-reviews'),api('/api/equity'),api('/api/events'),api('/api/research'),api('/api/research/status'),api('/api/paper-scorecard'),api('/api/futures-forward'),api('/api/market-pulse').catch(()=>null),api('/api/platform').catch(()=>null)
    ]);
    currentExecutionMode=String(status.mode||'paper').toLowerCase();
    const modeUpper=currentExecutionMode.toUpperCase();
    const forwardPositions=Array.isArray(futuresForward?.positions)?futuresForward.positions:[];
    document.getElementById('mode').textContent=modeUpper;
    const versionNode=document.getElementById('botVersion');
    if(versionNode)versionNode.textContent=/^\d+\.\d+\.\d+$/.test(String(status.installed_version||''))?'v'+status.installed_version:'v—';
    document.getElementById('executionModeChoice').value=currentExecutionMode==='testnet'?'testnet':'paper';
    const primaryState=document.getElementById('primaryEnvironmentState');
    if(primaryState)primaryState.textContent=modeUpper;
    const controlsReady=paperControlsAvailable();
    const spotSmoke=document.getElementById('testTestnetExecution');
    if(spotSmoke && !window.portalButtonBusy?.('testTestnetExecution'))
      spotSmoke.disabled=currentExecutionMode!=='testnet'||!controlsReady;
    for(const id of ['checkFuturesTestnet','testFuturesExecution','reconcileFutures']){
      const button=document.getElementById(id);
      if(button && !window.portalButtonBusy?.(id))
        button.disabled=currentExecutionMode!=='testnet'||!controlsReady;
    }
    const futuresState=document.getElementById('futuresState');
    if(futuresState){
      const futuresDisabledReason=currentExecutionMode!=='testnet'
        ? 'INACTIVO · MOTOR EN '+currentExecutionMode.toUpperCase()
        : (!futuresForward?.enabled?'INACTIVO · FORWARD DESHABILITADO':null);
      futuresState.textContent=futuresDisabledReason || (futuresForward?.killed?'PAUSADO':futuresForward?.scorecard?.risk_halt?.active?'LÍMITE DE PÉRDIDA':'ACTIVO');
      futuresState.className='state'+((futuresDisabledReason||futuresForward?.killed||futuresForward?.scorecard?.risk_halt?.active)?' warning':'');
    }
    document.getElementById('accountEnvironmentTitle').textContent='Spot · '+modeUpper;
    const spotEngineState=document.getElementById('spotEngineState');
    if(spotEngineState){
      const spotActivity=status.activity?.state||'starting';
      spotEngineState.textContent=status.killed?'PAUSADO':activityLabel(spotActivity);
      spotEngineState.className='state'+(status.killed||spotActivity==='delayed'?' warning':spotActivity==='offline'?' offline':'');
    }
    const spotPositions=document.getElementById('spotEnginePositions');
    if(spotPositions)spotPositions.textContent=String(status.positions);
    const spotExposure=document.getElementById('spotEngineExposure');
    if(spotExposure)spotExposure.textContent=money(status.exposure);

    const forwardState=document.getElementById('futuresForwardState');
    const forwardPosition=futuresForward?.position;
    if(forwardState){
      const forwardDisabledReason=currentExecutionMode!=='testnet'
        ? 'INACTIVO · MOTOR EN '+currentExecutionMode.toUpperCase()
        : (!futuresForward?.enabled?'INACTIVO · FORWARD DESHABILITADO':null);
      forwardState.textContent=forwardDisabledReason || (futuresForward.killed?'PAUSADO':futuresForward.scorecard?.risk_halt?.active?'LÍMITE DE PÉRDIDA · PROTECCIONES ACTIVAS':(forwardPositions.length?forwardPositions.length+' POSICIÓN'+(forwardPositions.length===1?' ABIERTA':'ES ABIERTAS'):'ACTIVO · ESPERANDO SEÑAL'));
      forwardState.className='state'+((forwardDisabledReason||futuresForward?.killed||futuresForward?.scorecard?.risk_halt?.active)?' warning':'');
      if(!forwardDisabledReason&&!futuresForward?.killed&&!futuresForward?.scorecard?.risk_halt?.active){
        if(futuresForward?.cycle_diagnostic&&!futuresCycleFresh(futuresForward,status)){
          forwardState.textContent='SIN ANÁLISIS RECIENTE';forwardState.className='state warning';
        }else if(futuresForward?.cycle_diagnostic?.state==='ATTENTION'){
          forwardState.textContent='ACTIVO · DATOS PARCIALES';forwardState.className='state warning';
        }
      }
    }
    const fWallet=document.getElementById('futuresForwardWallet');
    if(fWallet){
      const last=(futuresForward?.equity||[]).at(-1);
      fWallet.textContent=last?money(last.wallet_balance):'Esperando ciclo';
    }
    const fPosition=document.getElementById('futuresForwardPosition');
    if(fPosition)fPosition.textContent=forwardPositions.length?forwardPositions.map(p=>`${String(p.symbol).replace('USDT','')} ${p.direction}`).join(' · '):'SIN POSICIÓN';
    const fClosed=document.getElementById('futuresForwardClosed');
    if(fClosed){
      const score=futuresForward?.scorecard||{};
      fClosed.textContent=(score.strategy_closed_trades??'—')+' de estrategia · '+(score.technical_closed_trades??'—')+' técnicos';
    }
    const fReturn=document.getElementById('futuresForwardReturn');
    if(fReturn)fReturn.textContent=futuresForward?.scorecard?.account_return_pct==null?'—':pct(futuresForward.scorecard.account_return_pct);
    const fAi=document.getElementById('futuresForwardAi');
    if(fAi){
      const reviews=futuresForward?.last_ai_reviews||{};
      const [symbol,review]=Object.entries(reviews).filter(([,r])=>r).sort((a,b)=>(Date.parse(b[1].at)||0)-(Date.parse(a[1].at)||0))[0]||[];
      fAi.textContent=review?`${symbol.replace('USDT','')} · ${review.verdict} · ${Math.round(Number(review.confidence||0)*100)}%`:
        (status.ai_enabled?'SIN REVISIÓN':'DESACTIVADA');
    }
    const fAiModel=document.getElementById('futuresForwardAiModel');
    if(fAiModel){
      const latest=Object.values(futuresForward?.last_ai_reviews||{}).filter(Boolean).sort((a,b)=>(Date.parse(b.at)||0)-(Date.parse(a.at)||0))[0];
      fAiModel.textContent=(futuresForward?.ai_model||status.ai_model||'—')+(latest?.at?' · '+shortTime(latest.at):'');
    }
    const fRecovery=document.getElementById('futuresForwardRecovery');
    if(fRecovery){
      const rec=futuresForward?.recovery||{};
      fRecovery.textContent=rec.durable_order_journal&&rec.startup_position_reconciliation?'LISTA':'REVISAR';
    }
    const fPauseReason=document.getElementById('futuresForwardPauseReason');
    if(fPauseReason){
      const diag=futuresForward?.pause_diagnostics||{};
      if(futuresForward?.killed){
        const parts=[diag.label||'Pausa de seguridad Futures'];
        if(diag.paused_at)parts.push('desde '+shortTime(diag.paused_at));
        if(Number(diag.consecutive_errors)>0)parts.push(String(Number(diag.consecutive_errors))+' errores consecutivos (umbral de seguridad)');
        if(diag.pending_reconciliation)parts.push('conciliación pendiente');
        const incident=diag.incident;
        if(incident?.id)parts.push('incidente '+incident.id+(Number(incident.repetitions)>1?' · '+Number(incident.repetitions)+' repeticiones':''));
        const last=diag.last_error;
        if(last?.message && last.message!==diag.detail)parts.push('último error: '+last.message);
        fPauseReason.textContent='Motivo de pausa · '+parts.join(' · ');
        fPauseReason.hidden=false;
      }else{
        fPauseReason.textContent='';
        fPauseReason.hidden=true;
      }
    }
    const fSafety=document.getElementById('futuresForwardSafety');
    if(fSafety){
      const rec=futuresForward?.recovery||{};
      const symbolHealth=futuresForward?.symbol_health||{};
      const blockedRows=Object.entries(symbolHealth).filter(([,row])=>row?.status==='BLOCKED');
      const blocked=blockedRows.map(([symbol])=>symbol.replace('USDT',''));
      const blockedDetail=blockedRows.map(([symbol,row])=>symbol.replace('USDT','')+': '+String(row?.error||'bloqueado').slice(0,120)).join(' · ');
      const repair=rec.automatic_config_repair?'autorreparación config ✓':'autorreparación config —';
      const resume=rec.automatic_safe_resume?'auto-reanudación segura ✓':'auto-reanudación segura —';
      const gap=futuresForward?.evidence_gap;
      const journalRecovery=futuresForward?.last_journal_recovery;
      const recoveryText=journalRecovery?.status?' · última recuperación: '+journalRecovery.status:'';
      const gapText=gap?.status?' · evidencia marcada: '+gap.status:'';
      const nativeRows=futuresForward?.native_protection?.positions||{};
      const confirmed=Object.values(nativeRows).filter(row=>row.status==='ARMED').length;
      const nativeText=rec.native_exchange_stop_orders?`Protección nativa: ${confirmed} pares confirmados en Binance; los cierres se concilian al reconectar`:'Protección nativa pendiente de actualización';
      fSafety.textContent=`Journal ${rec.durable_order_journal?'✓':'—'} · conciliación al reiniciar ${rec.startup_position_reconciliation?'✓':'—'} · ${repair} · ${resume}${blocked.length?' · bloqueados: '+blocked.join(', ')+(blockedDetail?' ['+blockedDetail+']':''):''}${recoveryText}${gapText} · IA final: ${futuresForward?.ai_model||status.ai_model}. ${nativeText}. LIVE bloqueado.`;
    }
    const pauseForward=document.getElementById('pauseFuturesForward');
    const resumeForward=document.getElementById('resumeFuturesForward');
    if(pauseForward&&!window.portalButtonBusy?.('pauseFuturesForward'))pauseForward.disabled=!futuresForward?.enabled||!!futuresForward?.killed;
    if(resumeForward&&!window.portalButtonBusy?.('resumeFuturesForward'))resumeForward.disabled=!futuresForward?.enabled||!futuresForward?.killed;

    document.getElementById('riskPanelTitle').textContent='Límites Spot · '+modeUpper;
    document.getElementById('financialEvidenceTitle').textContent='Seguimiento financiero Spot · '+modeUpper;
    document.getElementById('equity').textContent=money(status.equity);
    document.getElementById('cash').textContent=money(status.cash);
    document.getElementById('exposure').textContent=money(status.exposure);
    document.getElementById('return').textContent=`${status.return_pct>=0?'+':''}${status.return_pct.toFixed(2)}% total`;
    document.getElementById('positionsCount').textContent=`${status.positions} de ${status.max_positions} posiciones`;
    document.getElementById('aiStatus').textContent=status.ai_enabled?'ACTIVA':'DESACTIVADA';
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
    const effectiveRisk={...risk,risk_per_trade_pct:riskSelected?Number(risk.risk_per_trade_pct)*riskSelected[1]:null};
    for(const [id,key] of [['riskTrade','risk_per_trade_pct'],['riskPosition','max_position_pct'],['riskExposure','max_total_exposure_pct'],['riskDaily','daily_loss_limit_pct'],['riskWeekly','weekly_loss_limit_pct']]){
      const value=Number(effectiveRisk[key]);
      document.getElementById(id).textContent=effectiveRisk[key]!=null&&Number.isFinite(value)?`${(value*100).toFixed(2).replace(/\.00$/,'')}%`:'—';
    }

    const state=document.getElementById('killState'), button=document.getElementById('killButton');
    state.textContent=status.killed?'PAUSADO':'PROTECCIONES ACTIVAS'; state.className=status.killed?'state killed':'state';
    button.textContent=status.killed?'Reanudar entradas Spot':'Pausar entradas Spot'; button.dataset.killed=String(status.killed);

    const activity=status.activity || {state:'starting',age_seconds:null};
    renderSpotCycle(status);
    renderFuturesCycle(futuresForward,status);
    document.getElementById('operationSummary').textContent=activity.state==='operational'?
      `Motor ${modeUpper} activo. ${status.positions} posiciones abiertas de ${status.max_positions}; ${status.killed?'nuevas entradas pausadas y protecciones vigentes':'nuevas entradas sujetas a límites y revisión IA'}. Último ciclo ${ageLabel(activity.age_seconds)}.`:
      `Motor ${activityLabel(activity.state).toLowerCase()}. ${status.killed?'Nuevas entradas pausadas. ':'Comprueba la conexión de Windows antes de dar instrucciones. '}Último ciclo ${ageLabel(activity.age_seconds)}.`;
    if(modeUpper==='TESTNET'&&status.native_protection){
      const native=status.native_protection.positions||{};
      const armed=positions.filter(p=>native[p.symbol]?.status==='ARMED').length;
      document.getElementById('operationSummary').textContent+=` Spot: ${armed}/${positions.length} posiciones con OCO confirmado. Los stops confirmados permanecen en Binance si Windows se desconecta; el trailing se actualiza mientras el bot está conectado.`;
      const residues=Object.entries(native).filter(([,row])=>Number(row.unprotected_quantity)>0).map(([symbol,row])=>symbol+': '+num(row.unprotected_quantity,8));
      if(residues.length)document.getElementById('operationSummary').textContent+=' Remanente fuera del OCO por filtros de cantidad: '+residues.join('; ')+'.';
    }
    const botState=document.getElementById('botState');
    botState.textContent=activityLabel(activity.state);
    botState.className='state'+(activity.state==='delayed'?' warning':activity.state==='offline'?' offline':'');

    lastPositions=positions;
    document.getElementById('positions').innerHTML=positions.length?positions.map(p=>`<tr><td><strong>${esc(p.symbol)}</strong></td><td>${num(p.quantity)}</td><td>${num(p.entry_price,4)}</td><td>${p.market_price==null?'—':num(p.market_price,4)}</td><td class="${p.unrealized_pnl==null?'':p.unrealized_pnl>=0?'positive':'negative'}">${p.unrealized_pnl==null?'—':`${p.unrealized_pnl>=0?'+':''}${num(p.unrealized_pnl,2)}`}</td><td class="${p.unrealized_pct==null?'':p.unrealized_pct>=0?'positive':'negative'}">${p.unrealized_pct==null?'—':`${p.unrealized_pct>=0?'+':''}${num(p.unrealized_pct,2)}%`}</td><td>${num(p.stop_price,4)}</td><td>${num(p.take_profit,4)}</td><td><button class="secondary paper-close" data-symbol="${esc(p.symbol)}" ${p.market_price==null||!paperControlsAvailable()?'disabled':''}>Cerrar</button></td></tr>`).join(''):emptyRow(9,'Sin posiciones abiertas');
    document.getElementById('trades').innerHTML=trades.length?trades.slice(0,8).map(t=>`<div class="feed-item"><strong class="${esc(t.side.toLowerCase())}">${esc(t.side)}</strong><div><strong>${esc(t.symbol)} · ${num(t.quantity)}</strong><p>${esc(t.reason)}</p></div><time>${shortTime(t.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay operaciones');
    document.getElementById('reviews').innerHTML=reviews.length?reviews.slice(0,8).map(r=>`<div class="feed-item"><strong class="${esc(r.verdict.toLowerCase())}">${esc(r.verdict)}</strong><div><strong>${esc(r.symbol)} · ${(r.confidence*100).toFixed(0)}%</strong><p>${esc(r.reason)}</p></div><time>${shortTime(r.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay revisiones');
    const important=events.filter(e=>['WARN','ERROR','CRITICAL'].includes(e.level)).slice(0,10);
    document.getElementById('events').innerHTML=important.length?important.map(e=>`<div class="feed-item"><strong class="event-${esc(e.level.toLowerCase())}">${esc(e.level)}</strong><div><p>${esc(e.message)}</p></div><time>${shortTime(e.created_at)}</time></div>`).join(''):feedEmpty('Sin errores ni advertencias recientes');
    lastPortalChartData={spot:equity,futures:futuresForward?.equity||[]};
    renderChart(equity);
    renderResearch(research,researchState);
    renderPaperEvidence(paperReport,equity,trades);
    renderDualEvidence(paperReport,futuresForward,status);
    renderFuturesParity(futuresForward);
    renderObservationHealth(status?.observation_health,futuresForward?.observation_health,futuresForward,status);
    renderFuturesChart(futuresForward?.equity||[]);
    document.getElementById('updated').textContent=`Último ciclo ${ageLabel(activity.age_seconds)} · ${shortTime(activity.last_cycle_at)}`;
    PulsePortal.render(marketPulse,status,futuresForward,positions);
    FourEnginePortal.render(platform);
    CommandCenterPortal.render({status,reviews,events,marketPulse,platform,futuresForward});
    GuardianIntelligencePortal.render(platform);
    CapitalLabPortal.render(platform);
    window.OpportunityShadowPortal?.render(platform);
  } catch(error) {
    PulsePortal.disconnected();
    FourEnginePortal.disconnected();
    CommandCenterPortal.disconnected();
    GuardianIntelligencePortal.disconnected();
    CapitalLabPortal.disconnected();
    window.OpportunityShadowPortal?.disconnected();
    const botState=document.getElementById('botState');
    botState.textContent='PORTAL SIN CONEXIÓN'; botState.classList.add('offline');
    document.getElementById('operationSummary').textContent='No se pudo consultar el motor. Comprueba la conexión con Windows antes de operar.';
    document.getElementById('updated').textContent='No fue posible consultar el motor';
    const cycleBadge=document.getElementById('spotCycleState');
    if(cycleBadge){cycleBadge.textContent='SIN DATOS RECIENTES';cycleBadge.className='state offline';}
    const cycleSummary=document.getElementById('spotCycleSummary');
    if(cycleSummary)cycleSummary.textContent='No se pudo consultar el diagnóstico de Spot. Comprueba la conexión con Windows.';
    const futuresCycleBadge=document.getElementById('futuresCycleState');
    if(futuresCycleBadge){futuresCycleBadge.textContent='SIN DATOS RECIENTES';futuresCycleBadge.className='state offline';}
    const futuresCycleSummary=document.getElementById('futuresCycleSummary');
    if(futuresCycleSummary)futuresCycleSummary.textContent='No se pudo consultar el diagnóstico de Futures. Comprueba la conexión con Windows.';
    const cycleReasons=document.getElementById('spotCycleReasons');
    if(cycleReasons)cycleReasons.textContent='';
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
window.addEventListener('resize',()=>Promise.all([api('/api/equity'),api('/api/futures-forward')]).then(([spot,futures])=>{renderChart(spot);renderFuturesChart(futures?.equity||[]);}).catch(()=>{}));
window.addEventListener('portal-ready',PulsePortal.onPortalReady);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
window.addEventListener('DOMContentLoaded',()=>{installPortalMotion();PulsePortal.init();FourEnginePortal.init();CommandCenterPortal.init();GuardianIntelligencePortal.init();refresh();});
setInterval(()=>{if(!document.hidden&&!document.querySelector('.shell').hidden)refresh();},30000);

document.getElementById('researchCurveChoice').addEventListener('change',renderResearchCurve);
