# Auditoría de transición — 0.10.52

Esta entrega avanza cinco frentes con componentes funcionales verificables.
Guardian conserva LEVEL0; Spot Testnet/Futures Demo conservan decisiones, límites,
AI Review y protección nativa. Pulse/Quant continúan SHADOW. Ningún resultado de
esta entrega implementa LIVE, activa control de entradas o autoriza capital.

## Cuenta observada, identidad y conciliación

`scripts/audit_testnet_inventory.py --source <instalación> --output-dir <evidencia>
--symbols BTCUSDT,ETHUSDT` consulta sólo GET en los hosts fijos Spot Testnet y
Futures Demo. Lee las cuatro credenciales Testnet existentes sin imprimirlas;
no lee ni utiliza OpenAI. Hay presupuesto de llamadas, respuesta acotada,
timeout, reloj anclado al servidor, redirecciones y proxies deshabilitados,
sin reintentos automáticos ni posibilidad de verbos de escritura.

Lee SQLite `mode=ro/query_only` directamente, sin constructores de ledgers.
Contrasta cantidades Spot contra saldo libre+bloqueado y Futures por activo y
dirección contra positionRisk; incluye órdenes estándar y familia algo/OCO.
Los IDs de cuenta/órdenes, respuestas crudas y errores externos no se guardan.
Nombres Unicode de balances son datos inertes, nunca símbolos de ejecución.

Cada producto conserva su corte más antiguo participante, incluido SQLite;
finalizar consultas posteriores no rejuvenece saldos anteriores. Los cortes no
son atómicos entre endpoints, archivos o cuentas. Una diferencia requiere
conciliación, nunca una reparación automática o repetición de POST.

El corte explícito23Oct2026 16:05UTC hizo28GET: Spot2 posiciones locales cubiertas
por balances,4 órdenes estándar y2 listas; Futures4 posiciones con cantidades
exactas,0 órdenes estándar y8 algo. Es evidencia fechada y puede cambiar durante
la operación. `uid`/`accountAlias` informados no vinculan ambos productos ni
certifican propiedad, permisos de clave o capital común. Las identidades no
se exponen en el informe. No se suman wallets.

Historial consultado: primera página de24h exclusivamente de símbolos solicitados.
Página ausente/inválida conserva UNKNOWN, nunca cero. No certifica historial
completo, aportes/retiros, todas las comisiones/funding ni inventario causal
integral. `complete_exchange_inventory` y `history_complete` permanecen false.
Un saldo libre Futures ya neto de margen no vuelve a restar reservas locales.

## Protocolo de capital y exposición SIM

`CapitalFlowShadow` une evaluación de riesgo, exposiciones activas y reserva en
la misma transacción `BEGIN IMMEDIATE` de una nueva SQLite SHADOW `SIM_FLOW_*`.
Vincula principal, nocional, riesgo, costes, política y patas; no permite
subdeclarar nocional ni tratar LONG/SHORT como cobertura. Las cantidades monetarias
son enteros micro-USDT. Dos estrategias concurrentes no gastan el mismo capital.

La reclamación de envío produce únicamente un recibo sintético durable e
idempotente. No hay ejecutor, callback o transporte de órdenes. Crash antes/después
del commit, mensajes duplicados, parciales, cancelación y reconciliación tardía
conservan invariantes. UNKNOWN/TTL no libera reservas; terminal contradictorio
requiere recuperación. Un lector anterior del protocolo SIM conserva el journal.

`python scripts/run_capital_flow_shadow.py --output-dir <directorio-nuevo>`
ejecuta16 checks en tres recetas con1000USDT ficticios por caso. Esos importes
no provienen de los100USD propuestos ni de wallets existentes. No sobrescribe
directorios o cohortes anteriores. No integra admisión operativa de motores.

## Bloqueos persistentes de pérdidas SIM

`RiskLatchesShadow` persiste baselines UTC diarios/semanales, cashflows verificados,
equity ajustada, máximo observado, bloqueos de pérdidas/drawdown/manual y recuperación.
Paso del tiempo sin baseline nuevo no libera el bloqueo. Un aporte no se convierte
en ganancia; un reset no borra el máximo. Conflictos de mensaje/evidencia dejan
disputa durable; pausa manual persiste incluso ante regresión del reloj.

`python scripts/audit_risk_latches_shadow.py --directory <directorio-nuevo>`
ejecuta nueve ensayos, incluidos reinicio, commit perdido, concurrencia,
cashflows y reloj. Políticas e identidades SIM explícitas, sin presupuestos por
defecto en la API. Pasar esa puerta de pérdida no es admisión de riesgo integral.

La base de pérdidas y Capital Flow son independientes: aún no hay atomicidad
entre ellas ni integración pre-entrada de los motores. SQLite/journal/hashes no
constituyen protección antimanipulación ni reconstrucción automática de un estado
mutable corrupto. El máximo es el observado, no un pico ausente reconstruido.

## Capital conjunto y cohortes de evidencia

`migration_evidence.py` añade hipótesis de dos motores bajo un sobre de capital
explícito: suma de asignaciones <= total y suma de riesgos <= límite conjunto.
Cada escenario conserva costes/redondeos/filtros de `migration_costs.py`; rechazo
no aumenta presupuesto, cantidad ni leverage. USD propuesto y USDT hipotético se
mantienen separados. No son saldos combinados, transferencias o reservas.

Una auditoría privada usó precios/filtros Testnet/Demo recibidos23Oct16:05UTC y
cuatro hipótesis:100USDT,50/50,0.5USDT de riesgo por motor,1.5USDT conjunto,1x,
stops nominales1.5%/3%, slippage0.1% por lado y pisos hipotéticos de comisión
0.1% Spot/0.05% Futures. Son sensibilidad matemática, no política aprobada,
tarifas LIVE o recomendación de stops. Spot Testnet informó tarifa estándar0;
no se extrapoló a producción. Una hipótesis BTC Spot/ETH Futures a1.5% fue
factible bajo esas reglas; las otras tres rechazaron el mínimo nocional Futures.
No valida funding, liquidación, profundidad, otras tasas/filtros o rentabilidad.

La API de cohortes valida registro explícito, fingerprints congelados, ancla
retenida y recibos por cadencia. Rechaza futuro, backfill, contrafactuales,
contradicciones y datos incompletos. No crea un capturador o registro durable
operativo, ni convierte spans legacy en días válidos. No inventa episodios a
partir de SELL, cashflows, costes, P&L, ventaja OOS o atribución IA.

`python scripts/audit_migration_evidence.py --input <JSON-explícito>` evalúa
cohorte y/o presupuesto conjunto sin APIs, modelos o bases. Treinta días nunca
habilitan trading. Fuente/cadencia/evidencia aportada no certifican cuenta Binance.

## Portal compartido y evidencia

System & Settings incorpora **Auditoría de transición** plegable, con dos cuentas
separadas, recetas SIM, escenarios y estado de cohortes. Mismo `web/` en Windows,
local y remoto; validador cerrado compartido con Worker, <=8000bytes. Sólo conserva
conteos, estados, propuesta/hypótesis y fechas; sin balances privados, IDs,
credenciales o textos externos. Estado vacío/incompatible queda explícito.

`scripts/publish_migration_audit.py` selecciona archivos existentes indicados por
CLI y crea archivo histórico+provenance de los bytes exactos leídos. Reemplaza
sólo su cache `data/research/migration-audit/latest.json` atómicamente. No ejecuta
auditorías ni recetas. GET/refresh sólo leen el cache; no cambian el corte, llaman
a Binance o crean wallets. Antigüedad del informe, producto y sincronización son
separadas; evidencia antigua se presenta histórica. PASSED sólo significa recetas
sintéticas: no reinicio físico de Windows, rollback real o admisión conjunta.

El campo opcional se omite antes de sacrificar evidencia financiera cuando no
cabe en480000bytes. El agente tiene un solo reintento compatible que retira ese
campo ante Worker51, conservando las proyecciones anteriores y actualizaciones.
No cambia la lista11 de módulos del agente; debe refrescarse desde instalación
firmada y verificarse después. No se añadió infraestructura o coste IA.

## Puertas que siguen pendientes

Cuenta inicial e historial/cashflows completos; vinculación verificable de cuentas
cuando proceda; reserva→único envío→reconciliación integrados en ambos motores;
estado global durable con admisión en una frontera transaccional validada;
cohortes prospectivas durables y evidencia OOS/forward suficiente; costes reales
por cuenta; recuperación operativa y autorización específica. La política de100USD
y cualquier perfil de riesgo siguen propuestas. No se configura LIVE ni se prepara
su activación por fecha. Los10 bloqueos de `live_preparation` permanecen intactos.

## Fuentes oficiales revisadas23Oct2026

- [Spot Account](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account)
- [USD-M Account](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
- [USD-M Trade, órdenes estándar y algo](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)

Publicación, firma, instalación y verificación de esta versión requieren sus
propias evidencias. Los resultados locales/CI se registran en el PR y entrega;
no se reutilizan los de51 como pruebas de52.

## Robustez del laboratorio en Windows

La esperaSQLite de los walletsSIM está acotada a5s. Un lock400ms reproduce
el error del antiguo presupuesto250ms; al liberarse conserva reserva única y
contabilidad. Si se agota la espera no hay mutación/journal/reserva. No hay
reintentos de órdenes. Las fuentes financieras/actualizador operativo no cambian.
El fixture de proceso Windows dispone de10s, conservando todas las comprobaciones
de identidad/handshake/commit; no amplía el plazo del supervisor operativo.
