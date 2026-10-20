# Opportunity & Capital Shadow — candidata 0.10.45

## Alcance

Integra observación de la intención final de nuevas entradas en los cuatro motores
y cálculo hipotético paralelo. No admite, reserva fondos efectivos, bloquea,
reduce ni ejecuta operaciones. Guardian permanece OBSERVER/LEVEL0; toda autoridad
financiera y promoción false. No modifica señales, límites aprobados, AI Advisor
individual, stops, cierres, conciliación nativa, credenciales o updater.

No es la Fase3 operativa completa ni Guardian Control Testnet. Las reservas del
Capital Protocol Lab44 son independientes y sintéticas; no se mezclan con esta
observación de propuestas auténticas ni con dinero de motores.

## Transición de arquitectura

`Motor → validaciones y revisión IA existentes → intención final observada →`
`ejecución nativa existente → resultado exchange → commit ledger existente`

La observación es una derivación sin autoridad: builder fijo → cola64 sin espera
→ un hilo del proceso supervisado → `opportunity-shadow.db`. Sin SQL, red,
consulta IA, callbacks arbitrarios o espera de consumidor en el productor.
Inicio/registro y salida/unregistro se integran en `TradingEngine.run_forever`,
bajo el mismo enabled de Guardian Intelligence. Nunca inicia otro motor.
Una excepción o cola llena descarta observación y mantiene operación nativa;
errors/dropped/capacity quedan visibles. No llamar APIs para enriquecer el DTO. Sólo rutas supervisadas instrumentadas:
Spot Testnet; PaperBroker, entradas manuales y conciliación externa no se capturan.

| Componente | Estado en45 | Límite |
|---|---|---|
| Spot/Futures AI Review | Conservado | Sin cambio de criterio ni poderes |
| Guardian schema IA | Implementado y probado sintéticamente | Aceptación real aún no observada |
| Contrato de oportunidad | Implementado, inmutable y acotado | Cuenta UNKNOWN |
| Cuatro adaptadores | Intención final/resultados | Cierres todavía sin hooks |
| Observer y journal | Persistencia/idempotencia/recuperación |16MiB/100000registros; no borrado automático |
| Riesgo/capital paralelo | Aritmética Decimal/hipótesis | Sin inventario inicial completo ni admisión real |
| Risk Engine global | Pendiente | Sin correlaciones, pérdida diaria/semanal o nueva autoridad |
| Protocolo común de cuentas | Pendiente | Prohibido conectar fondos compartidos sólo por este DTO |
| Guardian Control | Pendiente y requiere autorización | LEVEL0 se mantiene |

## Evidencia y causalidad

Cada evento≤4096bytes incluye engine/environment/version, SHA256 del identificador
nativo, etapas, patas y valores ya calculados. Se persisten números Decimal en
texto fijo, no importes float acumulados. Los IDs de órdenes/configuración/IA se
proyectan sólo como digest, nunca credenciales o texto externo arbitrario.

La intención final se fecha después de las comprobaciones nativas de entrada;
las horas originales de señal/revisión quedan en evidencia/digests. `market_at`,
`received_at`, `known_at` y `decision_at` distinguen disponibilidad real; REST sin
hora verificable conserva null. No retrodatar precios finales al cierre de vela
ni presentar recepción local como publicación del proveedor. La hipótesis causal
requiere todos los tiempos pertinentes. Evidencia posterior, vieja, ausente o
regresión de reloj produce UNKNOWN/degradación, no permisos financieros.

`EXCHANGE_RESPONSE/FILLED` no demuestra commit ledger, posición conciliada ni
protección nativa. `LEDGER_COMMIT/OPENED` sólo se observa después de una transacción
confirmada. Timeout→UNKNOWN, sin segundo POST. SELL/reduceOnly/salidas protectoras
no pasan por el observador. Sin hooks de cierre actualmente, una reserva hipotética
retenida no representa capital realmente ocupado; no se libera por TTL.

## Cálculo conservador y límites

Bruto=sum(abs(cantidad×precio)) de todas las patas; no netear LONG/SHORT ni asumir
cobertura. Se diferencian capital comprometido/margen conocido, costes de ida y
vuelta simulados, distancia nominal a stop y riesgo inclusivo estimado. Funding,
gaps, impacto de mercado, parciales reales y eficacia de hedge no se infieren.

Los ámbitos se segregan por motor y entorno. Cuenta siempre UNKNOWN: ni sumar
wallets SHADOW/PAPER/SpotTestnet/FuturesDemo ni asumir que dos cuentas coinciden.
Los topes globales y el inventario previo completo no se deducen de un límite por
operación o de los fondos libres actuales. Los adaptadores45 conservan UNKNOWN
cuando faltan esas evidencias; no afirman disponibilidad financiera global.

El evaluador puro permite RESERVED_UNVERIFIED sólo como escenario con todas sus
hipótesis numéricas y causales aportadas. Aun entonces `state=UNKNOWN` y
`real_admission=NOT_EVALUABLE`. Su lista de reservas sólo contiene propuestas
observadas y puede omitir posiciones anteriores; usar capital libre actual y
reservas previas podría contar ocupación dos veces. Por ello no completar los
campos faltantes ni conectar el evaluador a admisión real sin baseline/completitud
y semántica de capital verificadas. Ni REJECTED_UNVERIFIED veta la orden nativa.

## Persistencia y recuperación

Journal append-only con triggers, IDs idempotentes, origin digest, revisión y
conflictos latched; BEGIN IMMEDIATE. Reinicio conserva evidencia e incertidumbre.
FILLED/OPENED retienen reservas; liberación exige terminal explícito conciliado,
no un timeout. Conflictos de origen/terminal nunca se reviven silenciosamente.
Límites de disco/registros degradan observación; no podar datos automáticamente.
Lectura opcional usa SQLite mode=ro/query_only, sin crear directorio/DB ni migrar.

Heartbeat distingue consumidor vivo de última propuesta; ausencia de actividad
es normal. No sustituye frescura de mercado, salud de Binance o estado del agente.
No hay captura atómica entre DBs ni recuperación de una reserva financiera real.
Updater44/45 respalda la SQLite Spot configurada; no se amplió a una copia global.
El nuevo journal requiere política de backup específica antes de operación de
capital continua; rollback44 puede ignorarlo sin borrar evidencia o retroceder
finanzas. No se realizó rollback operativo para probar esta entrega.

## Portal único y sincronización

Tres plegables en Guardian: resumen/cobertura, capital hipotético por ámbito,
e intenciones/resultados. Conserva los siete workspaces,50plegables y enlaces
Windows al mismo `web/`. Sin botones financieros, rutas POST ni privilegios nuevos.
Datos vacíos, desconocidos, viejos y desconexión se muestran explícitamente.
Salud muestra latido, frescura del observador, capacidad y código de diagnóstico.
`freshness` corresponde al observador; cada evidencia conserva sus tiempos.

`web/opportunity-contract.js` es el mismo validador cerrado del navegador y Worker:
≤12000bytes ASCII, cuatro coberturas, hasta cinco ámbitos y seis eventos recientes,
flagsfalse/cuentaUNKNOWN/admisiónNOT_EVALUABLE. Proyección opcional con presupuesto
existente≤480000bytes; omitirla no detiene heartbeat, motores o actualización.
Agente conserva un único retry para rechazo opcional conocido y prioriza quitar
este nuevo campo frente a perder campos44. No copiar cuerpos de error arbitrarios.

## Guardian IA y costes

Conserva modelo `gpt-6-luna`, timeout, claims/cache, dos intentos/día UTC y una hora
mínima entre intentos. Schema por assessment: citas limitadas al enum de evidencias
y arrays acotados. Instrucciones explicitan longitudes; validador local histórico
sigue autoritativo. Sin truncar, inventar, reintentar fuera de cuota o resetear.

No se añadieron proveedores, suscripciones o infraestructura pagada. Desarrollo
usa fixtures y no llama al API. Los dos intentos20Oct44 fallaron con
AI_COMMENTARY_INVALID y consumieron2/2; su causa específica sigue desconocida.
La corrección sintética de contrato no acredita una respuesta real exitosa ni
rentabilidad. Esperar evaluación ordinaria con cuota disponible, sin forzarla.

## Validación y estados de entrega

Pruebas enfocadas de núcleo, adaptadores, IA, proyección, contrato Worker y UI
se ejecutaron con datos sintéticos. Validación local final: **959/959 Python offline**,157.391s TEST_RESULTS
(20Oct2026 15:49:18.882210UTC; runner157.393s), red externa bloqueada,
ningún bot iniciado; **220/220 Node**,45.607s. Dos ramas defensivas posteriores
del contrato pasaron foco actualizado14/14 (7.350s); después de corregir la
cuadrícula visual, contrato+UI finales **32/32** (4.568s). Sin fallos/errores/skips.
Windows PowerShell5.1 lifecycle/vistas, build compartido y diff-check PASS.

QA de navegador sobre preview sintético con POST403 y red externa bloqueada:
360/768/1366px sin overflow (client/scroll345/753/1351), cuatro coberturas y
ámbitos separados, cero botones financieros, plegado/Enter/detalle correctos.
Inspección inicial detectó una cuadrícula anidada estrecha y se eliminó; no se
cambiaron datos. Captura fullpage no disponible en esta superficie; capturas
visibles guardadas. El preview no prueba instalación.

CI del head exacto, main CI, publicación,
firma, instalación Windows y observación operativa son verificaciones separadas.
No atribuir resultados44 a candidata45 ni afirmar escenarios probados por inspección.


## Verificación instalada45 y correctiva remota46

45 se publicó e instaló (PR122/main5d08ca7, publicación39453869690, Ed25519,
207/207hashes). Observer45 IDLE/FRESH con tres latidos distintos y cero errores;
aún sin entradas observadas al corte16:10:37UTC. No se fuerza actividad.
El exportador incluye el DTO de1035bytes dentro de414068bytes y mantiene el Lab44.
Guardian Intelligence fue PARTIAL por Futures STALE_OR_UNPRICED_SOURCE, con
servicio/lease activos y protecciones nativas confirmadas; no se relaja el criterio.

GET remotos de ambos JS devolvieron401: faltaban en la allowlist estática del
Worker.46 corrige exactamente esas dos rutas y prueba que las APIs conservan su
autenticación/CSRF. No se considera el panel45 verificado remotamente; completar
GET200/hash de ambos scripts tras despliegue46. Esto no amplía autoridad financiera.

Auditoría45 posterior16:11:31UTC: Guardian OBSERVING, cuatro fuentes FRESH y
tres replays causales MATCH; cero errores, LEVEL0, cuota2/2 intacta. No se
relajó frescura. Seguridad main39453845081 SUCCESS; ejecución duplicada39453869860
cancelada. Publicación39453869690 SUCCESS en el mismo main45.

Validación local46: **959/959 Python offline** (157.844s TEST_RESULTS,
20Oct2026 16:16:56.557358UTC; runner157.846s), **223/223 Node** (44.546s),
build/diff PASS, sin fallos/errores/skips; red externa bloqueada, bot no iniciado.
Regresión de recursos falló401 antes del fix y pasó después. CI/rollout46 pendientes.
