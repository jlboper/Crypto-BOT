# AI Quant Arbitrage — laboratorio SHADOW

Esta etapa incorpora un cuarto observador dentro del proceso supervisado existente.
Funding Carry puede registrar posiciones hipotéticas cuando supera las condiciones
numéricas. Statistical Arbitrage acumula datos y calcula diagnósticos; todavía no
abre posiciones, ni siquiera simuladas. `SHADOW` es el único modo admitido.

No hay cliente de ejecución, acceso a cuentas, llamadas a IA ni activación de
Testnet/Demo/LIVE en estos módulos. La identidad «AI Quant Arbitrage» no significa
que un modelo de lenguaje decida tamaños o envíe órdenes. Guardian continúa en
Observer: no reserva fondos, veta operaciones ni amplía permisos. Spot, Futures y
Market Pulse conservan sus ledgers, riesgos y mecanismos de protección separados.

## Componentes y persistencia

- `trader/quant_models.py`: modelos deterministas sin red ni acceso a cuentas.
- `trader/quant_public.py`: conectores públicos con rutas y parámetros cerrados.
- `trader/quant_shadow.py`: servicio, cartera virtual, journal, simulación y replay.
- `data/quant-shadow.db`: SQLite independiente con WAL; conserva hipótesis,
  posiciones, operaciones cerradas, decisiones, precios contemporáneos,
  financiación observada y recibos simulados. La tabla adicional
  `quant_closed_bars` conserva cierres oficiales de un minuto con primera recepción
  y primer instante de registro. No se incorpora al repositorio.

Un hilo opcional del motor existente espera 60 segundos después de completar cada
evaluación antes de iniciar la siguiente. La cadencia efectiva incluye además el
tiempo de consultas y procesamiento; no se adelanta una consulta para eludir la
caché o el presupuesto del proveedor. Su lease persistente
se adquiere antes de consultar proveedores y se comprueba después de las lecturas,
del análisis y antes del commit. Una transacción interrumpida no puede confirmar
solo una parte del saldo, posición o journal. El servicio recupera la cartera
guardada; cambiar sus hipótesis financieras no reinicia el capital silenciosamente.
El fallo de este observador se aísla de las protecciones de los otros motores.

Una base ausente produce `NOT_STARTED` y capital desconocido; no crea una cartera
para completar una tarjeta. Un ledger ilegible produce diagnóstico degradado y
métricas desconocidas. La proyección es de solo lectura y se limita a 20 KB,
recortando historial antes que patas abiertas o totales financieros.

## Datos públicos y consumo

Se observan BTCUSDT, ETHUSDT y SOLUSDT mediante solicitudes GET anónimas. No se
requieren claves, suscripciones ni acceso autenticado. Son referencias del mercado
público, no fills de Spot Testnet ni de Futures Demo.

| Referencia | Host fijo | Ruta permitida |
| --- | --- | --- |
| Profundidad Spot, cinco niveles | `data-api.binance.vision` | `/api/v3/depth` |
| Velas Spot cerradas de un minuto | `data-api.binance.vision` | `/api/v3/klines` |
| Profundidad Futures, cinco niveles | `fapi.binance.com` | `/fapi/v1/depth` |
| Mark y funding observado, lote público filtrado a tres activos | `fapi.binance.com` | `/fapi/v1/premiumIndex` |
| Historial de funding, hasta 32 eventos | `fapi.binance.com` | `/fapi/v1/fundingRate` |
| Ajustes del intervalo de funding | `fapi.binance.com` | `/fapi/v1/fundingInfo` |

La documentación oficial distingue la tasa observada, el instante programado y
el evento histórico con su mark asociado. Los intervalos pueden cambiar; el
conector utiliza información oficial de ajustes o intervalos históricos
consistentes, sin asumir ocho horas para todos los contratos. Véanse las referencias
de [USD-M market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
y [Spot market data](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market).

El presupuesto propio sigue siendo de 15 consultas por minuto, con timeout de dos
segundos, respuesta acotada y rechazo de redirecciones. Un pase inicial completo
utiliza hasta 14 consultas; un pase normal, diez. La referencia de mark/funding se
recibe en un solo lote y solo se conservan BTC, ETH y SOL. El historial de funding
se consulta como máximo cada cinco minutos y los ajustes cada quince. Para velas
se solicitan hasta 500 al inicio o cuando una página corta no puede cubrir con
seguridad los cierres faltantes. Se comparan el último cierre aceptado y el reloj
actual al consultar, con margen para timeout y la vela abierta; normalmente se
solicitan cinco por activo y se añaden solo las nuevas.
Las respuestas de límite de consumo
activan backoff; los fallos repetidos también ralentizan las consultas. Estas
restricciones son más bajas que las cuotas del proveedor y no sustituyen sus
condiciones vigentes. No se configuran URLs arbitrarias, firmas, claves ni rutas
de órdenes o cuentas.

Cada precio conserva timestamp del proveedor y de recepción. Se admiten hasta
cinco segundos de adelanto del reloj del proveedor, pero una recepción posterior
a la decisión nunca es evidencia disponible. Los precios caducan a los 90 segundos;
las patas deben estar alineadas. Profundidad parcial o fuentes caídas no generan
precios de sustitución. La liquidez utilizable comprende solo niveles visibles
dentro de la banda de slippage, no toda la cantidad distante del libro.

## Capital y límites iniciales

Estos valores son hipótesis conservadoras registradas, no parámetros optimizados
ni garantías de pérdida máxima. La fábrica del motor reduce los límites cuando
los límites globales existentes son más restrictivos; no modifica el riesgo de
Spot ni de Futures para dar cabida a Quant.

| Concepto | Límite inicial propio |
| --- | --- |
| Capital hipotético inicial | 1.000 USDT virtuales |
| Exposición bruta de todas las patas | Máximo 15% de equity virtual |
| Riesgo estimado por posición de dos patas | Máximo 0,25% de equity virtual |
| Posiciones de dos patas simultáneas | Máximo dos |
| Apalancamiento simulado | 1x, collateral virtual por el notional completo |
| Comisión por pata y por lado | Mínimo 10 bps; puede ser mayor según configuración |
| Slippage por pata y por lado | Mínimo 10 bps; puede ser mayor según configuración |
| Límite de pérdida diaria para nuevas entradas | Máximo 1% |
| Límite de pérdida semanal para nuevas entradas | Máximo 2% |

El tamaño se limita también por estrés, costes, collateral libre y exposición
existente. El notional se calcula como cantidad por precio; el apalancamiento no
multiplica artificialmente esa cantidad. Se evita una segunda exposición Quant
al mismo activo y se prioriza el escenario de carry por su estimación neta
condicional. Esto no es una reserva compartida con las cuentas de los otros bots.

Los límites diario y semanal usan el primer equity válido observado dentro del
período UTC. Si la cohorte comienza a mediodía, esa es la baseline, no un saldo
reconstruido a medianoche. El diagnóstico conserva método, hora, valor inicial,
retorno observado y próximo reset. Un halt queda retenido hasta el siguiente día
o semana UTC correspondiente, incluso si el saldo se recupera. Una valoración o
baseline desconocida bloquea nuevas entradas. Estos retornos desde baseline no
deben etiquetarse como drawdown exacto desde el máximo del período.

## Funding Carry

El escenario estudia un LONG Spot y un SHORT Futures del mismo activo y la misma
cantidad subyacente. Ambas patas pertenecen a una sola cartera virtual separada;
no se suman balances Testnet/Demo ni se afirma que exista una cobertura ejecutable
atómicamente en esos entornos.

La entrada exige precios recientes, spreads contenidos, profundidad suficiente
en ambos lados, basis y mark compatibles, capital conocido y al menos ocho
eventos históricos consistentes. Funding actual o histórico adverso, intervalos
con huecos, costes excesivos o metadatos insuficientes producen REJECT o WAIT.
Una tasa positiva por sí sola no autoriza una posición.

La proyección aplica un recorte del 50% al menor funding positivo observado entre
la referencia actual y el historial utilizado, con horizonte máximo de 24 horas.
Resta comisiones, slippage y spreads de entrada/salida de ambas patas y reserva
por basis. También exige que la estimación de estrés quepa en el presupuesto de
riesgo. Una proyección favorable sigue siendo una hipótesis prospectiva: no es
ingreso garantizado ni saldo ganado.

La contabilidad distingue tres cosas:

1. **Tasa observada:** evidencia de mercado del proveedor.
2. **Ingreso proyectado:** escenario condicional sin abono al ledger.
3. **Funding asentado en simulación:** abono o cargo hipotético derivado de un
   evento histórico autorizado por sus timestamps, cuando la pata ya estaba
   abierta antes del instante de funding y el dato fue recibido antes de decidir.

Un recibo simulado tiene identidad persistente y se registra una sola vez. Un
funding negativo genera un débito. Los datos históricos posteriores pueden
completar una operación hipotética ya cerrada si se demuestra que estaba abierta
en aquel instante; no se imputan ingresos de antes de la entrada ni se adelantan
pagos futuros. Ninguno de estos recibos prueba un ingreso en una cuenta Binance.

La página pública está limitada a 32 eventos. Una interrupción prolongada puede
dejar un pago esperado fuera del historial recuperable. En ese caso la calidad
queda pendiente/desconocida, se ocultan equity/P&L netos y métricas que dependan
de ese resultado completo y se bloquean nuevas entradas. No se rellena el hueco
con cero ni con el funding estimado. Resolverlo requiere evidencia histórica
válida y revisión independiente, preservando los registros existentes.

## Cierres protectores y estrés de margen

La simulación comprueba cierres antes de evaluar nuevas entradas: presupuesto
estimado de pérdida, máximo de permanencia de 24 horas para carry, funding adverso,
kill switch y estrés del collateral virtual. La pausa independiente bloquea
entradas; las valoraciones, financiación y salidas protectoras continúan. Si falta
el precio de una pata, se registra la espera por datos recientes en lugar de
inventar un cierre. Un cierre protector impide reabrir ese activo en la misma
evaluación.

El proxy de estrés dispara una salida cuando la pérdida de la pata Futures,
incluida financiación negativa conocida, alcanza el 80% de su collateral virtual
de notional completo a 1x. Se evalúa la pata aunque la ganancia Spot compense el
P&L conjunto. En esa salida se añade un coste de estrés del 2% del notional
Futures de salida, usando la hipótesis congelada de legging stress.

El coste se identifica como `SIMULATED_STRESS_COST`, no como comisión. Se descuenta
una sola vez del saldo y del resultado, queda en el journal y se incluye en
`stress_costs_usdt` y en los costes totales. Es una aproximación conservadora;
no implementa las fórmulas de liquidación de Binance, mantenimiento de margen,
ADL ni la trayectoria intrabar. Un gap o una salida desfasada puede superar tanto
el riesgo estimado como esta penalización. No se promete una cobertura atómica.

## Statistical Arbitrage

Los diagnósticos de BTC/ETH, BTC/SOL y ETH/SOL usan cierres oficiales de velas Spot
de un minuto, comunes a los tres activos. Se toma una ventana acotada de hasta
500 cierres disponibles y se mantiene el mínimo de 360 observaciones del modelo.
No se interpolan minutos ni se rellenan activos ausentes. Las velas abiertas se
excluyen, así como los cierres cuyo final normalizado no preceda la recepción por
al menos cinco segundos. Las comprobaciones de antigüedad, continuidad y calidad
del modelo permanecen intactas.

La marca de cada vela representa el final exclusivo de su minuto UTC. Se guardan
por separado ese instante, su primera recepción efectiva y cuándo se registró por
primera vez en el ledger. Una vela de hace varias horas obtenida ahora solo queda
disponible para decisiones tomadas desde su recepción y registro; no se atribuye
a decisiones pasadas. Un cierre repetido conserva precio y timestamps originales.
Una contradicción o página inválida se rechaza mediante un savepoint, sin
sobrescribir evidencia ni impedir la contabilidad y protección de Funding Carry.
Una página parcial puede dejar historial insuficiente, antiguo o con huecos; no
se inventa el dato que falta.

Esta entrada resuelve la incompatibilidad entre consultar después de completar
cada evaluación y exigir minutos contiguos: una cadencia efectiva superior a
60 segundos salta algunos buckets de las observaciones instantáneas anteriores.
Esos registros originales de `quant_observations` se conservan y siguen siendo la
única entrada de los replays antiguos que los utilizaron. No se reescriben señales,
hipótesis financieras, posiciones, saldo ni P&L para aplicar el nuevo método.

La ventana histórica recibida durante la observación **no es evidencia forward ni
una validación fuera de muestra independiente**. Su procedencia se identifica con
`HISTORICAL_CLOSED_BARS_RECEIVED_DURING_OBSERVATION_NOT_FORWARD_OOS`. El modelo
ajusta la relación entre log-precios con los primeros dos tercios; el tercio
restante comprueba estabilidad sin reajustar la cobertura. Este corte cronológico
interno no elimina sesgos de selección ni valida por sí solo la estrategia.

Se muestran Z-score normalizado por entrenamiento, hedge ratio y su deriva,
cambios de media/escala, correlaciones de retornos, volatilidad, semivida AR(1)
aproximada y un estadístico residual de raíz unitaria con un rezago fijo. La
comparación con costes considera ambas patas. Relaciones inestables, huecos y
escenarios sin margen después de costes se rechazan.

El umbral residual inicial es una pantalla heurística sin p-value calibrado.
La prueba formal de Engle-Granger exige supuestos de integración y calibración
específica de residuos; la documentación primaria describe esas condiciones y
sus dificultades con huecos o colinealidad. Véanse
[cointegración en statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html),
[ADF](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html)
y [fuente de calibración MacKinnon](https://raw.githubusercontent.com/statsmodels/statsmodels/main/statsmodels/tsa/adfvalues.py).

Por ello una relación aparentemente prometedora permanece en
`WAIT / COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED`. Una correlación alta no prueba
convergencia. Seis horas de datos tampoco validan una relación de largo plazo ni
una ventaja negociable. No se copian coeficientes de calibración de statsmodels
ni se añade esa dependencia al motor. La calibración formal, selección entre
pares/hipótesis, ventanas OOS no solapadas y ejecución conservadora requieren una
etapa de investigación posterior antes de habilitar entradas estadísticas.

## Métricas, replay y límites de investigación

La cartera muestra equity virtual valorado con costes conservadores de salida,
cash libre, collateral, exposición bruta, P&L neto, costes, funding simulado,
drawdown observado, operaciones cerradas y resultados por estrategia. Win rate y
profit factor permanecen desconocidos cuando no hay denominador o financiación
completa. La ausencia de operaciones puede ser una decisión correcta.

Los benchmarks iniciales usan el primer precio Spot contemporáneo registrado:
buy-and-hold bruto sin costes y efectivo sin rendimiento supuesto. Su metodología
se indica expresamente; no se presentan como comparación equivalente con el
resultado neto de dos patas ni con una cuenta Testnet/Demo de otro período.

`replay_quant_decision(data_dir, decision_id)` reproduce el modelo numérico con
precios, funding, supuestos y observaciones inmutables disponibles en el instante
guardado. Las decisiones nuevas de StatArb congelan método de entrada, corte,
extremos de ventana, número de observaciones y digest de sus cierres. El replay
consulta únicamente registros recibidos y conocidos entonces, dentro de esa
ventana; comprueba el digest y rechaza evidencia cambiada o ausente. El primer
registro impide que una página cacheada o un backfill recibido más tarde altere
el pasado. Se almacena cada cierre una sola vez, sin repetir las 500 velas en
cada fuente ni en la proyección remota.

Los replays de decisiones anteriores, sin el marcador del nuevo método, siguen
leyendo exactamente sus observaciones instantáneas originales. Se respetan tanto
publicación/evento como recepción y registro. No se consultan APIs
actuales, noticias posteriores ni precios futuros. La coincidencia del modelo
no reproduce todos los overrides de cartera o fills, y no constituye validación
independiente ni backtest de ejecución.

Todavía faltan una reconstrucción histórica con evidencia válida, calibración
estadística, validación fuera de muestra y observación prospectiva suficiente.
Los diagnósticos sintéticos verifican mecánica; no prueban rentabilidad ni permiso
para operar. Un resultado positivo pequeño no promociona estrategias. Cualquier
ejecución nueva en Testnet/Demo y cualquier Guardian Control requieren revisión y
autorización expresas posteriores. LIVE permanece ausente.
