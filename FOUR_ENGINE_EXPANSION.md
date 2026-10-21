## 0.10.47 — validación y recuperación en preparación

Base sincronizada main `a851908a11ff9f84cf53e755db120edc853b9fe9` (0.10.46).
Verificación independiente 21Oct2026 01:56:39 UTC: firma Ed25519, 207/207 hashes,
journal COMMITTED, runtime RUNNING, mismo motor7636/agente17748 y HTTPS correcto.
Spot5/Futures7 con protecciones ARMED y cantidad desprotegida observada cero.
Pulse/Quant SHADOW; Guardian LEVEL0 sin autoridad. Son cortes fechados.

El propietario autorizó completar los seis frentes propuestos, manteniendo esas
restricciones. La candidata añade trazabilidad postcommit de cierres/parciales,
compatibilidad de rollback46, presupuesto remoto después de compactar, consultas
RO con evidencia, matriz Research/Quant y preparación Risk+Capital exclusivamente
SIM. No habilita Testnet nuevo, Control, reservas efectivas, LIVE ni promociones.
Ver [VALIDATION_AND_RECOVERY.md](VALIDATION_AND_RECOVERY.md) para alcance y límites.

Antes de publicar se obtuvieron ocho copias SQLite locales consistentes cada una
(quick_check OK/hash; no captura global atómica), sin restaurar datos. Referencia
01:58:35–39 UTC: 154485 filas/11 tablas para comparación posterior; configuraciones
y credenciales sólo mediante hashes. CI, publicación, firma e instalación47 siguen
pendientes y requieren comprobación propia. Local47:1042Python offline PASS142.563s,
242Node PASS39.280s, PS5.1/build/diff PASS; no reutilizar resultados46.
Las secciones siguientes conservan historia.

# Four engines and Portfolio Guardian — approved staged continuation

## Estado verificado — 0.10.45 instalada; correctiva remota46 en preparación

Main45 **`5d08ca7f78731236386212c2c88983b3e21dd281`**, [PR122](https://github.com/jlboper/Crypto-BOT/pull/122).
[Publicación39453869690](https://github.com/jlboper/Crypto-BOT/actions/runs/39453869690)
aprobó validate/validate-windows/publish. A20Oct2026 16:10:01UTC: Ed25519,
**207/207 hashes**, journal COMMITTED, runtime RUNNING, único motor12020 y PID13968
anterior salido. Agente23592 autorrefrescado, **11/11 módulos**. Spot3/Futures7
ARMED y cantidad desprotegida observada cero; Pulse/Quant SHADOW/FRESH.

Observer45 verificado con tres latidos distintos, IDLE/FRESH, cero errores,
descartes y registros; no se forzaron entradas. Todos los permisos false/LEVEL0.
Cuatro adaptadores probados sintéticamente, aún sin entradas nuevas observadas
al corte. Exportador instalado414068bytes incluye observer1035bytes, Guardian,
cuatro motores y mismo Capital Lab44. Guardian Intelligence PARTIAL por Futures
STALE_OR_UNPRICED_SOURCE, no caída del motor: fuente desconocida conservada sin
relajar frescura. A16:11:31UTC volvió OBSERVING: cuatro fuentes FRESH/completas,
tres assessments/tres replays causales MATCH, cero errores; IA conserva2/2. Preservación de referencia15:59:45–50UTC: diez tablas,
**138702 filas** sin ausencias/cambios; configuración/credenciales/settings hashes
intactos. Backup updater45 sólo Spot85trades/53receipts íntegros, no backup global.

Auditoría remota detectó **401** para los dos JS nuevos: se copiaron al build,
pero faltaban en la lista de recursos estáticos del Worker; incluso con sesión
habrían terminado404. El resto del portal y trading permanecen disponibles.
46 agrega exactamente esas dos rutas de código estático, manteniendo CSP,
no-store y autenticación/CSRF de APIs. No cambia controles ni módulos financieros.
No declarar45 completamente funcional remotamente ni46 publicada/instalada
antes de validar su propio CI, firma, rollout y ambos GET200 de recursos.

Validación local46: **959/959 Python offline** (157.844s TEST_RESULTS,
20Oct2026 16:16:56.557358UTC; runner157.846s), **223/223 Node** (44.546s),
build/diff PASS, sin fallos/errores/skips; red externa bloqueada, bot no iniciado.
Regresión de recursos falló401 antes del fix y pasó después. CI/rollout46 pendientes.

Los registros siguientes conservan los cortes anteriores de preparación45/base44.

## Registro histórico — preparación45 desde44

Main **0.10.44** `f79578360f7870321d29cb842966bac2a250dba5`,
[PR #121](https://github.com/jlboper/Crypto-BOT/pull/121),
[publicación 39407655253](https://github.com/jlboper/Crypto-BOT/actions/runs/39407655253)
y [seguridad 39407655107](https://github.com/jlboper/Crypto-BOT/actions/runs/39407655107)
SUCCESS en Linux/Windows. El 20Oct2026 a10:31–10:34 UTC se verificaron Ed25519,
**195/195 hashes**, journal COMMITTED, runtime RUNNING y un único motor13968.
Agente13292: **11/11 módulos** y dos sincronizaciones HTTPS distintas correctas.
Cinco assets web remotos coincidieron con Git. La publicación no se usó como
prueba de instalación; ambas se verificaron por separado.

Capital Protocol Lab instalado se ejecutó exactamente una vez: siete casos
PASSED/siete SQLite SIM nuevas, lecturas posteriores sin mutaciones. Research
Lab compartido y 47 plegables comprobados. Guardian LEVEL0: cuatro fuentes
FRESH/completas, tres replays causales MATCH, cero errores y autoridad false.
Corte operativo posterior **12:23:44 UTC**: Spot1/Futures8, protecciones nativas
ARMED y cantidad desprotegida observada cero; Pulse/Quant SHADOW/FRESH, Pulse
WARMING_UP. Son cortes fechados, no conteos permanentes.

Conservación44: las **129773 filas** de diez tablas históricas seleccionadas al
corte10:20:21–10:20:34 UTC permanecieron sin ausencias/cambios; configuración,
credenciales y settings congelados conservaron hashes. Backup restaurable44
sólo Spot:83trades/51receipts íntegros. Los otros hashes son referencias RO,
no backups SQLite ni captura atómica de todo el sistema.

Candidata45 en rama `feature/opportunity-capital-shadow-v01045`: contrato IA
Guardian acotado, intenciones finales de cuatro motores, consumidor asíncrono
persistente y aritmética hipotética; paneles compartidos RO. Véase
[OPPORTUNITY_CAPITAL_SHADOW.md](OPPORTUNITY_CAPITAL_SHADOW.md). Guardian continúa
LEVEL0: sin veto, ejecución, reservas efectivas o promoción. Sin cambio de riesgo,
modelo/presupuesto IA, revisión individual, stops ni reconciliación nativa.
No declarar Fase3 operativa completa: cuentas/baselines no verificados, cierres
observacionales pendientes y límites globales incompletos conservan UNKNOWN.

IA instalada44: dos fallos20Oct `AI_COMMENTARY_INVALID` consumen2/2; no resetear
claims ni forzar llamadas. Uso conocido1166input/526output, estimación cliente
USD0.0003796, excluye dos fallos anteriores de causa/uso desconocidos. No hay
respuesta cruda para atribuir causa.45 corrige una discrepancia reproducible del
contrato; la aceptación real por el API y su utilidad siguen pendientes de
observación normal con cuota disponible. No confundir tests sintéticos con IA real.

Validación local45:959 Python offline/220 Node PASS, PS5.1 lifecycle/vistas,
build/diff; foco final contrato+UI32 PASS después de ajustes menores. QA de
preview sintético a360/768/1366px sin overflow. CI/rollout45 pendientes.

Las secciones siguientes son registros históricos; el checkpoint anterior y la
evidencia autenticada más reciente prevalecen sobre estados de preparación antiguos.

## Historical baseline and Command Center continuation

**Current: installed 0.10.42, corrective 0.10.43 pending.** Main
`b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`, [PR #119](https://github.com/jlboper/Crypto-BOT/pull/119),
[publication 39181606398](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
and [safety 39181606401](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
succeeded. At 2026-10-19 00:42:33 UTC: Ed25519 verified, 188/188 hashes, five web
assets matching, engine 3680, Spot 1/Futures 5 ARMED and zero unprotected quantity.
Independent agent inventory was 9/11 at that cut. At **00:54:20 UTC**, signed
refresh completed: agent 21344, **11/11**, sync_ok and two fresh healthy heartbeats;
engine 3680 unchanged, Spot 1/Futures 5 ARMED and zero unprotected quantity.

Guardian is PARTIAL with 0/4 sources valid: all UNKNOWN due to
WAL_SIDECARS_UNAVAILABLE; its first real record replays MATCH. One real AI attempt
FAILED with unknown usage/cause. Do not call this complete operating success.
43 corrects normal `mode=ro`/query-only WAL reads without requiring persistent
sidecars, permits only transient SQLite metadata without financial DML, and
prefilters all-UNKNOWN captures before AI with safe diagnostics. PR/main CI/
publication/signature/install remain pending; data/risk/protections are preserved.
The synthetic Capital Protocol Lab stays outside this release and is not a
four-engine capital runtime or authorization to share funds.

43 candidate check 00:47:04 UTC read temporary standard RO backups of all four
actual schemas: FRESH/complete, positions 1/5/1/0 and descriptive SIDEWAYS. No
engine/providers/credentials loaded. This is candidate evidence, not installed
43; focused capture/service 87 PASS and all-UNKNOWN no-AI 1 PASS. Additional 43
checks: AI 35 PASS (6.961 s), Node 180/180 PASS (106.485 s), Windows PowerShell 5.1
lifecycle/view, portal build and diff PASS. Full offline Python **777/777 PASS**,
no failures/errors/skips, **238.609 s** (`TEST_RESULTS.json`, 00:55:17 UTC), external
network blocked and no bot started. PR/CI/publication/signature/install 43 pending.

### Historical 42 preparation record

Current baseline is verified 0.10.41 main
`022fb9135d165d5c52f12b65aa9628ab8c1436af`, [PR #118](https://github.com/jlboper/Crypto-BOT/pull/118),
published/signed/installed 178/178 after successful
[publication 39134814222](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814222)
and [safety 39134814202](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814202).
The 14:16:30 UTC audit on 2026-10-18 retained one Spot/nine Futures protected
positions, no observed unprotected quantity, fresh agent sync and financial rows.

Candidate 0.10.42 implements Guardian Intelligence SHADOW LEVEL 0 alongside the
existing pure Observer: strict RO acquisition, descriptive BTC regime/conflicts,
independent frozen journal/replay and optional bounded advisory AI. The owner's
AI request/key reuse permits its separate two-attempt/day budget under global
AI enablement; it grants no Control/level-1 authority. No order hooks, reservations,
capital sharing or risk changes. Eight local read-only query intents explain the
current assessment and cite its evidence; browser query history is not durable.
General server-side NL/journal querying, Capital Manager and Guardian Control
remain future phases in [Command Center 2.0](COMMAND_CENTER_2_0.md).

Local 42 validation passed 767/767 offline Python tests (361.510 s), 180/180 Node
tests (85.515 s), Windows PowerShell 5.1 lifecycle/view checks, portal build and
diff checks. Browser QA at 1366/360/768 px found no horizontal overflow and one
Guardian workspace. PR/main CI, publication/signature, installation and actual
model usage remain pending. A 19:10 UTC predecessor audit again verified 41's
178/178 hashes, engine 19240/agent 13056, one Spot/nine Futures positions, native
protections ARMED and zero observed unprotected quantity.

## Historical 0.10.40 / 0.10.41 preparation context

The four-engine foundation is now verified at 0.10.40 main
`81ba4366cf587c16cae20d403974a340080c4d10`, [PR #117](https://github.com/jlboper/Crypto-BOT/pull/117),
published/signed and installed 178/178 hashes at 2026-10-18 02:27 UTC.
[Publication](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416208)
and [Linux/Windows safety](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416215)
succeeded. Spot Testnet, Futures Demo, Pulse Shadow and Quant Shadow remain
separate. Funding Carry simulation and closed-bar research are implemented;
StatArb entries and Guardian Control remain blocked.

Candidate 0.10.41 starts [CRYPTO-BOT 2.0](COMMAND_CENTER_2_0.md): phase-0 audit
and phase-1 shared presentation with seven views and coherent Windows labels.
Existing Guardian evidence under Portfolio & Capital is read-only. Future
Guardian Intelligence, Capital Manager Shadow and explicitly authorized Control
are distinct components, not capabilities implied by this interface or the
prototype reservation module. No new API cost, execution path or risk change.
Verification of 41 remains separate. The versioned preparation records below
preserve development history and do not override this current baseline.

Owner request received 2026-10-16 after installed 0.10.33. Finish the pending
ten-asset/five-source Pulse and collapsible portal release before starting this
work from updated main. Existing Spot Testnet/Futures Demo and Pulse Shadow remain
separate and supervised; no duplicate engine, data reset or risk increase.

1. Guardian Observer and extensible four-engine contracts: scoped gross/net
   exposure, capital/reservations, concentration/conflicts, data freshness and
   deterministic alerts. Observer cannot veto or raise existing limits. Missing
   evidence remains unknown, not zero. Independent environments never form one
   real portfolio. Native stops/reconciliation never depend on Guardian/AI.
2. Four cards, Guardian view, Quant Funding Carry/Statistical Arbitrage sections,
   shared responsive web assets and Windows states. Until initialized, Quant must
   explicitly show NOT_STARTED, with no invented performance or enabled execution.
3. Quant Shadow only: separate virtual capital/journal, coherent two-leg costs and
   residual risk; observed funding is distinct from projected/settled simulation.
   Funding/hedge timing, basis, margin, liquidity and adverse sign changes matter.
   BTC/ETH/SOL pair research must test cointegration/stability/structural breaks;
   correlation alone never qualifies convergence. No claimed atomic exchange hedge.
4. Historical/OOS/forward evaluation, conservative stress and restart/update
   recovery. No automatic promotion or Guardian control activation. Both require
   separate review/authorization and verified common reservation/reconciliation.

Each stage requires Python/Node/Windows/Linux checks, normal PR/main publication,
Ed25519 signature, installed inventory and current operating-health evidence.
Document implemented/tested/pending states separately. LIVE remains absent.

## Stage 1 — 0.10.35 implementation

Pure bounded Observer consumes the existing credential-free dashboard evidence;
it has no broker, database, filesystem or network dependencies. Four separate
scopes retain environment identity, gross/net notional, priced/unpriced inventory,
nominal distance to stop, capital freshness, descriptive concentration, native
protection status and overlap alerts. Leverage does not multiply notional.
Futures cost-inclusive existing budget stays distinct from nominal stop distance.
Unknown or stale observations remain null; no aggregate real-wallet total exists.

The optional remote contract includes `portfolio_guardian`, `engine_catalog` and
`quant`. Quant is strictly NOT_STARTED; no wallet, worker or orders are created.
Authenticated local/remote `GET /api/platform` returns these identities and
diagnostics. Local projection caches for ten seconds to bound refresh cost.
Optional failures degrade diagnostics while preserving the existing heartbeat,
signed updater and financial engines. Guardian is never called by trading cycles.

Reservations/admission, correlation, daily/weekly losses, drawdown and liquidation
modeling are explicitly unavailable at this stage. Observer does not implement
shared-capital enforcement or allocation journals; those require a separately
validated Control phase. It cannot veto, reserve capital or increase permissions.
The four-card web/Windows view, Quant Shadow and statistical evaluation remain
separate subsequent PRs. No automatic strategy promotion or Testnet activation.

Observed Pulse freshness fix in the same continuity stage: provider timestamps
can lead Windows within the already accepted five seconds. Receipt must precede
decision and expire independently; the selected price must also be recent.
Future buckets are excluded and the existing 80% time coverage gate remains.
Sparse trading can therefore keep an asset incomplete; no forced entry or
fabricated statistical confidence fills that gap.

## Stage 2 — 0.10.36 shared portal and Windows app

Four consistent overview cards preserve the existing identity and use a responsive
4/2/1 layout. Guardian has scoped exposure/budget, overlap/alert and data-quality
folds. Quant has Funding Carry and Statistical Arbitrage folds, explicitly not
started, with unknown finances and unavailable execution/promotion controls.
The comparison includes a fourth unavailable cohort, never an invented return.
Twenty-one long detail groups can collapse; navigation opens the correct group.

The Windows indicator uses four compact cards in two rows, read-only asynchronous
optional platform diagnostics, Guardian status and direct portal links. Process
ownership, startup, watchdogs, update/recovery and engine controls are preserved.
PAPER labels simulated protections; Testnet retains native confirmation evidence.
Source installation and a running indicator are distinct: verify the signed hashes
before reopening the existing indicator to load its new layout. No extra trading
process is created. Missing/stale optional evidence does not imply engine failure.

Stage 2 was observed signed and installed as 0.10.36, main
`1bb77fad1a490472907ce29591e0b1075d3e7ba3`, PR #113, with 167/167 file hashes.
This is source-installation evidence; an offscreen synthetic component render
does not prove the actual desktop window was captured.

## Stage 3 — 0.10.37 Quant Shadow candidate

`trader/quant_shadow.py` runs as one optional service inside the existing signed,
supervised process. It has no account-executor dependency or exchange-order path.
It persists its own `data/quant-shadow.db`, hypotheses, virtual wallet, two-leg
positions, costs, decisions, source evidence, funding receipts, equity and journal.
Lease/ownership recovery, idempotent events, independent pause/kill and isolated
provider failures preserve the other engines. A missing database stays NOT_STARTED;
an unreadable ledger is unavailable, never a fabricated zero wallet.

Anonymous allowlisted Binance Spot/Futures reference GETs observe BTC/ETH/SOL,
depth, basis, premium/funding and historical funding schedules. Public production
prices are reference data, never Testnet/Demo fills. Evaluation is once per minute,
freshness is 90 seconds, transport/history are bounded and rate limits back off.
No new credential, paid subscription, model call or GPU dependency is introduced.

Funding Carry evaluates hypothetical Spot LONG/Futures SHORT pairs against
independent quantity, spread, depth, timing, basis, historical adverse funding,
fees/slippage, collateral and stress checks. An observed rate and a conditional
projection are distinct from an authoritative historical event applied once as
`SETTLED_SIMULATION`; none is real income. Missing due funding evidence makes net
valuation/statistics unavailable. Each leg has costs; failure of a second leg has
a conservative simulated unwind. The hedge is never claimed atomic.

Initial virtual capital is 1,000 USDT, at most two pairs/four legs, 15% gross
exposure and 0.25% estimated risk per pair, subordinate to existing global bounds.
Quant's own daily/weekly entry-loss latches are 1%/2%; baselines use the first valid
ledger equity within each UTC period, possibly after midnight. Unknown valuation
blocks entries. Pauses and loss latches preserve hypothetical protective exits.
The 80% virtual-collateral stress exit and extra simulated stress cost are research
proxies, not a Binance liquidation model, maximum-loss or intrabar-fill guarantee.
Spot/Futures risk settings are unchanged; no actual shared capital is allocated.

StatArb calculates aligned BTC/ETH/SOL pair diagnostics, train/holdout stability,
z-score, residual unit-root screen, correlation/volatility and structural-break
checks. These are exploratory hypotheses, not independent cointegration proof:
its entries remain blocked, even if a screen looks favorable. Frozen-source replay
uses only information received by the decision cutoff; matching a replay does not
validate profitability, OOS performance or statistical significance.

The shared local/remote portal and Windows app show actual initialized Shadow
state, hypothetical pairs/legs, costs, decisions/journal, market/funding and data
quality. Stale projections mask current valuations. Authenticated pause/resume
uses the existing agent with a dedicated Quant capability; it cannot change mode,
risk or promotion. Guardian observes the fourth separate ledger and still has no
veto, reservations or allocation authority.

Focused checks recorded: 70 core, 59 contract, 31 UI and 20 Windows-asset tests;
PowerShell 5.1 view/render checks also passed. The complete offline/Node suites,
Linux/Windows CI, exact main publication, signature and installed audit are still
pending for this candidate. Prepared is not published or installed.

Stage 4 independent historical/OOS calibration, matched net benchmarks and longer
forward evidence remain pending. Guardian Control and new Testnet execution still
require separate validation and explicit owner authorization; LIVE remains absent.

## Stage 4 groundwork — 0.10.40 closed-minute diagnostic candidate

Observed snapshot totals concealed gaps and insufficient contiguous StatArb
history. The candidate reads up to 500 officially closed Spot 1m bars for each
BTC/ETH/SOL from the fixed public allowlist, preserving them in a separate
append-only store. First local receipt, market-close time and decision cutoff
have distinct meanings: a prior close never proves the bot knew the bar then.
Replay excludes evidence first received after its decision, and forming/future
bars remain ineligible. Original snapshot gaps and journals are not interpolated
or silently rewritten. This is retrospective closed-bar diagnosis, not forward
OOS evidence, a validated backtest or independently calibrated cointegration.
StatArb hypothetical entries remain blocked regardless of a favorable screen.

Batch public premium-index reads make room for the closed-bar requests under
the existing 15-request/minute cap: planned 14 startup and 10 steady refresh
calls. No credentials, execution mode, risk, capital or Guardian authority change.
Based on signed/installed 0.10.39 main `2328f2959dc9b4fb939e889519b59a19e5a58423`,
verified 176/176 hashes after successful publication 39070205949 and safety 39070205944.
The 0.10.40 full suites, Linux/Windows CI,
publication/signature and installed runtime evidence must be checked separately.
