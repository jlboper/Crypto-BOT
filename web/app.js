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

function renderFuturesChart(points) {
  const canvas=document.getElementById('futuresEquityChart');
  if(!canvas)return;
  const ctx=canvas.getContext('2d'), dpr=window.devicePixelRatio||1;
  const width=canvas.clientWidth||520, height=190;
  canvas.width=width*dpr; canvas.height=height*dpr; ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,width,height);
  const rows=(points||[]).map(row=>Number(row.wallet_balance ?? row.equity ?? row.value)).filter(Number.isFinite);
  if(rows.length<2){ctx.fillStyle='#7890ad';ctx.font='12px Segoe UI';ctx.fillText('Esperando muestras de Futures',14,28);return;}
  const min=Math.min(...rows), max=Math.max(...rows), span=Math.max(max-min,1);
  ctx.strokeStyle='#263b55';ctx.lineWidth=1;
  for(let i=1;i<4;i++){const y=(height-24)*i/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
  ctx.strokeStyle='#4de3b0';ctx.lineWidth=2;ctx.beginPath();
  rows.forEach((value,i)=>{const x=8+(width-16)*(i/(rows.length-1));const y=8+(height-28)*(1-(value-min)/span);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
  ctx.stroke();
  retriggerMotion(canvas,'motion-chart');
}

function renderDualEvidence(spot, futures) {
  const score=futures?.scorecard||{};
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  set('spotObservedDays', Number(spot?.observed_days||0).toFixed(1));
  set('spotClosedTrades', String(Number(spot?.closed_trades||0)));
  set('spotObservedPnl', money(spot?.net_realized_pnl_usdt||0));
  set('spotObservedDrawdown', finite(spot?.sampled_max_drawdown_pct).toFixed(2)+'%');
  set('futuresObservedDays', finite(score.observed_days).toFixed(1));
  set('futuresObservedTrades', String(finite(score.closed_trades).toFixed(0)));
  set('futuresObservedReturn', score.account_return_pct==null?'—':pct(score.account_return_pct));
  set('futuresObservedPnl', money(score.gross_realized_pnl_usdt||0));
  set('futuresObservedDrawdown', finite(score.sampled_max_drawdown_pct).toFixed(2)+'%');
  set('futuresObservedQuality', (score.win_rate_pct==null?'—':finite(score.win_rate_pct).toFixed(1)+'%')+' / '+(score.profit_factor==null?'—':finite(score.profit_factor).toFixed(2)));
  set('futuresDirectionSplit','L '+finite(score.long_closed_trades).toFixed(0)+' ('+money(score.long_gross_pnl_usdt||0)+') · S '+finite(score.short_closed_trades).toFixed(0)+' ('+money(score.short_gross_pnl_usdt||0)+')');
  const cycles=finite(score.cycle_total),incidents=finite(score.incident_total),attempts=finite(score.failure_attempt_total);
  set('futuresErrorRate',incidents.toFixed(0)+' incidentes · '+attempts.toFixed(0)+' intentos fallidos · '+cycles.toFixed(0)+' ciclos');
  const spotDays=finite(spot?.observed_days),spotTrades=finite(spot?.closed_trades);
  const futuresDays=finite(score.observed_days),futuresTrades=finite(score.closed_trades);
  const checks=[
    [spotDays>=30,'Spot: '+spotDays.toFixed(1)+' / 30 días'],
    [spotTrades>=30,'Spot: '+spotTrades.toFixed(0)+' / 30 cierres'],
    [futuresDays>=30,'Futures: '+futuresDays.toFixed(1)+' / 30 días'],
    [futuresTrades>=30,'Futures: '+futuresTrades.toFixed(0)+' / 30 cierres'],
    [finite(score.consecutive_errors)===0,'Futures: sin errores consecutivos activos'],
  ];
  const list=document.getElementById('dualReadinessChecks');
  if(list){list.replaceChildren();for(const [ok,label] of checks){const li=document.createElement('li');li.textContent=(ok?'✓':'○')+' '+label;list.append(li);}}
  const ready=spotDays>=30&&spotTrades>=30&&futuresDays>=30&&futuresTrades>=30;
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
  const pos=positions[0]||futures?.position||null;
  const last=(futures?.equity||[]).at(-1)||{};
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;

  const limitState=document.getElementById('futuresLimitState');
  if(limitState){
    limitState.textContent=futures?.killed?'PAUSADO':(futures?.enabled?'PROTECCIONES ACTIVAS':'INACTIVO');
    limitState.className='state '+((futures?.killed||!futures?.enabled)?'warning':'neutral');
  }
  set('futuresLimitLeverage',futures?.automatic_leverage==null?'—':String(futures.automatic_leverage)+'x');
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
    positionState.className='state '+(positions.length?'warning':'neutral');
  }
  if(pos){
    const qty=Number(pos.quantity);
    const entry=Number(pos.entry_price);
    const unrealized=Number(last.unrealized_pnl||0);
    const direction=String(pos.direction||'—');
    const mark=Number.isFinite(qty)&&qty>0&&Number.isFinite(entry)?
      (direction==='SHORT'?entry-unrealized/qty:entry+unrealized/qty):null;
    set('futuresPositionContract',String(pos.symbol||futures?.symbol||'BTCUSDT')+' · '+direction);
    set('futuresPositionQty',Number.isFinite(qty)?num(qty,6):'—');
    set('futuresPositionPrices',num(entry,2)+' / '+(Number.isFinite(mark)?num(mark,2):'—'));
    set('futuresPositionUnrealized',(unrealized>=0?'+':'')+money(unrealized));
    const pnlNode=document.getElementById('futuresPositionUnrealized');
    if(pnlNode)pnlNode.className=unrealized>=0?'positive':'negative';
    set('futuresPositionProtection',num(pos.stop_price,2)+' / '+num(pos.take_profit,2));
    set('futuresPositionLeverage',String(pos.leverage||futures?.automatic_leverage||1)+'x · '+String(guard.margin_type||'ISOLATED').toUpperCase());
    set('futuresPositionOpened',pos.opened_at?shortTime(pos.opened_at):'—');
  } else {
    for(const id of ['futuresPositionContract','futuresPositionQty','futuresPositionPrices','futuresPositionUnrealized','futuresPositionProtection','futuresPositionLeverage','futuresPositionOpened'])set(id,'—');
    const pnlNode=document.getElementById('futuresPositionUnrealized');if(pnlNode)pnlNode.className='';
  }

  const days=finite(score.observed_days), trades=finite(score.closed_trades);
  const ready=days>=30&&trades>=30&&finite(score.consecutive_errors)===0;
  const evidence=document.getElementById('futuresEvidenceState');
  if(evidence){evidence.textContent=ready?'LISTO PARA REVISIÓN':'EVIDENCIA INSUFICIENTE';evidence.className='state '+(ready?'warning':'neutral');}
  set('futuresEvidenceNote',
    'Historial Futures Demo: '+days.toFixed(1)+' días y '+trades.toFixed(0)+' cierres. 30 días y 30 cierres son solo evidencia operativa; nunca activan dinero real automáticamente.');
  const metrics=document.getElementById('futuresEvidenceMetrics');
  if(metrics)metrics.innerHTML=
    '<div><small>Días observados</small><strong>'+days.toFixed(1)+'</strong></div>'+
    '<div><small>Operaciones cerradas</small><strong>'+trades.toFixed(0)+'</strong></div>'+
    '<div><small>P&amp;L realizado bruto</small><strong>'+money(score.gross_realized_pnl_usdt||0)+'</strong></div>'+
    '<div><small>Drawdown muestreado</small><strong>'+finite(score.sampled_max_drawdown_pct).toFixed(2)+'%</strong></div>';
  set('futuresEvidenceSummary',
    'Retorno observado '+(score.account_return_pct==null?'—':pct(score.account_return_pct))+
    ' · win rate '+(score.win_rate_pct==null?'—':finite(score.win_rate_pct).toFixed(1)+'%')+
    ' · profit factor '+(score.profit_factor==null?'—':finite(score.profit_factor).toFixed(2))+
    ' · LONG '+finite(score.long_closed_trades).toFixed(0)+' / SHORT '+finite(score.short_closed_trades).toFixed(0)+'.');
  const more=document.getElementById('futuresMoreMetrics');
  if(more)more.innerHTML=
    '<div><small>LONG P&amp;L</small><strong>'+money(score.long_gross_pnl_usdt||0)+'</strong></div>'+
    '<div><small>SHORT P&amp;L</small><strong>'+money(score.short_gross_pnl_usdt||0)+'</strong></div>'+
    '<div><small>Errores totales</small><strong>'+finite(score.error_total).toFixed(0)+'</strong></div>'+
    '<div><small>Errores consecutivos</small><strong>'+finite(score.consecutive_errors).toFixed(0)+'</strong></div>';
  const checks=document.getElementById('futuresReadinessChecks');
  if(checks){
    const rows=[[days>=30,days.toFixed(1)+' / 30 días'],[trades>=30,trades.toFixed(0)+' / 30 cierres'],
      [finite(score.consecutive_errors)===0,'Sin errores consecutivos activos'],
      [futures?.recovery?.durable_order_journal===true,'Journal durable'],
      [futures?.recovery?.startup_position_reconciliation===true,'Reconciliación al reiniciar'],
      [futures?.recovery?.native_exchange_stop_orders===true,'Stops nativos persistentes del exchange']];
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
      return '<article class="futures-asset-card"><h4>'+esc(symbol.replace('USDT',''))+'</h4><dl>'+
        '<div><dt>Estado</dt><dd>'+(p?esc(p.direction)+' · '+esc(String(p.leverage||1))+'x':'ESPERANDO')+'</dd></div>'+
        '<div><dt>LONG</dt><dd>'+String(long.trades||0)+' · '+money(long.gross_pnl_usdt||0)+'</dd></div>'+
        '<div><dt>SHORT</dt><dd>'+String(short.trades||0)+' · '+money(short.gross_pnl_usdt||0)+'</dd></div>'+
        '<div><dt>Score</dt><dd>'+esc(String((futures?.latest_signals||{})[symbol]?.long_score??'—'))+' / '+esc(String((futures?.latest_signals||{})[symbol]?.short_score??'—'))+'</dd></div>'+
      '</dl></article>';
    }).join('');
  }
  const signalGrid=document.getElementById('futuresSignalGrid');
  if(signalGrid){
    const symbols=Array.isArray(futures?.symbols)?futures.symbols:[];
    signalGrid.innerHTML=symbols.map(symbol=>{
      const s=(futures?.latest_signals||{})[symbol]||{};
      const r=(futures?.last_ai_reviews||{})[symbol]||{};
      return '<article class="futures-asset-card"><h4>'+esc(symbol)+'</h4><dl>'+
        '<div><dt>LONG / SHORT</dt><dd>'+esc(String(s.long_score??'—'))+' / '+esc(String(s.short_score??'—'))+'</dd></div>'+
        '<div><dt>Dirección</dt><dd>'+esc(s.direction||'SIN SEÑAL')+'</dd></div>'+
        '<div><dt>RSI</dt><dd>'+(s.rsi==null?'—':num(s.rsi,1))+'</dd></div>'+
        '<div><dt>IA</dt><dd>'+esc(r.verdict||'SIN REVISIÓN')+'</dd></div>'+
      '</dl></article>';
    }).join('');
  }
  const shadow=document.getElementById('futuresShadowStrategies');
  if(shadow){
    const rows=(futures?.shadow_scorecard||[]).slice(0,9);
    shadow.innerHTML=rows.length?rows.map(row=>'<div><small>'+esc(row.strategy_key)+'</small><strong>'+num(row.pnl_pct||0,2)+'% · '+String(row.trades||0)+' trades</strong></div>').join(''):'<div><small>Shadow lab</small><strong>Acumulando muestras</strong></div>';
  }
  const body=document.getElementById('futuresTradeRows');
  const rows=(futures?.trades||[]).slice(0,12);
  if(body)body.innerHTML=rows.length?rows.map(t=>'<tr><td><strong>'+esc(t.symbol)+' '+esc(t.direction)+'</strong></td><td>'+num(t.quantity,6)+'</td><td>'+num(t.entry_price,2)+'</td><td>'+num(t.exit_price,2)+'</td><td class="'+(Number(t.gross_pnl)>=0?'positive':'negative')+'">'+(Number(t.gross_pnl)>=0?'+':'')+num(t.gross_pnl,2)+'</td><td>'+esc(t.exit_reason||'—')+'</td></tr>').join(''):emptyRow(6,'Aún no hay cierres Futures.');
}

function renderObservationHealth(spotHealth, futuresHealth) {
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  const stateClass=value=>value==='OK'?'':value==='ATTENTION'?'offline':'warning';
  const stateLabel=value=>({OK:'ESTABLE',WATCH:'VIGILAR',ATTENTION:'ATENCIÓN',STARTING:'INICIANDO'})[value]||'SIN DATOS';
  const formatGap=value=>value==null?'—':value<60?Math.round(value)+' s':(value/60).toFixed(1)+' min';
  const integrityText=value=>{const entries=Object.entries(value||{});if(!entries.length)return '—';const ok=entries.filter(([,passed])=>passed===true).length;return ok===entries.length?'✓ '+ok+'/'+entries.length+' comprobaciones':ok+'/'+entries.length+' correctas';};
  const renderState=(id,value)=>{const node=document.getElementById(id);if(!node)return;node.textContent=stateLabel(value);node.className='state '+stateClass(value);};
  renderState('spotHealthState',spotHealth?.state);
  renderState('futuresHealthState',futuresHealth?.state);
  set('spotCycleCoverage',spotHealth?Number(spotHealth.cycle_coverage_pct||0).toFixed(1)+'%':'—');
  set('spotCycleSamples',spotHealth?String(spotHealth.samples||0)+' / '+String(spotHealth.expected_samples||0):'—');
  set('spotCycleGap',formatGap(spotHealth?.average_cycle_gap_seconds));
  set('spotDailyErrors',spotHealth?String(spotHealth.errors||0)+' / '+String(spotHealth.warnings||0):'—');
  set('spotDailyAi',spotHealth?String(spotHealth.ai_reviews||0)+' / '+String(spotHealth.ai_rejects||0):'—');
  set('spotDailyTrading',spotHealth?String(spotHealth.closed_trades||0)+' · '+money(spotHealth.realized_pnl_usdt||0):'—');
  set('spotIntegrity',integrityText(spotHealth?.integrity));
  set('futuresCycleCoverage',futuresHealth?Number(futuresHealth.cycle_coverage_pct||0).toFixed(1)+'%':'—');
  set('futuresCycleSamples',futuresHealth?String(futuresHealth.samples||0)+' / '+String(futuresHealth.expected_samples||0):'—');
  set('futuresCycleGap',formatGap(futuresHealth?.average_cycle_gap_seconds));
  set('futuresDailyErrors',futuresHealth?String(futuresHealth.consecutive_errors||0)+' consecutivos · '+String(futuresHealth.errors_total||0)+' total':'—');
  set('futuresDailyTrading',futuresHealth?String(futuresHealth.closed_trades||0)+' · '+money(futuresHealth.realized_pnl_usdt||0):'—');
  set('futuresIntegrity',integrityText(futuresHealth?.integrity));
  const states=[spotHealth?.state,futuresHealth?.state];
  const overall=states.includes('ATTENTION')?'ATTENTION':states.includes('WATCH')?'WATCH':states.every(x=>x==='OK')?'OK':'STARTING';
  renderState('observationHealthState',overall);
  const note=document.getElementById('observationHealthNote');
  if(note)note.textContent=overall==='OK'?'La muestra de las últimas 24 h tiene continuidad e integridad operativa suficientes para seguir observando sin intervenir.':overall==='ATTENTION'?'Hay una condición operativa que puede contaminar la muestra. Revisar continuidad, journal o errores antes de interpretar resultados.':'La muestra sigue acumulándose; no cambia estrategia ni riesgo durante esta fase.';
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
    const [status,positions,trades,reviews,equity,events,research,researchState,paperReport,futuresForward] = await Promise.all([
      api('/api/status'),api('/api/positions'),api('/api/trades'),api('/api/ai-reviews'),api('/api/equity'),api('/api/events'),api('/api/research'),api('/api/research/status'),api('/api/paper-scorecard'),api('/api/futures-forward')
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
      futuresState.textContent=futuresDisabledReason || (futuresForward?.killed?'PAUSADO':'ACTIVO');
      futuresState.className='state '+((futuresDisabledReason||futuresForward?.killed)?'warning':'neutral');
    }
    document.getElementById('accountEnvironmentTitle').textContent='Spot · '+modeUpper;
    const spotEngineState=document.getElementById('spotEngineState');
    if(spotEngineState){
      spotEngineState.textContent=status.killed?'PAUSADO':(status.activity?.state||'ACTIVO');
      spotEngineState.className='state '+(status.killed?'warning':'neutral');
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
      forwardState.textContent=forwardDisabledReason || (futuresForward.killed?'PAUSADO':(forwardPositions.length?forwardPositions.length+' POSICIÓN'+(forwardPositions.length===1?' ABIERTA':'ES ABIERTAS'):'ACTIVO · ESPERANDO SEÑAL'));
      forwardState.className='state '+((forwardDisabledReason||futuresForward?.killed)?'warning':'neutral');
    }
    const fWallet=document.getElementById('futuresForwardWallet');
    if(fWallet){
      const last=(futuresForward?.equity||[]).at(-1);
      fWallet.textContent=last?money(last.wallet_balance):'Esperando ciclo';
    }
    const fPosition=document.getElementById('futuresForwardPosition');
    if(fPosition)fPosition.textContent=forwardPositions.length?forwardPositions.map(p=>`${String(p.symbol).replace('USDT','')} ${p.direction}`).join(' · '):'Sin posición';
    const fClosed=document.getElementById('futuresForwardClosed');
    if(fClosed){
      const closed=Number(futuresForward?.closed_trades||0);
      const pnl=Number(futuresForward?.gross_pnl||0);
      fClosed.textContent=closed+' '+(closed===1?'cierre':'cierres')+' · '+(pnl>=0?'+':'')+money(pnl);
    }
    const fReturn=document.getElementById('futuresForwardReturn');
    if(fReturn)fReturn.textContent=futuresForward?.scorecard?.account_return_pct==null?'—':pct(futuresForward.scorecard.account_return_pct);
    const fAi=document.getElementById('futuresForwardAi');
    if(fAi){
      const reviews=futuresForward?.last_ai_reviews||{};
      const review=Object.values(reviews).filter(Boolean).at(-1);
      fAi.textContent=review?`${review.verdict} · ${Math.round(Number(review.confidence||0)*100)}%`:
        (status.ai_enabled?'Activa':'Desactivada');
    }
    const fAiModel=document.getElementById('futuresForwardAiModel');
    if(fAiModel)fAiModel.textContent=futuresForward?.ai_model||status.ai_model||'—';
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
      fSafety.textContent=`Journal ${rec.durable_order_journal?'✓':'—'} · conciliación al reiniciar ${rec.startup_position_reconciliation?'✓':'—'} · ${repair} · ${resume}${blocked.length?' · bloqueados: '+blocked.join(', ')+(blockedDetail?' ['+blockedDetail+']':''):''}${recoveryText}${gapText} · IA final: ${futuresForward?.ai_model||status.ai_model}. Stops nativos persistentes aún pendientes; LIVE bloqueado.`;
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
    document.getElementById('positions').innerHTML=positions.length?positions.map(p=>`<tr><td><strong>${esc(p.symbol)}</strong></td><td>${num(p.quantity)}</td><td>${num(p.entry_price,4)}</td><td>${p.market_price==null?'—':num(p.market_price,4)}</td><td class="${p.unrealized_pnl==null?'':p.unrealized_pnl>=0?'positive':'negative'}">${p.unrealized_pnl==null?'—':`${p.unrealized_pnl>=0?'+':''}${num(p.unrealized_pnl,2)}`}</td><td class="${p.unrealized_pct==null?'':p.unrealized_pct>=0?'positive':'negative'}">${p.unrealized_pct==null?'—':`${p.unrealized_pct>=0?'+':''}${num(p.unrealized_pct,2)}%`}</td><td>${num(p.stop_price,4)}</td><td>${num(p.take_profit,4)}</td><td><button class="secondary paper-close" data-symbol="${esc(p.symbol)}" ${p.market_price==null||!paperControlsAvailable()?'disabled':''}>Cerrar</button></td></tr>`).join(''):emptyRow(9,'Sin posiciones abiertas');
    document.getElementById('trades').innerHTML=trades.length?trades.slice(0,8).map(t=>`<div class="feed-item"><strong class="${esc(t.side.toLowerCase())}">${esc(t.side)}</strong><div><strong>${esc(t.symbol)} · ${num(t.quantity)}</strong><p>${esc(t.reason)}</p></div><time>${shortTime(t.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay operaciones');
    document.getElementById('reviews').innerHTML=reviews.length?reviews.slice(0,8).map(r=>`<div class="feed-item"><strong class="${esc(r.verdict.toLowerCase())}">${esc(r.verdict)}</strong><div><strong>${esc(r.symbol)} · ${(r.confidence*100).toFixed(0)}%</strong><p>${esc(r.reason)}</p></div><time>${shortTime(r.created_at)}</time></div>`).join(''):feedEmpty('Aún no hay revisiones');
    const important=events.filter(e=>['WARN','ERROR','CRITICAL'].includes(e.level)).slice(0,10);
    document.getElementById('events').innerHTML=important.length?important.map(e=>`<div class="feed-item"><strong class="event-${esc(e.level.toLowerCase())}">${esc(e.level)}</strong><div><p>${esc(e.message)}</p></div><time>${shortTime(e.created_at)}</time></div>`).join(''):feedEmpty('Sin errores ni advertencias recientes');
    renderChart(equity);
    renderResearch(research,researchState);
    renderPaperEvidence(paperReport,equity,trades);
    renderDualEvidence(paperReport,futuresForward);
    renderFuturesParity(futuresForward);
    renderObservationHealth(status?.observation_health,futuresForward?.observation_health);
    renderFuturesChart(futuresForward?.equity||[]);
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
window.addEventListener('resize',()=>Promise.all([api('/api/equity'),api('/api/futures-forward')]).then(([spot,futures])=>{renderChart(spot);renderFuturesChart(futures?.equity||[]);}).catch(()=>{}));
window.addEventListener('portal-ready',refresh);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
window.addEventListener('DOMContentLoaded',()=>{installPortalMotion();refresh();});
setInterval(()=>{if(!document.hidden&&!document.querySelector('.shell').hidden)refresh();},30000);
