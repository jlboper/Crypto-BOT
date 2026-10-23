## 0.10.52 — auditoría de transición en preparación

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

> Continuación47 en preparación: consultar [Validación y recuperación](VALIDATION_AND_RECOVERY.md).
> Mantiene Guardian LEVEL0 y Pulse/Quant SHADOW. La evidencia fechada de instalación46
> no acredita publicación, instalación ni validación operativa de47.

# Crypto AI Trader — CRYPTO-BOT 2.0

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

> Copia de desarrollo aislada de la instalación Windows. El repositorio no contiene credenciales ni datos de la instancia operativa. No inicies un segundo motor. Consulta `BOT_UPDATE_PROGRESS.md` para distinguir versión preparada, publicada e instalada.

**Estado 2026-10-19 00:42:33 UTC:** 0.10.42 publicada, firmada e instalada,
main `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`, [PR #119](https://github.com/jlboper/Crypto-BOT/pull/119).
[Publicación](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
y [seguridad](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
aprobadas, Ed25519 verificado, **188/188 hashes** y cinco assets web coincidentes.
Motor 3680: Spot 1/Futures 5 con protecciones ARMED y cantidad desprotegida cero.
El agente tenía 9/11 módulos en ese corte. El refresco firmado quedó verificado a
las **00:54:20 UTC**: agente 21344, **11/11 módulos**, sync_ok y dos heartbeats
recientes correctos. Motor 3680 sin cambio; Spot 1/Futures 5 ARMED y sin cantidad
desprotegida observada.

Guardian todavía no queda plenamente verificado: PARTIAL, 0/4 fuentes válidas
por `WAL_SIDECARS_UNAVAILABLE`, aunque el primer journal real reproduce MATCH.
Un intento IA real terminó FAILED; uso/causa desconocidos, sin diagnóstico de cuota.
La correctiva **0.10.43 está en preparación**, con pruebas locales aprobadas: lectura
SQLite normal en sólo lectura sin exigir sidecars permanentes, metadata WAL/SHM
transitoria sin DML financiero, filtro determinista que evita IA con todas las
fuentes UNKNOWN y diagnósticos seguros. No modifica capital, órdenes ni riesgo.
Capital Protocol Lab sigue como prototipo sintético externo, sin integración.

Prueba candidata43 a las 00:47:04 UTC: copias temporales mediante backup SQLite RO
de los cuatro esquemas reales dieron fuentes FRESH/completas (posiciones 1/5/1/0),
sin motor, proveedores ni credenciales. No acredita 43 instalada. Pruebas enfocadas
87 de captura/servicio y una de no-llamada IA con todo UNKNOWN aprobadas; además
35 IA PASS (6.961 s), **180/180 Node PASS (106.485 s)**, lifecycle/vistas Windows
PowerShell 5.1, build y diff PASS. **777/777 Python offline PASS (238.609 s)**,
sin fallos, errores ni skips, red externa bloqueada y sin iniciar el bot
(`TEST_RESULTS.json`, 00:55:17 UTC). PR/CI, publicación/firma/instalación de 43
siguen pendientes.

Los apartados de preparación de 41/42 siguientes conservan contexto histórico;
este estado operativo fechado prevalece sobre sus checkpoints entonces pendientes.

Desde 0.10.34, AI Market Pulse observa en SHADOW diez activos elegibles por
capitalización y cinco fuentes públicas primarias/regulatorias. Conserva wallet
hipotético separado, tres posiciones máximas y cuota IA propia. El portal compartido
ofrece secciones plegables y navegación directa; no mezcla balances de entornos.
Ver [Market Pulse](MARKET_PULSE.md) para la selección fechada, fuentes, hipótesis y
limitaciones. La expansión progresiva a Quant Arbitrage y Portfolio Guardian está
documentada en [cuatro motores](FOUR_ENGINE_EXPANSION.md).

La base **0.10.41**, main `022fb9135d165d5c52f12b65aa9628ab8c1436af`,
[PR #118](https://github.com/jlboper/Crypto-BOT/pull/118), está publicada,
firmada e instalada con **178/178 hashes**.
[Publicación](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814222)
y [CI Linux/Windows](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814202)
exitosas. La auditoría del 18 de octubre a las 14:16:30 UTC verificó continuidad
del motor/agente y las posiciones Spot/Futures con protección nativa ARMED,
sin cantidad desprotegida observada ni cambios en las filas financieras comparadas.
Conserva cuatro motores: Spot Testnet, Futures Demo y dos ledgers
hipotéticos independientes, Market Pulse y Quant SHADOW. Funding Carry simula
pares tras sus barreras; StatArb usa hasta 500 cierres Spot 1m con recepción real
y replay, pero sigue sin entradas. Estos datos retrospectivos no acreditan OOS.
Guardian continúa **Observer**, sin veto ni reservas compartidas.

La 0.10.41 incorpora el **Intelligent Trading Command Center**:
auditoría de arquitectura y siete vistas compartidas para Command Center,
Portfolio & Capital, Trading Engines, Guardian AI, Operations & Decisions,
Research Lab y System & Settings, con presentación Windows coherente.
Capital muestra evidencia por entorno; no reparte fondos.

La candidata **0.10.42** añade **Guardian Intelligence SHADOW, nivel 0**:
captura explícita de los cuatro ledgers en sólo lectura, régimen BTC descriptivo,
conflictos y códigos de revisión, journal independiente y replay causal.
No veta, reserva capital ni altera órdenes, riesgos o revisiones IA individuales.
La explicación IA opcional usa un presupuesto propio autorizado de hasta dos
intentos/día, intervalo de una hora y caché histórica de 900 s; requiere además
`ai.enabled`. Pruebas con transporte/claves sintéticos; no se afirma todavía una
llamada real instalada. Ocho consultas locales de sólo lectura explican resumen,
régimen, riesgo por ámbito, conflictos, calidad, revisión original, límites y
contrafactual desconocido, con assessment/corte e identidad de journal disponible.
Su historial existe sólo en la pestaña; no es auditoría durable. La consulta NL
general de servidor, Capital Manager y Guardian Control siguen pendientes.
Ver [arquitectura, límites y fases](COMMAND_CENTER_2_0.md).

Validación local de 42: **767/767 Python offline, 180/180 Node**, ciclo/vistas
Windows PowerShell 5.1, build del portal y diff aprobados. QA a 1366/360/768 px sin
desbordamiento horizontal y con un único workspace Guardian. CI de PR/main,
publicación/firma e instalación de 42 aún no verificadas. La revisión de 41 a las
19:10 UTC volvió a verificar 178/178 hashes, motor 19240/agente 13056 y posiciones
Spot 1/Futures 9 con protecciones ARMED y cantidad desprotegida observada cero.

Plataforma supervisada de swing trading con Spot Testnet y un forward test LONG/SHORT de Futures Demo, con cuentas, ledgers, pausas y protecciones separados. PAPER se conserva como respaldo técnico/CI. Market Pulse observa eventos en Shadow; Quant añade investigación y simulación de pares. Consume datos reales de referencia y conserva costes y entornos explícitos. Binance LIVE sigue sin implementación.

El ajuste operativo del 12 de octubre de 2026 amplía Spot Testnet y Futures Demo a diez posiciones por bot. Futures observa 15 monedas y alterna 1x/2x/3x sin multiplicar la cantidad: máximo 100 USDT por entrada, 300 USDT de notional bruto conjunto y 7,5 USDT de pérdida estimada hasta los stops, incluida una reserva de costos del 0,5%. El objetivo de las nuevas entradas Futures pasa de 60 a 30 USDT al distribuir el mismo presupuesto entre diez cupos; las posiciones existentes conservan su tamaño. La cantidad se adapta a filtros actuales y presupuesto disponible; los límites pueden permitir menos de diez posiciones. Son estimaciones previas a órdenes MARKET, no garantías de pérdidas máximas. Publicación e instalación se verifican por separado; las descripciones versionadas anteriores son históricas.

La IA no puede inventar compras, aumentar tamaño, eliminar stops ni cambiar
límites. La revisión individual Spot admite `ALLOW`, `REJECT` o `REDUCE`;
Futures admite únicamente `ALLOW` o `REJECT` sobre su propuesta exacta.
Pulse interpreta eventos con cuota propia; Quant y Guardian Observer usan
cálculos deterministas. Los cierres protectores y la conciliación no esperan a IA.

## Límites Spot y simulación PAPER

- Capital simulado: 1,000 USDT.
- Máximo 10 posiciones Spot. Futures conserva sus diez cupos y presupuestos
  propios; Pulse tiene tres posiciones hipotéticas y Quant hasta dos pares.
- Máximo 15% por posición y 60% de exposición total.
- Riesgo objetivo: 0.75% del portafolio por operación.
- Detención diaria: −2%; semanal: −5%.
- Stops por ATR, objetivo 2R y trailing stop después de alcanzar 1R.
- En Testnet, protección nativa confirmada por posición: OCO MARKET en Spot y condicionales de cierre en Futures Demo. El último stop/objetivo confirmado permanece en Binance sin conexión del PC; trailing y salidas por señal necesitan al bot conectado. La ejecución puede deslizarse. Los estados inciertos y cantidades bajo mínimos bloquean nuevas entradas y nunca se indican como protegidos.
- El motor principal Spot no usa margen ni cortos. Futures Demo vive en un laboratorio separado, limitado a `ISOLATED`, One-way y 1x–3x con fondos ficticios.
- Kill switch manual y automático después de tres errores consecutivos. Bloquea entradas nuevas, pero el motor continúa vigilando stops y salidas de posiciones existentes.

Los límites Spot/Futures configurables están en `config.toml`; Pulse y Quant
conservan sus hipótesis y ledgers independientes. No son una cartera común.

## Requisitos

- Windows 10/11 o Linux.
- Python 3.11 o superior.
- Conexión estable a internet.
- El motor usa la biblioteca estándar. El portal requiere Waitress 3.0.2; las firmas requieren cryptography 50.0.1. Son dependencias opcionales declaradas en pyproject.toml.

## Inicio rápido en Windows

1. Descomprime el proyecto.
2. Abre PowerShell dentro de la carpeta.
3. Coloca `OPENAI_API_KEY` en `.env.local`. No compartas ese archivo ni lo subas a Git.
4. Ejecuta:

```powershell
.\scripts\start_windows.ps1
```

5. Abre `http://127.0.0.1:8765`.

La clave creada durante esta sesión está guardada de forma segura en el entorno actual; no se incluye dentro del ZIP. Para instalar el bot en otra PC, configura allí la credencial mediante un canal seguro.

## Inicio rápido en Linux

```bash
chmod +x scripts/start_linux.sh
./scripts/start_linux.sh
```

## Comandos útiles

```bash
# Ejecutar un solo ciclo
python -m trader once

# Motor continuo + dashboard
python -m trader run

# Solo dashboard
python -m trader dashboard

# Estado local
python -m trader status

# Backtest conservador con hasta 10,000 velas cerradas de Binance
python -m trader backtest BTCUSDT --limit 2000

# Research Lab: BTC, ETH, SOL, BNB y XRP
python -m trader research

# Emergencia / reanudación
python -m trader kill
python -m trader resume

# Verificar credenciales Binance Spot Testnet sin operar
python -m trader check-testnet

# Verificar acceso a GPT-6 Luna y salida estructurada, sin iniciar operaciones
python -m trader check-ai-model --model gpt-6-luna

# Preparar una orden hipotética con filtros públicos de Testnet (sin enviarla)
python -m trader testnet-plan BTCUSDT --side BUY --quote-amount 25

# Validar firma y parámetros en Binance Spot Testnet sin enviar una orden
python -m trader testnet-validate BTCUSDT --side BUY --quote-amount 25

# Simular conciliación NEW → PARTIALLY_FILLED → FILLED sin red ni credenciales
python -m trader testnet-simulate
```

## Binance Testnet: entorno principal y laboratorio Futures

`BINANCE_API_KEY` y `BINANCE_API_SECRET` de **Spot Testnet** deben estar únicamente en `.env.local`. `check-testnet`, `testnet-plan`, `testnet-simulate` y `testnet-validate` siguen disponibles como diagnósticos sin ejecutar operaciones. El TradingEngine principal puede operar en `PAPER` o `TESTNET`; Spot Testnet usa `BinanceTestnetBroker`, un ledger separado y un journal durable antes de cada escritura. No existe host ni modo Binance LIVE.

A partir de 0.7.0, PAPER queda como entorno de respaldo/CI: se mantiene para regresiones, diagnóstico y fallback, pero las capacidades nuevas se desarrollan sobre Testnet salvo cambios de seguridad necesarios.

El laboratorio paralelo de **USDⓈ-M Futures Demo** usa la API REST de prueba oficial en `https://testnet.binancefuture.com` y credenciales distintas: `BINANCE_FUTURES_TESTNET_API_KEY` y `BINANCE_FUTURES_TESTNET_API_SECRET`. Sus datos se guardan en `data/futures-testnet.db`, separados del ledger Spot. Solo permite margen `ISOLATED`, modo `ONE_WAY` y leverage 1x/2x/3x. La v0.8.0 mantiene Spot y Futures como dos pistas separadas dentro del mismo proceso supervisado. Spot Testnet continúa multi-activo. Futures Demo ejecuta un forward test persistente solo en BTCUSDT, con LONG/SHORT, 1x, margen ISOLATED, modo ONE_WAY, una sola posición y cierre `reduceOnly`. Su activación proviene de la configuración firmada; una pausa operativa se realiza exclusivamente mediante el kill switch de Futures. Usa `data/futures-testnet.db` y un kill switch independiente. Las pruebas manuales 1x–3x se conservan plegadas en Diagnóstico.

Usa únicamente claves dedicadas de entornos Testnet, nunca claves de Binance de producción. Guárdalas en la PC con acceso limitado y no las envíes al portal ni al repositorio. Las pruebas de Spot y Futures validan infraestructura, no rentabilidad.

## Qué hace cada ciclo

1. Selecciona los pares USDT con mayor volumen y excluye stablecoins y tokens apalancados.
2. Descarga únicamente velas cerradas de 4 horas.
3. Calcula EMA 20/50, RSI 14, ATR 14, volumen, momentum y breakout de 20 velas.
4. Penaliza nuevas entradas cuando el régimen de BTC es bajista.
5. Revisa stops, objetivos y trailing stops de posiciones existentes.
6. Envía como máximo tres candidatos a la IA.
7. Dimensiona cada entrada según la distancia al stop y los límites globales.
8. Registra señales, revisiones, operaciones y equity en SQLite.

## Monitorización remota

La versión 0.2 añade:

- Semáforo del motor basado en la hora real del último ciclo exitoso.
- Estados `OPERATIVO`, `RETRASADO` y `SIN ACTIVIDAD`.
- Precio spot, valor de mercado y P&L no realizado estimado de cada posición.
- Vigilancia de posiciones abiertas aunque salgan temporalmente del top de volumen.
- Stops y objetivos evaluados contra el precio spot más reciente disponible, mientras las señales técnicas continúan usando velas cerradas.
- Panel de errores y advertencias recientes.
- `/health` devuelve HTTP 200 cuando el ciclo está al día y HTTP 503 cuando falta actividad.

El dashboard continúa escuchando en localhost. El portal remoto está publicado en Cloudflare y recibe conexiones salientes de `trader.remote_agent`; no necesita VPN ni puertos entrantes en Windows. Consulta `DEPLOYMENT.md`.

## Research Lab v0.6

El portal incluye un laboratorio multi-cripto para `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` y `XRPUSDT`. Por cada activo compara cinco familias: tendencia base, momentum rápido, tendencia conservadora, pullback en tendencia y reversión a la media.

Cada ejecución descarga hasta 5,000 velas cerradas por activo y aplica:

- Señal al cierre y ejecución en la apertura de la vela siguiente, evitando anticipación de datos.
- Comisión y slippage en entradas y salidas.
- Stops y objetivos intravela; cuando el orden es ambiguo, supone primero el stop.
- Walk-forward rodante con selección en entrenamiento y evaluación fuera de muestra.
- Ranking ajustado por Sharpe, Calmar, drawdown, exceso frente a buy-and-hold, rotación y número de operaciones.
- Heurística de sobreajuste basada en el rango fuera de muestra de la estrategia seleccionada.
- 1,000 simulaciones Monte Carlo de las operaciones fuera de muestra.
- Auditoría de duplicados y huecos en las velas.
- Separación de resultados en regímenes alcistas, laterales y bajistas.
- Comparación de asignación por ventanas alineadas y matriz de correlaciones; no es un backtest conjunto de ejecución del portafolio.
- Sensibilidad del candidato ante cambios pequeños del umbral de entrada.
- Separación explícita entre estrategia fija y selector adaptativo.
- Benchmark de efectivo USDT al 0%: superar un mercado bajista no basta si la estrategia pierde dinero.
- Cash gate: el selector adaptativo no opera cuando el periodo de entrenamiento no demuestra retorno, Sharpe y actividad mínimos.
- Catorce puertas de evidencia en 0.6.10, incluyendo ventaja frente a comprar y mantener cada activo en desarrollo y ventana final, costos duplicados y mínimos de actividad.

El cálculo se ejecuta en un proceso independiente para no bloquear el motor ni el portal. Pulsa una fila del informe para ver el diagnóstico del activo o utiliza `Exportar CSV` para conservar el resumen.

Los resultados parten en `RESEARCH`: ni el ganador ni sus parámetros se transfieren al motor automáticamente. La columna `OOS fija` pertenece siempre al candidato mostrado; `Selector adaptativo` representa una política distinta que puede cambiar de estrategia entre ventanas o conservar USDT. El pipeline visible es `RESEARCH → CANDIDATE → FORWARD_TEST → TESTNET → APPROVED`; cada promoción exige aprobación del propietario y `APPROVED` nunca habilita LIVE. Consulta `RESEARCH_METHODOLOGY.md` para límites y criterios.

El portal local y el remoto distribuyen la misma interfaz. El remoto exige autenticación, no almacena datos privados en caché y puede solicitar Research al agente Windows sin modificar decisiones del motor.

## Actualizaciones asistidas

La app de Windows dispone de un centro de actualización **local** y participa en un rollout firmado unificado. Desde 0.8.8, la continuidad remota ya no depende de mantener abierta la app gráfica: una tarea programada ejecuta un watchdog persistente del agente HTTPS, y cada arranque firmado del motor intenta sincronizar de forma asincrónica los módulos del agente y su política de reinicio. Tras publicar una release firmada desde main validado, el portal remoto detecta una instalación Windows anterior y solicita automáticamente la instalación supervisada. El centro local sigue disponible para verificación, recuperación o instalación manual de un paquete ya descargado si el portal no está disponible. Solicita aprobación de la identificación exacta y usa el supervisor independiente para detener el motor activo de manera cooperativa, conservar respaldo y comprobar el arranque. El portal local mantiene la ruta web existente para quien prefiera ese flujo; ninguno instala ZIP sin firma. Para publicar una versión nueva, Work prepara un PR y GitHub prueba el commit. Tras integrarlo en main, GitHub vuelve a validar Linux/Windows y publica automáticamente bajo la política autorizada por el propietario el 4 de octubre de 2026. Solo main actual puede desplegar y firmar; PRs y revisiones superadas se rechazan. El rollout instala ese paquete exacto sin una segunda aprobación rutinaria. El entorno portal-production conserva sus credenciales y cualquier revisión que se vuelva a configurar debe respetarse; CI rechaza migraciones pendientes y hace rollback si la salud falla. Consulta `GITHUB_RELEASES.md`.

El instalador gráfico antiguo basado únicamente en SHA-256 fue retirado. `trader.update_manager` verifica paquetes Ed25519, evita downgrade, conserva respaldo y recupera cambios incompletos. El supervisor de Windows instala versiones firmadas tras aprobación exacta y ofrece una restauración voluntaria del código anterior desde **Opciones → Restaurar versión anterior** cuando conserva una copia comprobable. La operación deja intactos saldos, operaciones y la secuencia antirretroceso; solo aparece después de una instalación firmada realizada por el supervisor actualizado. `ACTUALIZAR_BOT.cmd` queda como herramienta técnica local.

## Seguimiento financiero por entorno

El panel resume operaciones cerradas, P&L realizado neto de comisiones, costos simulados y drawdown observado en la curva de equity. El agente Windows actual puede enviar solo una muestra reciente; el panel la marca como parcial hasta recibir el historial completo. Un mes de observación y 30 cierres son un filtro mínimo para revisar resultados, nunca una aprobación automática para operar con dinero real. Desde 0.8.1 el portal aplica esa misma disciplina por separado a Spot Testnet y al forward test Futures Demo, mostrando retorno observado, drawdown, cierres y estabilidad operativa antes de sugerir cualquier revisión de parámetros. El registro actual no modela aportes/retiros ni contiene un benchmark histórico sincronizado, de modo que el informe no demuestra ventaja sobre comprar y mantener BTC. La ruta posterior es un forward test reproducible, luego Testnet con filtros del exchange y conciliación de órdenes, y solo después una decisión separada sobre dinero real.

En 0.6.8 el informe desglosa resultados realizados por activo, porcentaje de cierres ganadores, exposición y P&L abierto estimado con comisiones y slippage PAPER. Las estimaciones abiertas solo aparecen con precios de mercado recientes; una cotización ausente o vencida muestra «—» y bloquea decisiones de cierre basadas en velas antiguas. Las cifras por activo son diagnósticas, no recomendaciones para activar una estrategia ni permisos LIVE.

En 0.6.9 se introdujo la evaluación histórica dentro del seguimiento financiero. Desde 0.6.20 el mismo TradingEngine puede operar en PAPER o TESTNET con ledgers separados; ninguna estrategia se activa automáticamente. Cada nuevo ciclo guarda juntos equity y BTCUSDT para comparar la variación en un período idéntico. No reconstruye BTC previo ni corrige aportes/retiros, y la referencia BTC spot no incluye comisiones.

En 0.6.10 el informe muestra también BTC con comisión y slippage PAPER en ambos extremos de la misma ventana; el laboratorio exige superar la compra y tenencia del activo evaluado fuera de muestra y en la ventana final para marcar un candidato como prometedor. La evaluación detallada queda plegada para limpiar el panel. Los límites PAPER se leen de la configuración efectiva. Los diagnósticos de más de 90 días se depuran diariamente incluso si el motor está pausado; operaciones, posiciones, equity y referencia BTC se conservan. Consulta `STRATEGY_EVIDENCE.md`. Estas mejoras no activan dinero real.

En 0.6.11 el desglose muestra hasta 50 activos cerrados y concilia el resto en «Otros»; agrupa P&L neto por motivo de salida y muestra cuántas operaciones PAPER pertenecen realmente a los cinco activos del estudio. La proyección HTTPS admite este historial acotado. Antes de cada nueva compra PAPER, un diagnóstico usa las reglas públicas ya descargadas de Binance Spot para estimar si la cantidad y el valor mínimo de una hipotética orden MARKET serían compatibles. La operación simulada sigue igual: el resultado solo sirve para investigar incompatibilidades; no se envía ninguna orden. El precio spot no sustituye al precio medio que Binance puede usar para el filtro de notional, ni valida balances o ejecución Testnet. Los diagnósticos nuevos se conservan hasta 90 días; no se alteran las operaciones ni el historial financiero previo.

En 0.6.12 el portal deja visibles las puertas unificadas de promoción: ventaja frente a efectivo y mantener el activo, consistencia OOS, costos duplicados en la ventana reservada, actividad mínima y un forward test futuro. Aunque un activo supere las puertas, permanece en `RESEARCH_ONLY` y no modifica el motor PAPER. Testnet añade un planificador de cantidad y notional basado en filtros públicos y una máquina de estados sintética para probar conciliación sin enviar órdenes. La versión 0.6.15 propone GPT-6 Luna para la revisión conservadora y permite comprobar acceso y salida estructurada con `python -m trader check-ai-model --model gpt-6-luna` en Windows. El modelo está documentado oficialmente; el acceso de la cuenta concreta requiere esta comprobación. Un `OPENAI_MODEL` existente en `.env.local` prevalece sobre `config.toml`, por lo que actualizar el paquete no cambia ese archivo local: verifícalo antes de decidir el cambio. Una revisión que falle bloquea la entrada por la política `fail_closed`.

El panel 0.6.15 prioriza estado, límites y posiciones; el diagnóstico histórico queda plegado en Opciones. El control de pausa solo bloquea nuevas entradas; la vigilancia de posiciones continúa. `testnet-validate` usa la ruta oficial `/api/v3/order/test`: comprueba parámetros y firma en Testnet sin entrar al motor de ejecución; puede requerir credenciales de Testnet con permiso de operaciones, pero no crea una orden. No hay botones de cierre individual ni cambio dinámico de límites: necesitan órdenes autenticadas, confirmación, deduplicación y conciliación con Binance Spot Testnet antes de ofrecerse.

La versión 0.6.16 introdujo tres perfiles inicialmente PAPER desde el portal local de Windows: mínimo (25%), prudente (50%) y normal (100%) del límite de riesgo por entrada ya configurado. Ninguno aumenta el límite base de posición o exposición. Cerrar una posición concreta desde el portal local consulta primero una cotización nueva; si cambió más del 2% respecto al último precio mostrado, el cierre se rechaza. Un cierre completado registra comisiones simuladas y bloquea nuevas compras de ese par durante 24 horas. El portal remoto muestra estos controles en modo informativo hasta contar con la entrega segura y deduplicada de esas instrucciones. La ejecución de órdenes en Binance Spot Testnet y con dinero real permanece deshabilitada.

Desde 0.6.18, la app local sincroniza automáticamente los módulos del agente independiente desde la instalación firmada al iniciarse, después de un update local y tras detectar una instalación efectuada por el portal remoto mientras la app está abierta. Solo reinicia la tarea del agente cuando hay archivos nuevos verificados; conserva un respaldo y deja en el menú **Reparar conexión del portal** para incidencias. Si la versión anterior de la app ya estaba abierta antes de instalar 0.6.18, ciérrala y ábrela una vez para activar esta mejora. En 0.6.17 se retiraron las dos comprobaciones antiguas del indicador; hoy el portal local/remoto permite elegir el modelo, reiniciar el motor activo, cambiar entre PAPER/TESTNET de forma supervisada y ver el estado efectivo. `OPENAI_MODEL` presente en `.env.local` prevalece sobre `config.toml`; el control actualiza únicamente esa línea y comprueba el nuevo arranque.

## Centro de control de Windows

Haz doble clic en `Crypto AI Trader.vbs` para abrir una aplicación gráfica sin consola. Tres tarjetas muestran Spot, Futures Demo y AI Market Pulse Shadow: estado y entorno reales, equity y resultado separados, posiciones, confirmación de protecciones y última evaluación. Los datos ausentes o antiguos se distinguen de los valores cero; el fallo de sincronización HTTPS no se presenta como caída de los motores. Las consultas locales de solo lectura se ejecutan en paralelo sin bloquear la ventana. El enlace de Market Pulse abre su panel con fuentes, eventos y controles Shadow. Desde la misma app puedes abrir el portal local o remoto; buscar e instalar actualizaciones firmadas; reiniciar el proceso supervisado; pausar nuevas entradas Spot y configurar el inicio automático. Si Internet falla, el botón puede comprobar un paquete firmado previamente descargado; no puede descubrir versiones que no estén ya en la PC. El supervisor independiente debe estar configurado y la versión debe estar firmada, vigente y ser más reciente. Al minimizar o cerrar, el único indicador continúa en el área de notificaciones de Windows.

Desde 0.10.15, volver a abrir la app muestra el indicador existente en la misma sesión de Windows en lugar de crear otro; el inicio automático minimizado permanece silencioso. Las reparaciones del agente se ejecutan de una en una y solo declaran conexión recuperada después de dos sincronizaciones HTTPS nuevas. Los indicadores iniciados con código anterior deben cerrarse una vez mediante **Salir del indicador**, que no detiene el motor, antes de abrir la app actualizada. Si 0.10.14 dejó al supervisor independiente sin `native_protection_compat.py`, reiniciar ese agente no basta: primero debe recuperar ese módulo desde el inventario local firmado.

## Seguridad operacional

- El dashboard escucha solo en `127.0.0.1`; no abras el puerto 8765 en el router.
- Si cambias el host para acceder remotamente, define `DASHBOARD_TOKEN` y usa una VPN privada.
- El motor principal solo permite `paper` y `testnet`; PAPER queda como respaldo/CI. Futures Demo funciona como laboratorio paralelo con credenciales y ledger separados. Cualquier modo LIVE o desconocido se rechaza y Binance LIVE no está implementado.
- Una simulación favorable no garantiza resultados reales: existen slippage, gaps, cambios de régimen, fallas de conectividad y riesgo de contraparte del exchange.

## Pruebas locales

```bash
python -m unittest discover -s tests -v
```

La siguiente fase debe comenzar solo tras revisar resultados fuera de muestra, costos, drawdown, estabilidad por activo y comportamiento durante varias semanas en simulación.


## Arquitectura v0.8.0: dos motores de prueba

- **Spot Testnet:** motor multi-activo existente, sin margen ni posiciones cortas.
- **Futures Demo:** forward test separado de BTCUSDT, LONG/SHORT, apalancamiento automático fijo en 1x y máximo una posición.
- Futures tiene ledger, journal de órdenes, historial, métricas y kill switch propios. Un fallo del forward test no debe detener el motor Spot.
- La entrada Futures usa una familia cuantitativa simétrica LONG/SHORT y pasa por una revisión IA final específica para Futures. La IA solo confirma o rechaza la señal; no cambia dirección, tamaño ni leverage.
- La cantidad inicial es 0.001 BTC, validada con `/order/test`, y la entrada se bloquea si su notional supera el presupuesto automático configurado.
- Las protecciones de Futures se revisan durante los ticks de protección aunque se pausen nuevas entradas Futures.
- Ninguna métrica de Testnet autoriza automáticamente LIVE. La evaluación de dinero real es una decisión posterior y separada.
