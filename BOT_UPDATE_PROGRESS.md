## 0.10.53 — auditoría Futures V3 en preparación

52b110b7e PR129 publicada, firmada e instalada255/25523Oct22:39UTC;
publicación40033473861 intento2 y seguridad40033473866 SUCCESS Linux/Windows.
259816 filas/11tablas y hashes de configuración/credenciales preservados;
CapitalFlow16/16 y RiskLatches9/9 instalados PASS SIM, agente11/11 y dos HTTPS.
53 corrige la falsa exigencia de canTrade en el auditorGET Futures V3,
sin certificar permisos ni añadir rutas/ejecución. Spot conserva su validación.
Pruebas/CI/firma/rollout53 pendientes. GuardianL0; Pulse/QuantSHADOW.

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

## 0.10.51 — presentación de intervalos (en preparación)

Base main50 `df12f1d625503eed6e77ffc98ea50954ed97307a`,
[PR127](https://github.com/jlboper/Crypto-BOT/pull/127).
Publicación39707960453 y seguridad39707960358 SUCCESS en Linux/Windows.
A22Oct2026 01:57–01:59UTC: Ed25519válida,237/237hashes,COMMITTED/RUNNING,
único motor24484/agente22748,agente11/11 y dos HTTPS distintos correctos.
Spot8/Futures6 con14/14ARMED y cantidad desprotegida observada cero.
183170filas previas/11tablas,configuración,credenciales y settings congelados
preservados; Research archivado conserva hashes. Es una verificación fechada,
no captura atómica de toda cuenta Binance. Guardian LEVEL0, Pulse/Quant SHADOW.
Una respuesta GuardianIA ordinaria22Oct00:00UTC fue aceptada; la de01:00UTC
se rechazó por CAUTION_BOUNDS. No se forzaron llamadas ni se relajaron validadores.

La candidata51 corrige exclusivamente la representación de días de observación:
máximo dos decimales, truncados para evitar mostrar30 cuando el intervalo aún es
29.999. Conserva valor original,umbral,contrato,fuentes,gates,límites y protecciones.
No activa modos financieros. PR/CI/firma/instalación51 requieren comprobación propia.

Validación local final51:1099/1099Python offline PASS193.141s a22Oct02:08:53UTC,
263/263Node PASS43.290s,build compartido ydiff-checkPASS. La prueba de frontera
se actualiza de29.999bruto a29.99visual conservando el dato original y su bloqueo.
No se relajan validadores ni se modifican decisiones. CI/publicación/instalación51
requieren evidencia nueva;50 permanece la última instalación comprobada aquí.

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


## Validación local de la candidata50

Python offline final: **1099/1099 PASS**,139.719s,22Oct2026 01:40:43UTC,
sin fallos, errores o skips; claves vacías, red externa bloqueada y ningún bot iniciado.
Node final: **262/262 PASS**,56.772s, incluidos autenticación/CSRF, Worker/D1,
contrato compartido cerrado, rechazo de autoridad y compatibilidad con snapshots
anteriores. PS5.1 lifecycle/vistas y build compartido PASS. La primera corrida
Node detectó una expectativa del test que preservaba -0 mientras JSON transmite0;
se corrigió la expectativa al formato transportado, sin cambiar datos financieros.

QA sintética: panel plegable en escritorio1265px y móvil360px; anchura documento
345/345 en móvil, cuatro tarjetas y propuesta explícita sin asignación. Detalle
abierto conservado al refrescar y repliegue por teclado comprobados. Sin APIs
externas, POST403 y ninguna instancia de TradingEngine. No acredita UI instalada
ni acceso de propietario remoto. CLI de costes ejecutada: una hipótesis compatible
y otra rechazada por mínimo nocional, ambas sin autoridad ni financiación conjunta.

Proyección candidata RO sobre instalación49 a21Oct20:55:16UTC:479577bytesASCII
y cuatro detalles recientes del observer59; conserva matrizResearch,Guardian,
CapitalLab,protecciones y preparación.205sentenciasSQLite,cero mutaciones y cero
llamadas a proveedores/IA; el harness evita constructorDDL y lockResearch, por lo
que no sustituye una petición HTTP real ni prueba de sincronización autenticada.

El propietario pidió preparar Spot y Futures con perfil algo más agresivo. Los
porcentajes sugeridos son un borrador privado; no hay aprobación de límites exactos
ni activación de dinero real. Pulse y Quant conservan sus validaciones separadas.
CI, publicación, firma e instalación50 permanecen pendientes a este checkpoint.

## 0.10.49 en preparación — instalación48 y nuevo estudio verificados

**0.10.48 está publicada, firmada e instalada**: main
`0270057f59d67362a6cff2851d138e0cc765155d`,
[PR125](https://github.com/jlboper/Crypto-BOT/pull/125).
[Publicación39609237309](https://github.com/jlboper/Crypto-BOT/actions/runs/39609237309)
y [seguridad39609237234](https://github.com/jlboper/Crypto-BOT/actions/runs/39609237234)
aprobaron Linux y Windows. Entre21Oct2026 **13:41–13:44UTC** se verificaron Ed25519,
**228/228 archivos**, agente11/11 y dos sincronizaciones HTTPS correctas.
Las **172145 filas** de referencia conservaron cero ausencias/cambios;
configuración, credenciales y settings mantuvieron sus hashes. Son verificaciones
fechadas, no una captura global atómica ni prueba de todas las filas posteriores.

Research terminó **COMPLETED a13:50:14UTC**:24/30 activos Spot y15/15 Futures.
Seis activos Spot quedaron excluidos con categoría `ValueError`; no se atribuye
una causa específica que el informe no conserva. El nuevo archivo incluye matriz
de cuatro motores, replay Pulse acotado a1000 decisiones sin divergencias y
16/16 modelos Quant coincidentes en su muestra. El archivo previo del19Oct quedó
intacto. Metodología presente/replay coincidente no acreditan rentabilidad,
ejecución validada, ventaja OOS independiente o ganancias atribuibles a IA/Guardian.

Después del estudio se observó en48 una proyección remota de **474183 bytes**
con serialización ASCII predeterminada y **441792 bytes** de transporte que omitía
`opportunity_shadow`. La menor huella de transporte no aumenta el límite de
validación ni demuestra una caída del observador o de los motores.

La candidata49 prepara historial remoto adaptativo: probar de seis a cero registros
recientes y conservar el mayor prefijo que quepa, retirando primero el detalle más
antiguo. Mantiene **480000 bytes** como límite de serialización ASCII predeterminada.
Conserva sin recortar la base, `health`, `coverage`, `scopes`, permisos y
evidencia de protecciones. Si ni con cero detalles cabe, conserva la omisión
opcional reconocida; no fuerza una proyección inválida.

La UI diferencia cero registros en el journal de cero detalles incluidos en esa
proyección. El SQLite y el detalle habitual local no se recortan para reducir el
envío remoto. No cambian contratos públicos, APIs, autoridad, trading o riesgo.
Pulse/Quant permanecen SHADOW y Guardian LEVEL0, sin promociones o LIVE.

Validación local49: **1061/1061 Python offline PASS**198.282s,21Oct14:10:29UTC,
sin fallos/errores/skips, red externa bloqueada y bot no iniciado; **245/245 Node
PASS**90.126s, PS5.1 lifecycle/vistas, build/diff PASS. Nueve regresiones Python
y tres UI cubren prefijo máximo, límite exacto/Unicode, resumen sin detalle,
omisión inevitable, ausencia de mutaciones y distinción entre vacío/desconocido.
Probe RO secuencial14:05:22–23UTC:48omite el observer con474217bytes; candidata49
incluye3recientes de37 con479616bytes, misma matriz y protecciones,0SQLmutaciones.
No es sesión remota autenticada ni una captura global atómica. CI del head/main,
PR, publicación, firma e instalación49 aún requieren verificación propia.
Las secciones inferiores conservan historia.


## 0.10.48 — Research Windows en preparación; checkpoint47 verificado

Base confirmada **0.10.47 publicada, firmada e instalada**, main
`216c8232e50903627ff541b52befdb8494cac4e8`, [PR124](https://github.com/jlboper/Crypto-BOT/pull/124).
[Publicación39532789868](https://github.com/jlboper/Crypto-BOT/actions/runs/39532789868)
y [seguridad39532789801](https://github.com/jlboper/Crypto-BOT/actions/runs/39532789801)
aprobaron Linux y Windows. Entre21Oct2026 **02:35–02:38UTC** se verificaron
Ed25519, **227/227 archivos**, agente **11/11** y dos sincronizaciones HTTPS
distintas correctas. Las **154485 filas** de referencia conservaron cero
ausencias/cambios. Spot5/Futures7 mantenían protecciones ARMED en ese corte;
son observaciones fechadas y no acreditan el estado actual de los motores.

El arranque real de Research a02:38UTC falló con `WinError5` al reemplazar
su JSON de estado. Se reprodujo un escenario con un lector sintético sin cambiar
ACL. La identidad del handle que originó el incidente operativo no se determinó.

La candidata48 usa temporales exclusivos por escritura en el mismo directorio,
flush/fsync y cierre antes del reemplazo. Sólo reintenta los errores Windows5/32/33:
hasta cinco reintentos, con **310ms de espera acumulada**; el tiempo de E/S se suma
a esa espera. Si persiste el error, conserva el JSON anterior. La limpieza se limita
al temporal de esa invocación; nunca borra el destino ni cambia permisos para
forzar el reemplazo. No modifica scheduler, IA, trading, riesgos o protecciones.

La matriz Research47 se adjunta sólo a un estudio nuevo completado. El informe
histórico del19Oct conserva la evidencia disponible entonces y no se enriquece
retrospectivamente con observaciones posteriores. Instalar47 no acredita que ese
nuevo estudio haya finalizado. Pulse/Quant siguen SHADOW y Guardian LEVEL0;
no se habilitan Control, reservas efectivas, promociones o LIVE.

Validación local48: **1052/1052 Python offline PASS**145.156s,21Oct13:26:59UTC,
sin fallos/errores/skips, red externa bloqueada y ningún bot iniciado;
**242/242 Node PASS**34.309s, PS5.1 lifecycle/vistas, build/diff PASS.
Diez regresiones nuevas incluyen un lector Windows real, fallos de serialización,
E/S, fsync y reemplazo, reintentos selectivos/acotados y escrituras concurrentes.
CI del head/main, PR, publicación, firma e instalación48 requieren verificación
propia y permanecen pendientes. Los bloques inferiores conservan historia.


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

# Historical candidate43 — Guardian RO WAL corrective

Installed baseline: 42 main `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`,
[PR #119](https://github.com/jlboper/Crypto-BOT/pull/119).
[Publication 39181606398](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
and [safety 39181606401](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
SUCCESS. At 2026-10-19 00:42:33 UTC Ed25519, 188/188 installed hashes and five
web assets matched. Engine 3680: Spot 1/Futures 5 native ARMED, zero unprotected
quantity observed. Agent inventory was 9/11 then. At **00:54:20 UTC** signed
auto-refresh was verified: agent 21344, **11/11 modules**, sync_ok and two fresh
healthy heartbeats. Engine 3680 unchanged, Spot 1/Futures 5 ARMED and zero observed
unprotected quantity.

42 is installed but Guardian acquisition is not fully verified: PARTIAL with 0/4
valid sources, all UNKNOWN/WAL_SIDECARS_UNAVAILABLE. The first actual journal
record replays MATCH. One real AI attempt FAILED with unknown usage/cause; no
quota or credit diagnosis is substantiated.

43 permits normal SQLite RO/query-only reads with transient WAL/SHM metadata,
without financial DML or requiring persistent sidecars. Preserve current commits,
source freshness, causal checks, data and protections; no immutable-copy shortcut.
A deterministic all-UNKNOWN filter precedes AI; safe codes replace opaque errors
without exposing provider bodies/secrets. PR/main CI/publication/signature/
installation/runtime 43 remain pending. Capital Protocol Lab stays an external
synthetic prototype and is excluded from this corrective release.

00:47:04 UTC candidate43 actual-schema check used standard SQLite RO backups
into temporary copies: all four FRESH/complete, positions 1/5/1/0, descriptive
SIDEWAYS, no engine/provider/credential loader. Copies removed; not installed 43
proof. Focused capture/service 87 and isolated no-AI 1 tests PASS. Additional local
43 checks PASS: AI 35 (6.961 s), Node 180/180 (106.485 s), Windows PowerShell 5.1
lifecycle/view, portal build and diff. Full offline Python **777/777 PASS,
238.609 s**, no failures/errors/skips, external network blocked and no bot started
(`TEST_RESULTS.json`, 00:55:17 UTC). PR/main CI/publication/signature/install/runtime
remain pending.

# 0.10.42 Guardian Intelligence Shadow — historical preparation record

Prepared from main `022fb9135d165d5c52f12b65aa9628ab8c1436af`, 0.10.41,
[PR #118](https://github.com/jlboper/Crypto-BOT/pull/118), published/signed and
installed 178/178 hashes. [Publication 39134814222](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814222)
and [Linux/Windows safety 39134814202](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814202)
succeeded. At 2026-10-18 14:16:30 UTC engine PID 19240 retained one Spot/nine
Futures native-protected positions with no observed unprotected quantity;
independent agent PID 9372 had fresh sync and 11/11 modules. Compared previous
financial rows had zero missing/changed rows; secrets/risk/hypotheses remained.

Candidate 42 implements Shadow Level-0 observation only: bounded RO capture of
four ledgers, pure descriptive diagnostics, independent append-only Guardian
journal, lease/recovery and frozen causal replay. Optional authorized advisory
AI has its own two-attempt/day cap, hour interval and historical cache, gated by
global AI configuration; no order, veto, reservation or admission hook exists.
No actual installed-42 model request is verified. Estimates are not billing caps.

Eight local closed read-only query intents now explain the displayed assessment
with cutoff/journal evidence; six browser-tab query identities are not durable
audit. General server-side NL/journal querying remains pending.

Complete local validation passed **767/767 offline Python tests (361.510 s)**,
**180/180 Node tests (85.515 s)**, Windows PowerShell 5.1 lifecycle/view checks,
portal build and diff checks. UTC precision, numeric heartbeat and int/SQLite-REAL
digest regressions are covered without relaxing causal checks. QA at 1366/360/768 px
found no horizontal overflow and one Guardian workspace. Logs:
`python-full-v01042.log`, `node-full-v01042-final.log`, `windows-v01042.log`.
At 19:10 UTC installed 41 again matched 178/178 hashes, engine 19240/agent 13056,
Spot 1/Futures 9 native-protected positions and zero observed unprotected quantity.
42's PR/main CI, protected publication, signature, installed inventory and
operative verification remain pending.
Preserve current financial data, individual controls, protections and signed flow.
See `COMMAND_CENTER_2_0.md`; Capital Manager and Guardian Control remain future.

# Candidate — 0.10.41 Command Center foundation (historical preparation record)

Prepared from current main `81ba4366cf587c16cae20d403974a340080c4d10`,
0.10.40, [PR #117](https://github.com/jlboper/Crypto-BOT/pull/117). Predecessor
[publication 39089416208](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416208)
and [Linux/Windows safety 39089416215](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416215)
succeeded; signature and installation were verified 178/178 hashes at
2026-10-18 02:27 UTC. Current operation still requires fresh runtime evidence.

Phase 0 audits existing components and records typed future contracts in
`COMMAND_CENTER_2_0.md`. Phase 1 reorganizes shared portal/Windows presentation
into seven views, without financial effects, new Guardian API calls, risk changes
or execution authority. Capital is scoped observation; Intelligence/Capital Shadow
and future expressly authorized Testnet Control remain separate pending phases.
No production exposure reservation integration exists; do not share account funds.

Candidate 41 implementation and tests, PR/main CI, protected publication,
Ed25519 signature, installed inventory and operative verification are separate
checkpoints. Do not infer completion from predecessor evidence or a version label.
Preserve the updater, activation barrier, independent agent closure and all ledgers.

# Candidate — 0.10.40 closed-minute diagnostic evidence (historical preparation record)

Based on verified signed/installed 0.10.39 main
`2328f2959dc9b4fb939e889519b59a19e5a58423`, 176/176 hashes.
[Publication 39070205949](https://github.com/jlboper/Crypto-BOT/actions/runs/39070205949)
and [safety 39070205944](https://github.com/jlboper/Crypto-BOT/actions/runs/39070205944)
succeeded; independent agent matched 11/11 modules and four observed Quant ticks
were fresh (maximum observed age 60.85 s). Persistent gaps in observed
Quant snapshots require valid closed-bar evidence rather than waiting or
interpolating. Add a separate append-only BTC/ETH/SOL Spot 1m store, up to 500
closed bars per symbol/read, first actual receipt and decision/replay cutoff.
This does not repair snapshot gaps retroactively or create prospective OOS/
validated backtest results. StatArb entries stay blocked. Batch premium-index
reads retain the 15-request/minute cap (planned 14 startup/10 steady calls).
Risk, Shadow-only execution, persistent financial data and signing policy stay.
Full checks, CI, publication/signature and installed evidence for 0.10.40 are
pending separately; predecessor evidence proves none of this candidate's release states.

# Candidate — 0.10.39 signer availability and safe diagnostics (historical preparation record)

Based on 0.10.38 main `a94f1124d57439e90620f4b2d5c02cbb07f53f58`: CI passed,
publication attempts 1/2 failed with 403 `publisher_revision_unavailable`.
No signed or installed 0.10.38 is verified; 0.10.37 remains installed 176/176.
The GitHub HTTP/root cause and possible quota exhaustion remain unconfirmed.
Add sanitized bounded diagnostics and same-manifest/OIDC-token retries only for
availability/propagation with at most 105 seconds of cumulative backoff, seven
requests and 30-second timeouts. Preserve exact current
main, authorized identity/workflow, deployed revision, trust anchor and all data.
The 0.10.38 cadence fix is retained; no trading/UI/risk change. Full suites, CI,
protected publication, latest signed manifest and installed evidence for 0.10.39
must still be verified. An unsigned ZIP or deployed portal is not an installed bot.

# Candidate — 0.10.38 Quant reference cadence (historical preparation record)

Prepared from verified 0.10.37 main
`3b02326c435acf3c9c666940a90923908e9bab64`, signed and installed 176/176 hashes.
Post-install observation detected intermittent stale references when the
start-anchored tick reached the strict 60-second cache slightly before expiry.
Schedule the next tick 60 seconds after completion; retain 90-second freshness,
bounded API use, all financial hypotheses/state and strict Shadow execution.
Full suites/CI, exact main publication/signature, installed hashes and fresh
operating evidence are pending for 0.10.38; do not infer them from 0.10.37.

# Candidate — 0.10.37 functional Quant Shadow (historical preparation record)

Prepared from verified 0.10.36 main
`1bb77fad1a490472907ce29591e0b1075d3e7ba3` (PR #113), signed and installed with
167/167 hashes. Add Quant's optional supervised Shadow service, independent
virtual ledger/journal, conservative Funding Carry, research-only StatArb,
typed bounded remote evidence and authenticated independent pause controls.
Guardian remains Observer without veto. Four cards/Windows show actual initialized
hypothetical state; null/stale finances are never fabricated. No account execution,
strategy promotion, paid provider or existing-engine risk change is introduced.

Focused checks recorded: 70 core, 59 contract, 31 UI, 20 Windows assets and
PowerShell 5.1 view/render. Full offline/Node suites and exact Linux/Windows CI
are pending; publication/signature/installed inventory/operating health must be
verified separately for 0.10.37. Do not report this candidate as released or installed.

# Candidate — 0.10.34 ten-asset/five-source Pulse and compact portal

Prepared from main `815ba27bbe52d2ec3a3f5790caedfc7fe8901a04` (0.10.33),
previously signed and installed. Dated CoinGecko/Binance public probes establish
ten eligible nonstable Spot USDT symbols. Five direct RSS endpoints were verified;
commercial sources with incompatible automated/AI terms are excluded. Add bounded
provider health, deterministic candidate/review priority and additive cohort audit.
Long shared-portal sections become collapsible. Preserve all operating risk,
positions, ledgers, credentials, signed update/recovery and strict Shadow mode.
CI, signed publication, installed inventory and fresh source/sync health require
independent final verification. Four-engine/Guardian work follows on updated main.

# Candidate — 0.10.33 deterministic observer exclusion test

Prepared from verified main `6c3cd3091e9c6f98159526df57a901f2b6098f8c`.
One Linux safety run asserted the private persistent lease before the observer
thread reached it; the main publication's independent Linux/Windows validations
passed on the same source. Synchronize the synthetic stream before that assertion
instead of relying on scheduler order. Production ownership/lease logic is unchanged.
Versioned test files are bundled, so increment the stable release. Verify CI,
publication/signature, installed inventory and current runtime sources separately.

# Candidate — 0.10.32 canonical Ethereum RSS

Prepared from verified main `ef4378fd7ff139b892ffa3bde79c4faa08884e6b`.
Its 0.10.31 signed package was verified and installed with all 160 file hashes
matching, fresh HTTPS sync and existing Spot/Futures positions protected ARMED.
The first live news poll rejected the old Ethereum RSS URL's HTTP 301. Use its
official direct `/en/feed.xml` destination while preserving redirect rejection.
This adjustment changes no trading, risk, credentials or financial persistence.
PR/main validation, signed publication and installed source health remain separate
checks; record actual evidence in the final delivery.

# Candidate — 0.10.31 three-engine portal and Market Pulse Shadow

Prepared from verified main `26d1b33fdb54fb86a05c8c8310c80763110ca02b` (0.10.30).
Baseline read-only audit matched installed signed code hashes and committed journal;
Spot PYTH and Futures BNB/XRP positions reported ARMED native protection and fresh
HTTPS sync. Implement phases A/B and initial C, with D preparation only. Pulse
cannot submit orders or share exchange funds. Owner approved existing-key reuse
with separate bounded AI consumption. `MARKET_PULSE.md` records architecture,
sources, hypotheses, limitations and remaining authorization/evidence gates.
PR CI, main publication/signature, installation and fresh remote projection require
separate verification; source changes alone prove none of those states.

# Candidate — 0.10.30 execution plans and strategy evidence

Prepared from main a61c71c703ed59f8b0a70d9cfa8026623ebae666 after the owner's strategy optimization request. Correct new-entry geometry and preserve original Spot admission bounds; block invalidated Futures setups before and after AI review. Research now uses Futures 1h independently, archives its prior 4h cohort and exposes actual configured signal references without inventing execution returns. The observed weak results and exploratory RSI/extension comparisons do not qualify a new strategy. Validation, protected publication, signed installation and fresh HTTPS health remain separate checks. No operating histories, credentials, positions or risk budgets are edited during development.

# Candidate — 0.10.29 Futures clock pause recovery

Prepared from current main 1a7d9e3ed7878068bbd798bf5b0c39614413bd4d after the 15 October audit. Futures latched `Futures Demo server time response too slow` at 04:22 UTC; subsequent protection succeeded but this exact reason could not auto-resume. The installed supervisor safely resumed it at 15:05 UTC after full reconciliation; the next cycle evaluated all 15 contracts. Spot independently remained operational with 60 below-threshold signals and no pending journal. Add only the exact slow/unavailable Demo clock reasons to the existing audited recovery gate. Preserve clock validation, manual pauses, pending writes, risk and strategy. PR validation, main publication, signature and installed verification are separate checks.

# Candidate — 0.10.28 native filters and remote continuity

Prepared from main 361af475a9d38668d275a5a021228af7c4139bc6 after the 14 October incident. GNS OCO was definitively rejected by PERCENT_PRICE_BY_SIDE; local exits continued with entries blocked. A real 80,545-character Futures view reproduced the 80,000-character Worker rejection. A transient signed-read failure independently left Futures paused despite later confirmed native orders. This release validates protective bands before buys, repairs only definitive rejections after fresh checks, bounds remote history and preserves authenticated update delivery. Automatic read pauses require a complete audit before resume. Financial data, ten slots, leverage and risk budgets are preserved. CI, main publication, signature, installation and two fresh complete HTTPS syncs require independent verification.

# Candidate — 0.10.27 ten positions per bot

Prepared on current main 8cb9cd4874abb8991157c496b576fcbf11a075b1 following the owner's 12 October request. Preserves the installed operational fixes and existing risk/exposure budgets; expands both engine limits and remote snapshot compatibility. Publication, signature, installed limits and two fresh HTTPS heartbeats require independent verification after CI and merge.

# Candidate — 0.10.25 portal evidence audit

Prepared from current main `086fe50c04846a64d685e1b2098cefa6d65537e6` after an authenticated review of the installed 0.10.24 portal. Correct partial/stale Futures status, timestamp contract scores, add comparable financial fields and explicit accounting limitations, expose portfolio budgets and fix six-profile displayed risk. Research now retains safe failure stage/reason and labels the old report's actual coverage; the earlier generic failure's cause remains unverified. Strategies, risk boundaries, trading execution and operational data remain unchanged. See UPDATE_NOTES.md. Local validation passed 331 offline Python tests and 85 Node tests, including partial/stale contract states, dated scores, escaped reasons, six risk profiles and safe research diagnostics. PR validation, main publication/signature and Windows installation are separate gates.

# Candidate — 0.10.24 Futures asset resilience and exact diagnostics

Prepared from main after the owner observed two Futures Demo contracts unavailable while the remaining contracts were healthy. The candidate keeps the 1h/score-70 strategy and all hard risk limits unchanged, retries flat-contract validation every cycle, tolerates incomplete Demo MARKET_LOT_SIZE when LOT_SIZE is valid, and falls back from Demo ticker to Demo mark/index reference only. The portal exposes bounded symbol-level failure reasons so transient Binance Demo gaps can be distinguished from structural contract unavailability. PR validation, main publication, signed rollout and Windows installation remain separate evidence gates.

# Candidate — 0.10.23 faster Futures observation and explicit gate diagnostics

Prepared on the existing 0.10.22 automatic-publication candidate under the owner's authorization after observing many hours without strategy entries. Futures Demo now uses its own 1h candle cadence and score 70 while Spot stays 4h; hard portfolio, stop-loss, leverage, margin-mode and AI gates remain unchanged. The portal projects bounded per-cycle Futures reasons and exact Spot loss-lock period/expiry. PRs still only validate; publication and signing require the current main push after successful Linux/Windows checks. Source, merge, publication and Windows installation remain separately verified.

Local validation passed 325 offline Python tests and 85 Node tests, including real workerd/D1 signing, current-main rejection and authenticated update discovery. GitHub Linux/Windows validation, main publication and Windows installation must still be observed for this candidate.

0.10.21 was signed successfully by run [37182391307](https://github.com/jlboper/Crypto-BOT/actions/runs/37182391307), and the authenticated portal reported completed installation at 00:21:20 Mexico City on 4 October, installed 0.10.21 and connected Windows. The new Spot diagnostic showed `RISK_HALT`; no trading gate was reset. The later failure email was an obsolete 28 September job canceled when the required-reviewer rule was deleted.

# Candidate — 0.10.21 last Spot-cycle diagnosis

Prepared from current main `c1f522e021f50aed70ca609374edd3a6cdae9d13` after the owner requested a visible distinction between a bot working without opportunities and an operational error. The shared local/remote Spot panel reports the last cycle's outcome, counters and safe reasons, and expires old evidence. Legacy snapshots remain supported. Source validation, protected publication and signed Windows installation remain separate gates. See `UPDATE_NOTES.md` for scope and regressions.

Local validation passed 325 offline Python tests and 80 Node tests, including a real Python-to-Worker projection contract and browser-state rendering regressions. GitHub Linux/Windows validation and protected owner approval must still be verified for the exact PR head.

The preceding authenticated portal audit observed installed 0.10.20, Windows connected, Spot operational with no positions and no active errors, and Futures waiting for a signal. That audit did not expose why the current Spot cycle had no entry; the new diagnostic becomes available only after the installed engine completes a new cycle.

# Candidate — 0.10.19 update completion across configuration upgrades

Prepared from main `c2064a97f7ef006916a21037552f8d466dc578ec`. Avoid re-reading new trading settings through the old imported independent-supervisor validator after successful install/restore; require confirmed outcome, exact identity and expected version. Relevant source tests precede the PR; publication and installation remain separate.

# 0.10.18 published and observed installed/connected

PR [#96](https://github.com/jlboper/Crypto-BOT/pull/96) merged. Protected [37173943719](https://github.com/jlboper/Crypto-BOT/actions/runs/37173943719) succeeded, verified the signature and published TESTNET 0.10.18 for `f3f5d3508e6359ffff032d710dc5d51ffa0f0e41`. Linux/Windows validation passed; local checks counted 291 Python and 76 Node tests.

After the owner reported update failure, an authenticated portal audit observed installed 0.10.18, connected Windows and fifteen Futures assets/max five positions. The historical install job said only `Trabajo detenido: ValueError`; a subsequent check completed with `Estás actualizado · bot 0.10.18 · firma verificada`. Source reproduction found a stale previous-version validator in the post-install reporting path; see PROJECT_HISTORY.md. Point-in-time version/connection and signed check do not guarantee future uptime or native protection behavior without open exposure.

# Candidate — 0.10.18 fifteen-asset Futures portfolio

Prepared from main `15f74ab4d7a7ba28d6d1c716f46bfd07da7c804f` following the owner's approval of fifteen assets, up to five positions and a 300 USDT gross portfolio ceiling. Add a 7.5 USDT estimated stop-loss budget with a cost reserve; retain 1x/2x/3x without multiplying exposure. Source validation, protected publication and signed Windows installation remain distinct gates.

# 0.10.17 publication confirmed; installation not observed

PR [#95](https://github.com/jlboper/Crypto-BOT/pull/95) merged on main as `15f74ab4d7a7ba28d6d1c716f46bfd07da7c804f`. Protected run [37172747885](https://github.com/jlboper/Crypto-BOT/actions/runs/37172747885) completed successfully. The Windows installation of 0.10.17 has not been observed in this source checkout; the 0.10.16 evidence below remains the last authenticated installation audit.

# Current status — 0.10.16 published and observed installed/connected

An authenticated audit on 2026-10-04 UTC observed the portal reporting installed 0.10.15 and Windows connected. Main, financial/health details, signals/shadow evidence, Research assets and the Options submenus were inspected. Trading/account controls were viewed without changing settings or sending trading orders.

PR [#93](https://github.com/jlboper/Crypto-BOT/pull/93) merged as `2b51e596d0df6bf4d19b44302ffa1e7082465099`. Protected release [37170161112](https://github.com/jlboper/Crypto-BOT/actions/runs/37170161112) completed successfully, verified the signature and published TESTNET bot 0.10.16 for source `614dc45a9f62a89682fbb6c32b74b28f5ba58053`. Linux/Windows CI passed 273 offline Python tests; release validation also passed 76 Node tests and the real Windows PowerShell manager/repair lifecycle checks.

The authenticated portal subsequently showed an update job completed with `Bot 0.10.16 instalado; arranque y portal local comprobados en TESTNET`, followed by installed version 0.10.16, Windows connected over HTTPS, Spot operational and Futures active/waiting for a signal. The corrected UI showed separate strategy/technical closes, dated AI reviews and zero exposure for closed Spot assets. This confirms the reported installation/projection at the audit time, not permanent continuity or native protection behavior with no exposed positions.

The release corrects evidence presentation, Spot average-loss accounting and stale Futures health. It preserves strategies, risk, execution and observation history. See `UPDATE_NOTES.md` and the audit decision in `PROJECT_HISTORY.md`. The 0.10.15 status below is the historical baseline.

# Published baseline — 0.10.15; version and connection observed in authenticated portal

PR [#91](https://github.com/jlboper/Crypto-BOT/pull/91) merged as `2e73c67b68e422bc236fe3e66323e1034b9c2b7a`. Protected release [37168205095](https://github.com/jlboper/Crypto-BOT/actions/runs/37168205095) completed successfully on 2026-10-04 UTC and signed 0.10.15 for source `4286f185719d080efce4da97f41ef8302b252e0d`. Linux/Windows validation passed 271 offline Python tests; release validation also passed 75 Node tests and real Windows PowerShell manager/repair lifecycle checks.

The owner supplied Windows evidence of the 0.10.14 defect: the existing agent task was `Running`, its separate root lacked `trader/native_protection_compat.py`, and remote status showed `sync_ok=False` with `ModuleNotFoundError`. A local recovery copied only that missing helper from the committed, hash-verified signed installation and restarted only the existing agent. The owner then reported that Windows updated to 0.10.15 and the connection was visible again. The subsequent authenticated portal audit also observed version 0.10.15 and Windows connected. Two fresh local authenticated syncs, single-indicator ownership and native exchange protection must be verified separately rather than inferred from publication or a connection badge.

For the confirmed cause, recovery boundaries and mandatory prevention checks, read the 2026-10-03 incident in `PROJECT_HISTORY.md` and the agent handover section in `PROJECT_HANDOVER.md`. The older candidate/publication notes below are historical and do not override this status.

## v0.10.3 protected publish retry

Retry after fixing the merged-PR publication trigger to use `pull_request_target`, so the environment gate runs against the merged commit on `main` and keeps owner approval mandatory.

## v0.10.3 publication trigger

Visual-only portal motion release merged to main; this note exists only to emit the normal protected publication push. No runtime or trading behavior changes.
# 0.10.15 repair candidate — historical preparation note

Source preparation reproduced and fixed the 0.10.14 independent-supervisor missing dependency, added indicator ownership and serialized agent repairs. At preparation time, the owner's 3 October photo showed 0.10.14 in the Windows app and two tray icons; the exact Windows error, publication and installation were still pending. Subsequent diagnosis and owner-reported recovery are recorded in the current status above. See UPDATE_NOTES.md for regression checks and scope.

# 0.9.7 publication handoff

Version 0.9.7 is merged on `main`. The functional PR was merged through the GitHub API, which may not emit the protected `push` publication run in this repository. This documentation-only follow-up PR exists solely to be merged by the owner in the GitHub web UI so the normal `main` push event can trigger `portal-release.yml`. It does not change bot behavior, strategy, risk, leverage, credentials, ledgers, or LIVE state.

# 0.6.20 unified execution candidate

Version 0.6.20 is implemented on branch `work/unified-testnet-engine-v0620` for review. It keeps one TradingEngine and selects either PaperBroker or BinanceTestnetBroker. The Testnet broker is restricted to Spot Testnet, journals client order identity before writes, blocks duplicate writes during uncertain/partial states, reconciles by client id, and records exchange fills into a separate Testnet ledger. PAPER remains a reversible simulation environment; Binance LIVE remains unavailable.

The portal/supervisor changes make the active environment explicit and add a supervised PAPER↔TESTNET switch. Research remains read-only and now emits a non-automatic strategy promotion pipeline; forward testing and explicit approval are still required before a research candidate may be considered for Testnet. Publication, signed release, Windows installation and actual Testnet autonomous execution remain unverified until CI/release/owner installation complete.

# Bot updates: implementation and deployment status

Version 0.6.19 prepares six PAPER-only size controls, preserves old stored
risk multipliers, and adds a bounded read-only Binance Spot Testnet order and
balance audit for the completed fictional-funds round trip. The Testnet portal
uses derived ledger state to disable duplicate buy/sell controls; the installed
engine remains PAPER and no strategy automatically sends Testnet orders.
Publication and Windows installation remain pending until their actual GitHub
workflow and signed update are independently confirmed.

Version 0.6.18 prepares automatic refresh of the independent Windows agent
from a committed signed installation when the 0.6.18 app starts, following
a local update, or when it detects a remote portal installation while running.
An app process started before 0.6.18 was installed must be reopened once to
load its new code. Automatic refresh does not change a stopped agent or the
trading engine and retains a manual recovery button. Publication and Windows
installation are separate and must be verified after the protected workflow.

Version 0.6.17 is a proposed update under review. It adds model selection and
cooperative PAPER restart from the shared portal, plus a separate, explicitly
confirmed BTC/USDT Spot Testnet order pilot (25 fictional USDT per entry,
one entry per UTC day, durable order identity and read-only reconciliation).
This does not yet move the strategy engine or PAPER historical accounting to
Testnet, nor enable production Binance trading. The owner must install the
signed release and then refresh the independent Windows agent using the app's
repair action before the remote controls become available. No Testnet order
has been sent by development or CI.

Version 0.6.13 was published and signed for commit
`4df7ca199cd5148c205dcf499493c24ff7515a5b` after protected run
`36079566679` succeeded on its second attempt. The owner subsequently reported
a successful 0.6.13 installation from the authenticated portal. An independent
Windows version/health capture was not available in this source checkout. The
first protected attempt deployed a healthy portal but failed at signing with
`portal_and_bot_revision_must_match`: different
Cloudflare edges briefly served different deployed revisions. Version 0.6.14
prepares a bounded retry for only that exact fixed rejection, in the same
protected run and with the same OIDC identity, signed manifest and package.
The retry does not change signer validation or skip the owner environment gate.
It also keeps the core HTTPS heartbeat and update jobs alive when the optional
financial projection raises locally, and lets a refreshed independent agent
read the current installed bot's PAPER projection in a separate, short-lived
process. Refreshing the independent agent's `scripts/windows_agent.py` and
`trader/remote_agent.py` from the verified signed installation remains a
one-time Windows step after 0.6.14 is installed; upgrading the bot alone cannot
replace files in the separate supervisor directory.

The protected main release run for 0.6.15 succeeded at commit
`f6921b7f3247fcb54b983bf7c9f9ee019d36928c`; the owner reports completing
its Windows update. Independent Windows identity, effective OpenAI model and
supervisor module hashes are not available in this source checkout. Version
0.6.16 prepares a one-time assisted independent-agent refresh from a committed
signed installation. The local and remote portals expose the same PAPER position
closing and risk fractions. The remote portal requires a fresh Windows heartbeat,
queues a single exact request in the existing D1 jobs ledger and reports its
confirmed or failed result; the local portal executes the same validation
immediately. No new D1 migration or expanded CI credential is required. The signed Windows
installation must be followed by the assisted independent-agent refresh before
the remote controls become available. It introduces no Testnet or production
order placement; publication and Windows installation remain pending.

Version 0.6.13 is a minimal signed update exercise: only the packaged version
and the shared portal's visible version label change. The owner confirmed the
previous 0.6.12 Windows installation and a healthy outbound sync after repairing
the independent agent's dashboard projection. Installation required separate
approval of the exact release through the authenticated portal and a Windows
health check.

The owner's portal screenshot on 24 September 2026 shows **0.6.8** installed
after request #15, with startup and local PAPER portal checks completed. Its
signed package was published separately after the PR #11 merge. A subsequent
documentation-only PR #12 does not change the installed bot. The voluntary
restoration remains available only when Windows offers a previous verified
version; it was not executed in that screenshot.
The outgoing HTTPS agent was connected,
and the local and remote portals use the shared `web/` interface. The first signed
installation and a later end-to-end update initiated with the remote portal button
were verified. This document distinguishes
implemented code, publication and installation. See `BOT_RELEASE_OPERATIONS.md`
for the owner workflow.

Subsequently, 0.6.9 was published through the protected job for commit
`1ccccbbe5605fb9111c728ea8c9ab33040a778cc`; the owner replied "listo" after
the handoff, but no authenticated Windows version/health snapshot was captured
here. At that point 0.6.9 installation was unverified and version 0.6.10 was
only a proposed PAPER evidence and UI update; see the subsequent inspection below.

Later the owner reported a read-only inspection of the supervised Windows
process, local PAPER portal and installed 0.6.10 identity. The protected
publication run for commit `bfdb89ece5673985351829676ad234cfbcde9989`
completed successfully. This is owner-reported installation evidence, not
direct access to the operating database from this source checkout. PR #15 for
0.6.11 was subsequently merged and its protected publication reported as
successful; its installation on Windows has not been verified in this copy.

Version 0.6.12 kept GPT-5.6 Luna as the API review model at that time, adds a
read-only Testnet planner and synthetic order reconciliation, and exposes the
unified research promotion gates in the portal. It is not published or
installed until its PR and protected release complete. The official OpenAI API
now documents `gpt-6-luna`; proposed 0.6.15 uses it in config, subject to an
explicit `check-ai-model` probe on the Windows account. Existing `.env.local`
overrides persist across signed updates and may still select 5.6 Luna. The
0.6.15 portal emphasizes operational PAPER status and hides research in a
diagnostics panel. It adds a separate signed `/api/v3/order/test` request on the
fixed Binance Spot Testnet host for local validation; this endpoint does not
enter the matching engine. No Testnet or live order submission is introduced.
The owner's 24 September Windows screenshot shows the scheduled outbound agent
running but `sync_ok: false` with `HTTPError:400`, so the portal cannot deliver
update jobs. A separate manual supervisor refresh attempt ended with
`FileNotFoundError`; the exact missing path was not captured. The newer agent
now reports allowlisted server validation reasons and can retry one rejected
optional dashboard projection without dropping the heartbeat. The app now
supports direct signed local installation through the independent supervisor,
including a previously staged package when offline. Neither change has yet
been observed on the operating PC.

## Implemented and tested

- Shared portal buttons for finding a signed release and approving its exact
  manifest hash. The app/local UI open the same authenticated remote center.
- CSRF/session protection, fresh Windows heartbeat, enabled/expiry checks,
  idempotent requests and propagation of `release_id` into durable Windows jobs.
- Deterministic allowlisted source ZIP, version increase requirement and a
  protected GitHub publication step after portal deployment.
- GitHub OIDC validation and Ed25519 signing in the portal. The private signing
  key is held as a Cloudflare secret; GitHub receives no permanent signing key.
- Windows signature/hash verification, replay/downgrade rejection, cooperative
  stop, startup barrier, owned-process and loopback HTTP health checks, durable
  commit, code/SQLite recovery and reconciliation of interrupted remote jobs.
- Windows exclusive HTTP port binding and bytecode invalidation on rollback.
- One-time bootstrap for an already stopped legacy engine. It refuses to stop
  a discovered process or install while the original engine lock is occupied.
- Historical release tests covered workerd/D1 signing, synthetic Windows child
  processes, bootstrap and exact remote approval. Current test counts must be
  taken from the 0.6.8 PR/CI, not reused from an older release. No operating bot
  is started or stopped by the offline tests.

## Production baseline

- Cloudflare holds `BOT_SIGNING_KEY`; Windows and the repository use the public
  trust anchor. D1 migration `0004_bot_releases.sql` is active.
- The trusted Windows channel points to the existing portal; the owner's latest
  local read-only installation report shows 0.6.10 in PAPER.
- The portal update center already uses one options menu and one combined search.
  The voluntary restoration action and full-history PAPER financial scorecard
  were included in the subsequent release. Restoration requires a retained,
  verified previous code copy; do not count an offered restore as an executed one.
  The 0.6.8 installation includes per-asset diagnostics, quote freshness and
  historical research comparisons. Published version 0.6.9 adds a three-item activity
  summary, private 90-day paginated history, historical analysis within the
  financial panel and forward synchronized BTC spot comparisons. Historical
  equity is not backfilled; no Testnet or LIVE execution is implemented.

## Completion gates

1. Prepare the next version on an isolated branch, pass CI and merge it.
2. Verify successful automatic publication and signed-package publication of
   the current main commit after Linux and Windows validation. If the owner
   restores required reviewers, honor that existing environment gate.
3. Verify the exact signed release installation, version, health and heartbeat
   from the authenticated portal. Observe the existing automatic Windows rollout
   first; the exact-manifest manual installation remains a fallback.

Do not describe a new version as installed until all three gates are recorded as
completed. No Android app or push-notification delivery is implemented here.
# 0.10.35 — Prepared, not yet deployment evidence

Guardian Observer/four-engine contracts prepared from verified installed0.10.34
main06de9109a0ae49ffbdb5f94bc6310a9239f421fc. PR111mainpublication run38942598655
succeeded on Linux/Windows and publisher; Ed25519 verified,162/162 installed
hashes matched. Device syncs17:52/17:54UTC were fresh and distinct.
Next release must pass its own tests/PR/main publication and installed audit.
Observer cannot control trading; Quant remains NOT_STARTED. Four-card web/Windows
and Quant simulation are later separate stages.
# 0.10.36 — Prepared UI stage

PR112 merged0.10.35 maincf3eec5a9e310f4162e0b9edcd2c9a2f4dc2f9e6 after workflows
38983739524/38983739576 succeeded (515 Python tests,115 Node tests locally).
0.10.36 prepares shared four-card web/mobile and Windows2x2 layout from that main.
Its own main run, signature, installed hashes, engine health and indicator reload
must be observed separately. Quant NOT_STARTED; Guardian Observer only, no veto.
