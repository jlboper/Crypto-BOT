## Contrato de cuenta — correctiva53

No aplicar el contrato Spot de canTrade a Futures Account V3: este último
separa configuración y balances y omite ese campo. Exigir localmente forma
financiera suficiente no certifica permisos, cuenta completa ni capital común.
Conservar errores/malformados PARTIAL, autoridad false y los mismos hosts/rutasGET.
Fuente oficial: https://developers.binance.com/zh-CN/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
52b110b7e instalada255/25523Oct22:39UTC;53 requiere CI/firma/rollout propios.

## 0.10.52 — historia de preparación

Base main51 `f90f311f53a7c6f338b079f1d37b64bf4cd58459`,
[PR128](https://github.com/jlboper/Crypto-BOT/pull/128). Workflows39903537643
y39903537657 SUCCESS Linux/Windows. Corte23Oct15:51UTC: Ed25519 válida,
237/237 hashes, journal COMMITTED, runtime RUNNING, mismo motor18436/agente25008,
HTTPS correcto; Spot2/Futures3 ARMED. Son observaciones fechadas.

La candidata52 implementa auditoría GET Testnet/Demo explícita, protocolo conjunto
riesgo+capital exclusivamente SIM, bloqueos durables de pérdidas SIM, hipótesis
de capital Spot/Futures y validación de recibos prospectivos, más informe plegable
compartido. Ver [MIGRATION_AUDIT.md](MIGRATION_AUDIT.md). No cambia admisión, riesgo,
IA individual, protección, cuentas o trading de los motores. Guardian LEVEL0;
Pulse/Quant SHADOW. LIVE/control/reservas efectivas/promoción permanecen bloqueados.

No une wallets ni deduce30d certificados. Flow y latches aún tienen almacenes
independientes; no hay captura/registro durable de cohortes operativas ni
admisión conjunta de motores. Fuente de cuenta parcial, historia/cashflows y
validación operativa siguen pendientes. Pruebas, CI, publicación, firma e
instalación52 requieren evidencia propia. Las secciones siguientes son historia.

## Checkpoint vigente — 0.10.49 instalada; preparación 0.10.50

La base confirmada es main `a3bd52b541868bce498107e9f6a19787db03bbbf`,
[PR126](https://github.com/jlboper/Crypto-BOT/pull/126).
[Publicación39615774170](https://github.com/jlboper/Crypto-BOT/actions/runs/39615774170)
y [seguridad39615774421](https://github.com/jlboper/Crypto-BOT/actions/runs/39615774421)
finalizaron correctamente en Linux y Windows. Corte21Oct2026 20:25–20:27UTC:
Ed25519 válida,229/229 archivos, journal COMMITTED, un motor5016/agente14328,
11/11 módulos del agente y dos sincronizaciones HTTPS distintas verificadas.
Spot8/Futures6 con8/8 y6/6 protecciones ARMED y cantidad desprotegida observada cero.
Pulse/Quant SHADOW; Guardian LEVEL0 sin autoridad. Es una observación fechada.
Las172972 filas previas de11 tablas conservaron cero cambios o ausencias;
configuración, credenciales y settings preservaron hashes. No es una captura
atómica de toda la cuenta Binance. Research21Oct13:50UTC COMPLETED permanece archivado.

La candidata50 prepara evaluación RO de migración y viabilidad de costes SIM.
No habilita LIVE ni programa activación a30 días. Capital propuesto por el dueño
no significa fondos asignados; pérdida diaria, drawdown, ámbito de motores,
cuenta, reconciliación y autorización final se validan por separado.
Los spans legacy no son cohortes continuas certificadas. Pulse/Quant necesitan
su propia evidencia y el protocolo común de capital sigue sin admisión efectiva.
La alerta Futures de riesgo inclusivo observado9.308 frente al límite7.5USDT
no se resuelve elevando topes. Ver [Preparación de migración](LIVE_MIGRATION_PREPARATION.md)
y [Auditoría de evidencia](LIVE_MIGRATION_EVIDENCE.md).
Pruebas, PR, CI, publicación, firma e instalación50 requieren comprobaciones nuevas.
Las secciones anteriores y posteriores de versiones previas son historia fechada.

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

# Project Handover — Crypto AI Trader

This is the durable context entry point for a future engineer or AI model taking over this repository.

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

## Read first

Read, in this order:

1. `AGENTS.md`
2. `PROJECT_HANDOVER.md` (this file)
3. `WORK_CONTEXT.md`
4. `UPDATE_NOTES.md`
5. `BOT_RELEASE_OPERATIONS.md`
6. `BOT_UPDATE_PROGRESS.md`
7. `README.md`
8. `RESEARCH_METHODOLOGY.md` and `STRATEGY_EVIDENCE.md` when changing financial logic

Then inspect current `main`, recent commits, open PRs/issues and CI. Documentation is historical context, not proof that a release is currently published or installed.

## Mission

### Historical preparation — 0.10.43 Guardian RO WAL corrective

Start from installed main 42 `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`,
[PR #119](https://github.com/jlboper/Crypto-BOT/pull/119).
[Publication 39181606398](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
and [safety 39181606401](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
succeeded. Audit 2026-10-19 00:42:33 UTC verified Ed25519, 188/188 installed hashes
and five web assets. Engine 3680: Spot 1/Futures 5, native ARMED, zero observed
unprotected quantity. Agent inventory was 9/11 at that cut. Signed refresh at
**00:54:20 UTC** verified agent 21344, **11/11 modules**, sync_ok and two fresh
healthy heartbeats; engine 3680 unchanged, Spot 1/Futures 5 ARMED, zero unprotected
quantity observed.

42 Guardian actual status: PARTIAL, 0/4 sources valid, all UNKNOWN with
WAL_SIDECARS_UNAVAILABLE. One real journal record replays MATCH. A real AI attempt
FAILED without known usage or classified cause. Do not infer quota/credit issues
or claim full acquisition success from installation, replay or synthetic tests.

Corrective branch `fix/guardian-readonly-wal-v01043` must allow normal SQLite
mode=ro/query_only observation when WAL/SHM sidecars have been normally cleaned.
Transient WAL/SHM metadata is allowed; financial DML, constructors, migrations,
immutable copies, stale snapshots and relaxed causal/freshness checks are not.
Test quiet DB/WAL financial preservation and current commits under concurrent
writers. Add a deterministic all-UNKNOWN prefilter before any AI call and safe
bounded error classifications, never provider bodies/headers/secrets. 43 full
Python passed; PR/main CI/publication/signature/install/runtime are pending. 42 test
counts remain historical.

At 00:47:04 UTC, candidate43 read standard SQLite RO backups of all four actual
schemas from temporary copies: FRESH/complete, Spot 1/Futures 5/Pulse 1/Quant 0 and
descriptive SIDEWAYS. No engine/provider/credential loader ran. Copies were removed;
this is actual-schema candidate proof, not installed 43. Focused capture/service
87 PASS and isolated all-UNKNOWN no-AI 1 PASS. Additional 43 results: AI 35 PASS
(6.961 s), Node 180/180 PASS (106.485 s), Windows PowerShell 5.1 lifecycle/view,
portal build and diff PASS. Full offline Python **777/777 PASS**, no failures/
errors/skips, **238.609 s** (`TEST_RESULTS.json`, 00:55:17 UTC), external network
blocked and no bot started. These local results do not establish installed 43.

Keep the four financial ledgers, controls and protections intact. Capital Protocol
Lab remains an external synthetic prototype, excluded from 43. It does not observe
common immutable engine proposals, reserve existing funds or complete phase 3.

### 0.10.42 Guardian Intelligence Shadow — historical preparation record

Start from main `022fb9135d165d5c52f12b65aa9628ab8c1436af`, 0.10.41,
[PR #118](https://github.com/jlboper/Crypto-BOT/pull/118). Its publication
[39134814222](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814222)
and safety [39134814202](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814202)
succeeded; signature/installation matched 178/178 hashes. At 2026-10-18
14:16:30 UTC engine PID 19240 retained one Spot/nine Futures positions, native
protections ARMED and no observed unprotected quantity. Agent PID 9372 had fresh
HTTPS sync and 11/11 modules. Compared existing financial rows had zero missing/
changed rows; secrets, risk and hypotheses were preserved. This is dated 41 evidence.

Candidate 42 implements observational Guardian Intelligence inside that process,
strictly SHADOW LEVEL 0. Four read-only acquisition adapters avoid all financial
ledger constructors/migrations; incomplete inventories stay unknown. Each source
keeps its own timestamps, so this is not a globally atomic pre-submit snapshot.
Pure deterministic diagnostics, a descriptive BTC 60m/61-close proxy and a
separate append-only `guardian-shadow.db` journal/replay have no order hooks,
capital reservations, veto or financial control. Preserve `guardian-ai.db` too.

The owner requested Guardian AI and authorized existing-key reuse with a separate
consumption limit. The optional advisory client is wired up to two attempts/day,
one-hour minimum interval, historical 900 s cache, 4,096-byte input, 512 output
tokens and eight-second HTTP timeout, subject to global `ai.enabled`. Its own
durable claims remain consumed after failures/unknown outcomes. Pricing estimates
use the existing verified model; incomplete usage stays unknown and estimated
reserves are not hard billing caps. No actual installed 42 model request has been
verified yet; focused checks used fake transport/credentials. This authorization
is for observation only, not level 1/Control or capital sharing.

Eight closed local browser query intents now explain summary, regime, scoped risk,
conflicts, data quality, original review, limitations and unknown counterfactuals.
They read the displayed assessment, cite its cutoff and included journal identity,
and invoke no API/SQL/tool. Six browser-tab query identities are ephemeral, not
durable audit. General server-side NL/history queries remain pending.

Complete local validation passed **767/767 offline Python tests (361.510 s)**,
**180/180 Node tests (85.515 s)**, Windows PowerShell 5.1 lifecycle/view, portal
build and diff checks. Regressions cover UTC precision, numeric heartbeat metadata
and canonical integer/SQLite-REAL journal hashing without relaxing causal checks.
Browser QA at 1366/360/768 px found no horizontal overflow and exactly one Guardian
workspace; counterfactual queries stayed UNKNOWN and cited real journal identities.
Local logs are `python-full-v01042.log`, `node-full-v01042-final.log` and
`windows-v01042.log` in the isolated command-center work directory.

The 19:10 UTC baseline audit again verified installed 41's 178/178 hashes, engine
19240, agent 13056, one Spot/nine Futures positions, native protections ARMED and
zero observed unprotected quantity. See `COMMAND_CENTER_2_0.md` for typed reports
and future phase-3 design. PR/main CI, publication/signature, installation and
operative verification of 42 remain pending. Individual Spot/Futures AI,
protection, budgets and signed recovery remain authoritative.

### 0.10.41 Command Center foundation — historical preparation record

Start from main `81ba4366cf587c16cae20d403974a340080c4d10`, 0.10.40,
[PR #117](https://github.com/jlboper/Crypto-BOT/pull/117). Its publication
[39089416208](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416208)
and safety [39089416215](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416215)
succeeded; signed installation was verified 178/178 hashes at 2026-10-18 02:27 UTC.
That is predecessor evidence, not proof of 0.10.41 publication or installation.

Read [COMMAND_CENTER_2_0.md](COMMAND_CENTER_2_0.md) for the audited component map,
typed future contracts, authority levels and phase checkpoints. Candidate 41
reorganizes existing shared-web/Windows presentation only. Seven views retain
current authenticated controls and environment-scoped financial evidence. No new
AI request, capital allocator, reservation or trading admission hook is added.
Guardian Intelligence (phase 2), Capital Manager Shadow (phase 3) and expressly
authorized future Guardian Control are separate from today's pure Observer.
The `ExposureCoordinator` prototype has no production caller; it does not protect
shared account capital. Never enable shared Spot/Pulse funds from that scaffold.

Phase-2 blocker: Guardian's pure function has no E/S, but current snapshot
acquisition constructs `FuturesTestnetLedger`, which can initialize/migrate the
database and set WAL. Implement an explicit ≤1 s read-only adapter before frequent
Guardian supervision; preserve each source timestamp because multi-ledger reads
are not one atomic transaction. Do not claim an exact cross-engine decision view.

Preserve `AIAdvisor`: Spot ALLOW/REJECT/REDUCE, Futures ALLOW/REJECT. Individual
review and all existing deterministic limits remain; protection/recovery must not
depend on Guardian or AI. No autonomy level, risk state, NL query service, LIVE
executor or counterfactual effectiveness claim is implemented by this foundation.
Each later phase needs its own implementation, tests, publication/signature,
installed inventory and operating evidence. Future level changes require owner
authorization and validation; routine signed-release policy remains unchanged.

### 0.10.40 closed-minute diagnostics — historical preparation record

Based on verified signed/installed 0.10.39 main
`2328f2959dc9b4fb939e889519b59a19e5a58423`, 176/176 hashes. Publication
39070205949 and safety 39070205944 succeeded; agent matched 11/11 modules and
four observed Quant ticks stayed fresh (maximum observed age 60.85 s).
Candidate 0.10.40 addresses observed gapped
StatArb snapshot history with a separate append-only store of up to 500 closed
Spot minute bars per BTC/ETH/SOL refresh. Preserve each bar's first actual receipt
and decision-cutoff availability. Never interpolate old snapshots, rewrite their
gaps, use an open bar or treat its earlier close as earlier local knowledge.
These are retrospective diagnostics, not prospective OOS/backtest validation.
StatArb entries stay blocked; Shadow, risk and Guardian Observer authority remain.
Batch premium-index requests retain the existing 15-request/minute ceiling.
Full suites/CI, publication/signature and installed evidence for 0.10.40 are pending.

### 0.10.39 signer availability — preparation record

Main 0.10.38 `a94f1124d57439e90620f4b2d5c02cbb07f53f58` passed CI, but
publication attempts 1/2 failed with 403 `publisher_revision_unavailable`.
No signed/installed 0.10.38 is verified; Windows remains on verified 0.10.37,
176/176 hashes. The underlying GitHub HTTP cause, including quota, is unconfirmed.
Candidate 0.10.39 adds sanitized diagnostics and bounded availability retries
using the same manifest/OIDC token with at most 105 seconds of cumulative backoff
and seven requests with 30-second timeouts. All OIDC,
authorized workflow, exact current-main and deployed-revision checks remain.
Superseded or invalid identities never become retryable authorization successes.
Retain the 0.10.38 cadence fix and all financial state. Full checks, CI, protected
publication/signature and installed audit of 0.10.39 are pending separately.

### 0.10.38 cadence — preparation record

Version 0.10.37 main `3b02326c435acf3c9c666940a90923908e9bab64` was observed
signed and installed with 176/176 hashes. Post-install observation found Quant's
start-anchored scheduler could hit its strict 60-second reference cache slightly
early and reuse aging data. Version 0.10.38 schedules 60 seconds after completion;
it does not weaken the 90-second freshness gate or increase the API budget.
Slow/failed sources still degrade explicitly. Preserve all ledgers/journals and
existing protections; this changes no strategy, risk or execution authority.
Full checks, CI, publication/signature and installation of 0.10.38 remain pending.

### 0.10.37 implementation — preparation record, four engines

Verified predecessor: 0.10.36 main `1bb77fad1a490472907ce29591e0b1075d3e7ba3`,
PR #113, signed and installed 167/167 hashes. Version 0.10.37 is preparation only
until its own full suites, CI, main publication, signature and installed audit pass.
See `FOUR_ENGINE_EXPANSION.md` for Quant's independent Shadow ledger/service,
two-leg costs, funding provenance, entry-loss latches and strict execution block.
Funding Carry may open hypothetical pairs; StatArb remains an exploratory screen
with entries blocked pending independent calibration. Guardian remains Observer
without veto/reservations. Public Futures prices are reference observations, never
Demo fills. No trading-account client, paid provider or AI call is added by Quant.

Keep `data/quant-shadow.db`, source evidence, journals, hypotheses and pause/kill
state across updates/recovery. Unknown or late funding must not become income or
a zero valuation. Global and per-engine data remain separate; no actual shared
capital is allocated. Pause controls carry empty authenticated requests through
the existing agent; remote Quant capability is distinct from Spot control rights.
Never start another trading process to refresh the four-card Windows indicator.

### Third engine introduced by 0.10.31

Version 0.10.34 expands the reviewed Shadow observation universe to ten eligible
nonstable Binance Spot USDT assets with a frozen dated cap selection, five primary
RSS providers and deterministic candidate priority. Old journal/wallet survives an
audited additive hypothesis transition; risk/cost changes remain rejected. Native
folds compact long portal sections. The owner next requested Guardian Observer
and Quant Arbitrage; see `FOUR_ENGINE_EXPANSION.md`, with no veto/promotion implied.

AI Market Pulse observes public BTC/ETH/SOL trades, depth and bounded official
events inside the existing supervised process, after signed activation. It owns
`data/market-pulse.db` and an independent pause marker; `market-pulse-ai.db`
persists its separately capped model attempts. It is strictly SHADOW with no
broker or execution/promotion toggle. See `MARKET_PULSE.md` for hypotheses,
financial limitations, provider costs, research and promotion requirements.
Never combine its hypothetical capital/results with Spot Testnet or Futures Demo.
The shared-account coordinator is preparation only; existing Spot does not use
its reservation protocol. Therefore sharing Testnet capital remains blocked.
The optional remote projection and controls must evolve with the Worker validator.
Release 0.10.31 was observed signed and installed with 160/160 hashes on 2026-10-16.
Version 0.10.32 corrects the Ethereum RSS URL to its official direct `/en/feed.xml`
destination; redirected feeds remain rejected. Always verify the current release,
installation and source freshness independently.

Crypto-BOT is a safety-first crypto trading research and execution project. Its purpose is to test systematic strategies with explicit risk controls and strong recoverability before any consideration of production capital.

The current architecture intentionally separates:

- **Spot Testnet**: primary multi-asset test environment.
- **Futures Demo**: separate LONG/SHORT forward test with its own ledger, journal, risk controls and kill switch. Version 0.10.27 observes fifteen USDT perpetuals, allows up to ten positions, and sizes against 300 USDT gross exposure and 7.5 USDT estimated loss-to-stop (including cost reserve). Confirmed entries alternate 1x/2x/3x without multiplying quantities; actual fills/gaps can exceed pre-submit estimates. Expanded open state prevents incompatible code restoration.
- **PAPER**: regression, CI and technical fallback.
- **Market Pulse / Quant SHADOW**: separate hypothetical ledgers; no exchange
  execution. Quant's 0.10.40 foundation is installed/verified; current liveness
  and data quality still require fresh runtime evidence. StatArb remains blocked.
- **LIVE**: intentionally not implemented. Never infer that observed profitability authorizes production trading.

## Architectural invariants

- One supervised trading process; do not create a second engine accidentally.
- Spot and Futures remain financially and operationally separate.
- SQLite ledgers, journals, kill switches and rollback state are persistent assets; visual cleanup must never delete them.
- OpenAI acts only as a final risk gate for candidate entries. It must never create a trade by itself, increase risk, remove stops, or block protective exits/recovery.
- Secrets stay outside Git and outside shared backups.
- Local and remote portal use the same `web/` assets.
- Signed updates, anti-downgrade sequence, health checks and rollback are part of the safety architecture, not optional convenience.
- Release state is always distinguished as **prepared → merged → published/signed → installed/verified**.
- Changes to strategy/risk require evidence; operational/security fixes may happen immediately.

## Why the project looks this way

The project evolved from PAPER-only experimentation into a supervised Windows installation with a private remote portal, signed updates, Spot Testnet and a separate Futures Demo forward test. Several design choices exist because earlier approaches exposed failure modes:

- Remote-agent continuity used to depend too heavily on a Windows/PowerShell chain. The current 0.8.13 architecture runs the scheduled remote agent directly with `pythonw.exe` and requires repeated healthy heartbeats after self-heal.
- Runtime ambiguity previously caused updater/agent import failures. The updater now reuses the supervisor's Python runtime.
- Portal/local UI divergence was deliberately removed; there should be one shared interface.
- Testnet and PAPER histories are intentionally separate to avoid contaminating financial interpretation.
- Futures was promoted from smoke testing into a persistent forward test but remains isolated from Spot and from any LIVE path.

See `UPDATE_NOTES.md` for the detailed chronological record.

## Mandatory check after the 0.10.14 agent incident

Read the 2026-10-03 incident in `PROJECT_HISTORY.md` before changing the independent supervisor. The signed bot installation and the scheduled agent's `WorkingDirectory` are separate roots: a dependency present in the bot can still be absent from the agent. New supervisor imports must appear in both `scripts/refresh_independent_agent.py::MODULES` and `scripts/windows_agent.py::SUPERVISOR_MODULES`. Preserve the inventory-parity test and the real refresh/import test in `tests/test_agent_refresh.py`; imports must succeed from the refreshed root under isolated Python without the source checkout.

For a connection failure, inspect the existing scheduled task's root and `data/remote-status.json` (`sync_ok`, `error_type`, `at`, `last_success`). Task state `Running`, copied files and a version label do not prove connectivity. Repair success requires two distinct fresh successful syncs and no `SUPERVISOR_UNAVAILABLE` degradation. A dependency failure may block startup recovery before optional-metadata fallback runs; restarting the same incomplete agent cannot repair its files.

Recover missing code only from a committed signed installation with matching version, anti-downgrade sequence and expected SHA-256 inventory. Stop/restart only the existing agent task; preserve the engine, journals, credentials and financial data. Fail closed if those checks disagree. Two tray icons are not proof of two trading engines. An already running old indicator keeps old code after an update; use **Salir del indicador**, then reopen it once to load the 0.10.15 ownership guard.

Protected publication of 0.10.15 was verified in GitHub. After the verified dependency recovery, the owner reported installation of 0.10.15 and restored connection. That report does not independently verify two fresh heartbeats, a single indicator or native exchange protection; collect those separately when operational evidence is available.

## Current decision posture

Version 0.10.14 implements native protection in both Testnet motors. `native_protection.py` owns durable Spot OCO and Futures conditional-order journals, queries ambiguous submissions by client identity, reconciles native executions before ordinary close/open logic, and retains journals until sibling cleanup is confirmed. Integration support is separate from per-position ARMED evidence. Preserve journals across updates; code lacking native protocol 1 must not resume while native reconciliation remains pending. Trailing OCO replacement is cancel/confirm/create, not atomic. Existing histories remain; `native_protection_started_at` marks the new observation phase. LIVE remains blocked and real Demo behavior must be observed after installation.

The present phase is observation, stability and evidence collection. Avoid changing strategy, leverage or risk because of a few days of results. The project should accumulate enough clean forward-test data to support a later review.

A future decision to use real funds must be a separate project phase with explicit design and safety review. It must not be activated by a version bump, a configuration toggle, an AI recommendation or a good backtest.

## Future ideas already considered

These are ideas, not commitments:

- Longer Spot vs Futures forward-test comparison with comparable scorecards.
- Observe native protection during Demo operation, including offline fills and reconnection.
- Continued hardening of Windows supervisor/recovery and host portability.
- Migration to another Windows PC, Linux host or managed environment without changing trading semantics.
- Android/mobile experience for monitoring and alerts, with independent mobile authentication; never reuse the Windows device credential.
- Better notifications and operational alerting.
- Research strategy promotion only through the existing evidence pipeline.
- Eventual production-capital architecture only after explicit review, with separate credentials, limits and deployment path.

When implementing any old idea, first verify it is still appropriate against current code and current owner intent.

## Handover checklist for a future AI

Before proposing changes:

1. Identify the exact current version and commit on `main`.
2. Inspect the most recent release notes and recent commits.
3. State what is code, what is published, and what is actually installed separately.
4. Inspect tests and CI before changing architecture.
5. Preserve all safety invariants above.
6. Do not expose or request secrets in chat if a secure local configuration path exists.
7. Prefer a small reversible PR over a broad rewrite.
8. Record meaningful architectural decisions in this file or `PROJECT_HISTORY.md`, and implementation details in `UPDATE_NOTES.md`.

## Reconstructing elsewhere

See `PORTABILITY.md` and the bootstrap scripts. A new host should be reproducible from:

- approved GitHub code/release,
- separately transferred secrets,
- separately restored persistent state if desired,
- host-specific supervisor setup.

The current machine must never be the only place where knowledge required to operate or recover the project exists.
# 0.10.35 prepared — Guardian Observer

Main0.10.34 (06de9109a0ae49ffbdb5f94bc6310a9239f421fc) was published/signed and
installed162/162 with native Futures protections and fresh authenticated device
sync. Next PR adds pure read-only Guardian diagnostics and optional four-engine
contracts. Quant remains NOT_STARTED; four-card UI and Quant Shadow follow in
separate PRs. Do not call Observer from financial cycles or treat it as allocation
enforcement. Verify prepared/merged/published/installed independently.
# 0.10.36 prepared — four-card shared UI and Windows

Based on merged0.10.35 maincf3eec5a9e310f4162e0b9edcd2c9a2f4dc2f9e6. Portal and
Windows now represent four identities plus a separate Observer, with no invented
Quant performance. Quant simulation and Guardian Control remain future stages.
Reload only the indicator after installed signed-inventory verification; never
start another trading engine to update its appearance. Keep release states explicit.
