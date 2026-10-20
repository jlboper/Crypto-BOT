# Work Context — Crypto AI Trader

## Continuación actual — 0.10.44 Capital Protocol Lab, en preparación

Base main **0.10.43** `e61dd2a6f617cd39e8bd1c69728dc6f63b800401`,
[PR #120](https://github.com/jlboper/Crypto-BOT/pull/120), publicada y firmada tras
[publicación 39254593562](https://github.com/jlboper/Crypto-BOT/actions/runs/39254593562)
y [seguridad 39254593565](https://github.com/jlboper/Crypto-BOT/actions/runs/39254593565),
Linux/Windows SUCCESS. Instalada a 2026-10-19 12:53:08 UTC: Ed25519 y **188/188
hashes**, motor 21084, agente 21344 sincronizado. Spot 2/Futures 4 ARMED, cantidad
desprotegida cero. Cinco assets web y 11/11 módulos del agente coincidentes.

Auditoría Guardian43 12:54:49 UTC: OBSERVING, cuatro fuentes FRESH/completas,
tres assessments distintos y **3/3 replays MATCH** con causalidad válida, errores 0,
LEVEL 0 y toda autoridad false. Régimen entonces INSUFFICIENT_DATA por ventana
cerrada obsoleta; no inferir tendencia. Dos intentos IA legacy FAILED, causa y
coste desconocidos, cuota diaria 2/2 conservada. No resetear claims para probar.
Exportador firmado a las 12:55:01 UTC incluye GI 7407 bytes en payload 417045 bytes; sin nuevas
llamadas de proveedor durante esas auditorías. Datos previos comparados: ausentes 0 y
cambiados 0; claves, riesgo, configuración Futures e hipótesis intactos; prefijo de
721 registros Guardian y dos intentos también preservados. Son cortes fechados.

Rama44 `feature/capital-protocol-lab-v01044` integra un laboratorio sintético
cerrado de siete recetas con CLI explícito y JSON RO en Research Lab. Detalle en
[CAPITAL_PROTOCOL_LAB.md](CAPITAL_PROTOCOL_LAB.md). No usa cuentas actuales,
propuestas reales, ejecución, IA ni reservas de los motores. Guardian continúa
NOT_INTEGRATED para capital. No declarar F3 runtime completa. Prototipos 61 tests
y 64 tests core/Lab/CLI integrados PASS son evidencia enfocada previa. Antes de
compactar UI: **850/850 Python (181.531 s, TEST_RESULTS 13:19:52.904728 UTC), 202/202
Node (69.325 s)**, 84 pruebas UI enfocadas (13.643 s), PS5.1 lifecycle/vistas, build
y diff PASS. [PR #121](https://github.com/jlboper/Crypto-BOT/pull/121) ya existe en
draft, head `5138e51a1f37001629ac1420e3b0d7e48a439170`, CI 39259777367/39259777360
PASS para ese head. Compactación local posterior: 47 plegables, auditoría cerrada
y detalles por caso; LAB SIM/fecha/resultado visibles. Foco UI 84/84 (7.046 s) y
diff PASS. QA visual PASS en preview sintético local a 360/768/1366px: sin overflow,
siete casos, detalle independiente/Enter/auditoría y pérdidas con signo correctos.
Ver `capital-lab44-visual-qa.json` y CAPITAL_PROTOCOL_LAB.md. Full final tras
compactar: **850/850 Python** (171.844 s en TEST_RESULTS, 2026-10-19
17:56:01.749748 UTC; runner 171.835 s), **202/202 Node** (37.430 s), build/diff PASS,
sin fallos/errores/skips. Nuevo head/CI final pendientes; la CI anterior no
acredita cambios posteriores. Sin merge,
publicación/firma ni instalación44; preview no es evidencia de instalación.

Auditoría RO **13:18:23 UTC**: todas las filas del backup Spot 43, trades 80/80 y
receipts 48/48, ausentes 0/cambiadas 0; SHA del backup intacto. Informe
`append-only-backup43-verification.json`. Updater 43 respaldó sólo Spot. Los
prefijos muestreados Futures/Pulse/Quant previamente comparados siguen válidos,
pero no son comparación exhaustiva pre-43; no hubo backup 43 multiledger.
Pulse readiness parcial (10 fresh/1 complete a las 12:46 UTC) queda como entrega separada,
sin cambiar compuertas; no confundir WARMING_UP con caída.

## Registro histórico de preparación43

## Preparación histórica — 0.10.43 correctiva del lector Guardian

Base instalada 42 main `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`, PR #119.
Publicación 39181606398 y seguridad 39181606401 SUCCESS. Auditoría 2026-10-19
00:42:33 UTC: Ed25519, 188/188 hashes y cinco assets web verificados; motor 3680,
Spot 1/Futures 5 ARMED, cantidad desprotegida cero. Agente entonces 9/11; refresco
firmado verificado **00:54:20 UTC**: agente 21344, **11/11**, sync_ok y dos heartbeats
recientes correctos. Motor 3680 sin cambio y mismas posiciones/protecciones.

Guardian real PARTIAL, 0/4 fuentes válidas, todas UNKNOWN por
WAL_SIDECARS_UNAVAILABLE; journal real 1, replay MATCH. IA: un intento FAILED,
usage y causa desconocidos. No afirmar servicio completo ni fallo de cuota/créditos.

Rama `fix/guardian-readonly-wal-v01043`: permitir SQLite mode=ro/query_only normal
con sidecars ausentes tras limpieza habitual y metadata WAL/SHM transitoria, sin
DML financiero, constructor, migración, copias immutable ni pérdida de frescura.
Prefiltro determinista de todas las fuentes UNKNOWN antes de IA; diagnósticos
acotados seguros sin cuerpos/headers arbitrarios ni secretos. Pruebas de archivos
financieros sin cambios y escritores concurrentes; PR/CI/rollout 43 pendientes.
No usar los 767/180 de 42 como resultado de 43. Capital Protocol Lab continúa
fuera de Git, sintético, sin conectar motores ni completar F3 runtime.

00:47:04 UTC: candidata43 leyó backups SQLite RO temporales de los cuatro esquemas
reales, todos FRESH/completos, posiciones Spot 1/Fut 5/Pulse 1/Quant 0 y SIDEWAYS
descriptivo. Sin motor/proveedores/credenciales; copias retiradas. No es 43 instalada.
87 pruebas enfocadas captura/servicio y 1 no-IA con todo UNKNOWN PASS; IA 35 PASS
(6.961 s), Node 180/180 PASS (106.485 s), lifecycle/vistas PS5.1, build y diff PASS.
Python offline completo **777/777 PASS, 238.609 s**, sin fallos/errores/skips,
red externa bloqueada y sin iniciar bot (`TEST_RESULTS.json`, 00:55:17 UTC).
PR/CI/publicación/firma/instalación 43 pendientes; no se afirma operación instalada.

## 0.10.42 Guardian Intelligence Shadow — preparación histórica

Base main 0.10.41 `022fb9135d165d5c52f12b65aa9628ab8c1436af`, PR #118,
publicada/firmada e instalada 178/178 hashes. Publicación 39134814222 y seguridad
Linux/Windows 39134814202 exitosas. Auditoría 2026-10-18 14:16:30 UTC: motor
19240, Spot 1/Futures 9, protecciones nativas ARMED sin cantidad desprotegida;
agente 9372 con sync reciente y módulos 11/11. Filas previas comparadas: cero
ausentes/cambiadas; secretos, riesgo e hipótesis conservados. Es evidencia de 41.

42 implementa F2 dentro del único proceso, siempre SHADOW LEVEL 0: lectura
explícita de cuatro ledgers sin constructores financieros, cantidades incompletas
UNKNOWN, régimen BTC descriptivo de 61 cierres/60m y revisión de conflictos/límites.
Journal propio `guardian-shadow.db`, capturas congeladas, leases y replay causal;
no es vista global atómica ni propuesta completa previa a una orden. No veta,
reserva, ejecuta ni sustituye revisión individual o protecciones.

Guardian IA observacional está autorizado con reutilización de clave y límite
propio: hasta dos intentos/día, mínimo una hora, TTL histórico 900 s, entrada
4,096 bytes/salida 512 tokens/timeout 8 s, condicionado a `ai.enabled`. No consume
cuotas Spot/Futures/Pulse. Costes estimados con tarifa verificada, nunca tope duro
de factura; usage incompleto queda desconocido. Pruebas usan claves/transporte
sintéticos: llamadas reales instaladas aún sin verificar. Ya hay ocho intents
locales de lectura (resumen, régimen, riesgo, conflictos, calidad, revisión original,
límites y contrafactual UNKNOWN), vinculados al assessment/corte/journal disponible.
Su historial de seis identidades vive sólo en la pestaña, sin auditoría durable ni
llamadas API/SQL/tools. Capital Manager, NL general de servidor y Control Testnet
siguen pendientes; no se autoriza nivel 1 ni LIVE.

42 pasó 767/767 Python offline (361.510 s), 180/180 Node (85.515 s), lifecycle/vistas
Windows PowerShell 5.1, build del portal y diff. Regresiones de precisión UTC,
metadatos numéricos y hashes int/REAL no relajan cortes causales. QA 1366/360/768 px:
sin desbordamiento horizontal, un workspace Guardian, contrafactual desconocido e
IDs de evidencia reales. Logs locales `python-full-v01042.log`,
`node-full-v01042-final.log`, `windows-v01042.log`.
Auditoría base 41 19:10 UTC: 178/178 hashes, motor 19240/agente 13056, Spot 1/Futures
9, protecciones ARMED y cantidad desprotegida observada cero. CI de PR/main,
firma/publicación/instalación/operación de 42 aún pendientes. Conservar todos los
ledgers/journals y políticas; no hubo cambio en los motores financieros.

## 0.10.41 Command Center — registro histórico de preparación

Base main 0.10.40 `81ba4366cf587c16cae20d403974a340080c4d10`, PR #117,
publicada/firmada e instalada 178/178 hashes, verificada 2026-10-18 02:27 UTC.
Publicación 39089416208 y seguridad Linux/Windows 39089416215 exitosas.
La nueva misión CRYPTO-BOT 2.0 añade auditoría y organiza siete vistas compartidas
con Windows coherente; no altera ejecución, estrategias, límites, capital o IA.
Ver `COMMAND_CENTER_2_0.md`: mapa, contratos futuros, matriz y fases verificables.

Guardian actual es Observer puro, sin veto/reservas; Portfolio & Capital sólo
proyecta evidencia por entorno. Intelligence Shadow y Capital Manager Shadow son
fases 2/3 diseñadas, aún sin implementar. El coordinador de exposición es un
prototipo sin integración en bots; no habilitar capital compartido. Guardian
Control Testnet requiere autorización expresa futura y validación. Fase 1 tiene
presupuesto Guardian IA cero y ninguna llamada nueva; conserva revisión individual
Spot ALLOW/REJECT/REDUCE y Futures ALLOW/REJECT. No hay NL ejecutor ni LIVE.
Publicación/firma/instalación/verificación operativa de 41 siguen pendientes;
la evidencia de 40 no las sustituye. Las notas de preparación anteriores se
conservan como historia y no definen el estado actual.

## 0.10.40 — registro histórico de preparación

Base main 0.10.39 `2328f2959dc9b4fb939e889519b59a19e5a58423`, firmada e instalada
176/176. Publicación 39070205949 y seguridad 39070205944 exitosas; agente 11/11 y
cuatro ticks Quant recientes con edad máxima observada 60.85 s.
El historial de snapshots Quant observado tiene huecos;
su cantidad total no acredita una ventana StatArb contigua. La candidata añade
hasta 500 velas Spot cerradas 1m por BTC/ETH/SOL, guardadas aparte append-only
con primera recepción real y corte de replay. No interpola ni rellena snapshots
viejos y no atribuye conocimiento al instante de cierre anterior a la recepción.
Es diagnóstico retrospectivo; no forward/OOS ni backtest validado. StatArb sigue
sin entradas y Guardian sin veto. `premiumIndex` en lote conserva máximo 15
peticiones/minuto (14 iniciales/10 estables previstas), riesgos y SHADOW.
Pruebas completas, CI, publicación/firma e instalación 0.10.40 pendientes.

## Ajuste 0.10.39 — registro de preparación

0.10.38 main `a94f1124d57439e90620f4b2d5c02cbb07f53f58` superó CI; publicación
falló en intentos 1/2 con 403 `publisher_revision_unavailable`. No está verificada
como firmada/instalada; Windows conserva 0.10.37, 176/176 hashes. La causa HTTP
GitHub no está confirmada, incluida una posible limitación de cuota.
La candidata 0.10.39 añade diagnóstico saneado y reintento de disponibilidad
acotado a 105 s de espera acumulada, hasta siete solicitudes de 30 s cada una,
con el mismo manifiesto/token OIDC. Conserva validación
de `main` exacto, contexto autorizado, firma y coincidencia de revisión desplegada;
no acepta revisiones superadas ni relaja seguridad. Incluye el ajuste de cadencia
38 sin cambios de trading/UI. Suite completa, CI, publicación/firma e instalación
39 siguen pendientes. Ver `BOT_RELEASE_OPERATIONS.md`.

## Ajuste 0.10.38 — registro de preparación

0.10.37 main `3b02326c435acf3c9c666940a90923908e9bab64` verificada firmada e
instalada con 176/176 hashes. Después de instalar se observaron referencias
Quant antiguas intermitentes por la diferencia entre inicio/completado del tick
y la caché estricta de 60 s. La candidata 0.10.38 espera 60 s desde el completado;
no aumenta llamadas ni relaja frescura, riesgos o ejecución SHADOW. Preservar
todos los ledgers, journals, pausas y protecciones. Suite completa, CI y estado
publicado/firmado/instalado de 0.10.38 requieren verificaciones propias.

## Implementación 0.10.37 — registro de preparación

Predecesora verificada: 0.10.36, main
`1bb77fad1a490472907ce29591e0b1075d3e7ba3`, PR #113, firmada e instalada 167/167.
La candidata 0.10.37 implementa Quant SHADOW dentro del mismo proceso supervisado:
Funding Carry hipotético con costes por pierna, ledger/journal propios, fuentes
Binance públicas sin credenciales y pausa independiente mediante el agente.
StatArb sólo diagnostica y espera/rechaza; no abre pares hasta validación
independiente. Guardian sigue Observer sin veto ni reservas de capital compartido.

El portal y Windows muestran estados/finanzas virtuales reales del ledger,
frescura, funding observado/proyectado/asentado simulado y límites propios 1%/2%
diario/semanal con referencia en la primera equity válida del período UTC.
La valoración desconocida bloquea entradas; pausas no detienen cierres protectores
hipotéticos. Estrés de colateral virtual no equivale a liquidación Binance.
Datos de Spot/Futures/Pulse, límites previos y flujo firmado deben conservarse.

Focalizadas registradas: 70 core, 59 contratos, 31 UI, 20 assets Windows y vista
PowerShell 5.1. Suite completa, CI Linux/Windows, publicación/firma e instalación
de 0.10.37 pendientes de verificar. Ver `FOUR_ENGINE_EXPANSION.md`; no afirmar
ventaja estadística, promoción, Guardian Control ni nueva ejecución Testnet/LIVE.

## Ampliación 0.10.34 y siguiente etapa solicitada

El propietario autorizó diez mayores activos negociables sin stablecoins/duplicados,
cinco fuentes compatibles y plegar secciones largas. 0.10.34 prepara esta ampliación
de Market Pulse SHADOW, preservando riesgo, tres slots hipotéticos y datos previos.
Universo fechado y metodología en `MARKET_PULSE.md`; publicación/instalación se
verifican separadamente. Después solicita cuatro bots y Portfolio Guardian:
terminar esta ampliación primero; iniciar Observer sin veto ni ejecución Quant.
Ver `FOUR_ENGINE_EXPANSION.md`. No mezclar arbitraje con balances Testnet/Demo.

## Ajuste 0.10.33

Sin cambios de producción: la prueba de exclusión espera la adquisición efectiva
del lease antes de comprobar el segundo servicio. Evita una carrera sintética
observada en CI Linux. Conserva 0.10.32 y requiere validar publicación e instalación.

## Ajuste 0.10.32

La 0.10.31 (`ef4378fd7ff139b892ffa3bde79c4faa08884e6b`) se observó publicada,
firmada e instalada el 16 de octubre: 160/160 hashes, motor activo y sincronización
HTTPS reciente. El RSS Ethereum devolvió 301; 0.10.32 usa `/en/feed.xml` sin
permitir redirecciones. Bitcoin Core y Binance funcionaron. Verificar por separado
publicación, firma, instalación y fuentes actuales de este ajuste.

## Evolución 0.10.31 (verificar publicación e instalación por separado)

Tres identidades en el portal: Spot Testnet y Futures Demo conservan estrategias,
presupuestos, posiciones y protección; AI Market Pulse agrega observación SHADOW
de BTC/ETH/SOL dentro del proceso existente, con ledger, pausa y cuota IA propios.
No admite órdenes, PAPER/Testnet/LIVE ni promoción desde configuración o botones.
Ver `MARKET_PULSE.md`. Los antecedentes de dos motores que siguen son históricos.

## Antecedente 0.10.18–0.10.19 — arquitectura de dos motores

La rama estable trabaja con un único proceso supervisado y dos motores de prueba en paralelo:

- **Spot Testnet**: motor principal multi-activo, sin margen ni cortos, con estrategia swing, límites de riesgo y revisión IA final.
- **Futures Demo**: forward test separado de 15 monedas, LONG/SHORT, ISOLATED, ONE_WAY y hasta cinco posiciones. La candidata 0.10.18 conserva pruebas 1x/2x/3x sin multiplicar cantidades y fija límites conjuntos de 300 USDT de notional bruto y 7,5 USDT de pérdida estimada hasta stops (incluye reserva de costos del 0,5%). Configuración/filtros actuales dimensionan cada entrada; precios de fills y gaps pueden superar estimaciones. Usa ledger, journal y kill switch propios; posiciones existentes conservan sus protecciones. Publicación e instalación 0.10.18 observadas en el portal autenticado; 0.10.19 prepara una corrección de confirmación del actualizador, sin cambios de trading.
- **PAPER**: respaldo técnico, CI, regresiones y recuperación. No es el entorno diario predeterminado.
- **LIVE**: no implementado. Ninguna métrica o estado habilita capital real automáticamente.

## Arquitectura registrada en ese antecedente

- `web/`: interfaz única compartida por localhost y Cloudflare. El portal local y remoto deben conservar la misma estructura, nomenclatura y métricas.
- `scripts/manager_windows.ps1`: centro de control compacto de Windows; abre portal local/remoto, reinicia el motor, gestiona inicio automático, kill switch y actualizaciones firmadas.
- `trader/engine.py`: ciclo principal Spot y llamada al forward engine Futures durante TESTNET.
- `trader/futures_forward.py`: señal, revisión IA final, ejecución/recovery y protección del forward test Futures Demo.
- `trader/update_manager.py` + `trader/update_supervisor.py`: actualización firmada, parada cooperativa, health-check, commit/rollback y restauración de código anterior.
- `scripts/windows_agent.py`: agente saliente HTTPS para portal remoto; no crea un segundo motor.
- `data/trader.db`, `data/testnet-trader.db`, `data/futures-testnet.db`: ledgers separados. Nunca fusionarlos.

## Reglas permanentes

1. Nunca introducir una ruta Binance LIVE sin una fase explícita y separada de diseño/revisión.
2. Las claves y `.env.local` permanecen fuera del repositorio y del portal.
3. Spot y Futures deben conservar identidad, ledger, riesgo y kill switch separados.
4. La IA es una última compuerta para nuevas entradas; nunca bloquea un cierre protector, stop, reconciliación o recovery.
5. No borrar históricos, bases financieras, paquetes de rollback o mecanismos de recuperación durante limpiezas visuales.
6. Mantener portal local y remoto sobre los mismos assets web; evitar dos UIs divergentes.
7. Los tests deben declarar explícitamente PAPER/TESTNET cuando el comportamiento depende del entorno.
8. Antes de merge: `python scripts/test_offline.py` en Linux y Windows, parse de PowerShell y tests del Worker/frontend.

## Flujo de releases

Work prepara una rama/PR. GitHub ejecuta validaciones. Al integrar en `main`, el workflow protegido publica el portal y construye el paquete firmado cuando cambia la versión. Windows instala únicamente paquetes verificados mediante el supervisor. El centro local de actualizaciones puede verificar e instalar sin depender del portal remoto.

Desde la autorización del 4 de octubre de 2026, la publicación rutinaria es automática: PRs solo prueban; el push de `main` vuelve a validar Linux/Windows antes de publicar. El propietario quitó los revisores obligatorios. El entorno y sus credenciales permanecen; una revisión que se restablezca debe respetarse. Scripts y firmante rechazan PRs y revisiones de main superadas. No cambia el permiso para LIVE ni la promoción de estrategias.

## Fase actual

La prioridad es **observación**, no añadir estrategia por ruido de pocos días. Spot y Futures acumulan métricas separadas (días, cierres, P&L/retorno, drawdown, calidad y errores). Desde 0.8.7 el portal añade salud de observación de 24 h: cobertura de ciclos, gaps, errores e integridad de journals/ledgers. Cambios de estrategia o riesgo deben basarse en evidencia suficiente; correcciones de seguridad/operación sí pueden hacerse antes.


## Unified signed rollout

Desde 0.8.5, un agente actualizado reporta su versión instalada al portal. Si el ledger de releases firmadas contiene una versión superior, el Worker crea automáticamente un `update_install` para esa release exacta. El supervisor Windows valida firma, secuencia, health-check y rollback. Un fallo real queda detenido y no se reintenta en bucle. La instalación manual permanece solo como fallback.


## Self-healing remote agent (0.8.8+)

La tarea programada de Windows usa un watchdog persistente independiente del motor. Si el agente HTTPS termina inesperadamente, el watchdog lo relanza con backoff y la tarea conserva una política secundaria amplia de reinicio. Después de que una release firmada queda comprometida y el nuevo motor supera activación/health-check, el motor lanza en segundo plano `agent_self_heal.ps1`: valida el journal firmado, actualiza la definición de la tarea, refresca únicamente módulos del agente independiente, reinicia ese agente y busca una sincronización HTTPS nueva. Un fallo de esta reparación degrada solo visibilidad remota; nunca detiene el motor ni revierte datos financieros.

El rollout compara siempre la versión instalada contra la última release firmada. Por ello una instalación atrasada puede saltar directamente a la versión más reciente sin encadenar releases intermedias.
# Continuación 0.10.35 — Guardian Observer

0.10.34 main06de9109a0ae49ffbdb5f94bc6310a9239f421fc publicado, firmado e instalado
162/162; Pulse diez activos/cinco fuentes, journal conservado, Futures seis posiciones
con protección ARMED y exposición no ampliada. Guardian observa cuatro ledgers con
contrato opcional y `/api/platform`; no veta ni reserva capital. Quant NOT_STARTED,
sin métricas inventadas. Las etapas UI cuatro motores/Windows y Quant Shadow son
PRs separados. No introducir nuevas órdenes Testnet ni LIVE. Ver FOUR_ENGINE_EXPANSION.md.
# Continuación 0.10.36 — portal y Windows de cuatro motores

PR112 integró Guardian Observer y contratos en maincf3eec5a9e310f4162e0b9edcd2c9a2f4dc2f9e6.
La siguiente etapa añade cuatro tarjetas web/móvil/Windows y paneles plegables
Guardian/Quant. Quant sigue NOT_STARTED: ningún wallet, retorno o ejecución se
inventa. Sin cambios de riesgo, ledgers, lifecycle o actualizador. Verificar CI,
firma, instalación y recarga real del indicador por separado. Quant Shadow y
evaluación estadística siguen pendientes de desarrollo; ejecución Testnet requiere
autorización posterior y Guardian Control permanece deshabilitado.
