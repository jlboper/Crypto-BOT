# Laboratorio 0.10.20 — metodología vigente

El estudio corre automáticamente cada 24 horas con Windows y la aplicación encendidos. Una fecha vencida se atiende una sola vez al volver a iniciar; «Actualizar análisis ahora» adelanta la ejecución. Un proceso separado, con prioridad reducida, bloqueo compartido y plazo máximo de 6,900 segundos limita el impacto en el motor. Las actualizaciones solicitan cancelación cooperativa; el informe previo permanece disponible.

**Cobertura:** hasta treinta Spot del universo líquido actual y hasta quince Futures configurados. Cada mercado tiene sus propios datos cerrados. Para Futures se requieren también velas de mark y funding público histórico USD-M; no son fills Demo. Un activo incompleto se identifica y excluye; nunca se inventa funding cero ni se sustituyen sus velas por Spot. BTC sigue siendo indispensable para los controles Spot. La elección del universo actual tiene sesgo de supervivencia/liquidez retrospectiva, por lo que no demuestra resultados de un universo histórico sin ese sesgo.

**Cartera conjunta:** tres perfiles preregistrados (prudente/base/agresivo), capital inicial configurado, cinco posiciones máximas, riesgo por operación 0.25/0.5/1%, notional por posición 15/20/30% y exposición bruta Spot 50/80/100% o Futures 50/80/150%. El tamaño incluye reserva de costos y disponibilidad de efectivo/margen. La exposición se limita al abrir; movimientos posteriores pueden superar el porcentaje objetivo. Leverage Futures 1/2/3/5/10 compara idénticas señales y límites de notional, cambiando solo margen. No equivale a multiplicar retorno por leverage.

Entradas en apertura siguiente, stop antes de target cuando OHLC es ambiguo, gaps adversos, comisiones/slippage configurados de entrada/salida, capital realmente compartido y activos por timestamps coincidentes. Funding se cobra por su timestamp/dirección/mark; en una salida intravela ambigua solo se admiten cargos adversos. La liquidación es **estrés conservador de margen aislado**, con mark OHLC y mantenimiento supuesto 1% más costo de salida; toma prioridad si fue tocada intravela. No reproduce brackets, comisiones de liquidación específicas, profundidad/latencia ni el orden intravela exacto de Binance. Una cartera Futures no califica para promoción hasta calibración por contrato y evidencia futura independiente.

**Selección y evaluación:** se conservan las cinco familias y puertas Spot descritas abajo. Cinco modelos simétricos Futures (trend, fast_trend, conservative, pullback, breakout) se comparan únicamente en entrenamiento inicial con costos; el modelo fijado pasa por ventanas OOS y final reservada. Todos los escenarios de cartera tienen desarrollo OOS, final y costos duplicados por separado; ninguno se elige por rendimiento final. Las antiguas carteras por promedio de folds son ilustraciones y aparecen rotuladas como tales. Los retornos OOS Futures por folds reinician capital cada ventana; la nueva cartera conjunta lo mantiene durante su desarrollo completo. Más activos/modelos/escenarios amplían selección múltiple: resultados exploratorios, sin afirmar PBO formal ni ventaja estadística garantizada.

**Evidencia persistida:** `data/research/runs/` retiene informes completos inmutables con identidad/hash de datos, supuestos, configuración, curvas de equity por vela, cierres y motivos de descarte. El portal proyecta hasta doce resúmenes recientes y curvas muestreadas; drawdown se calcula sobre todas las velas, no sobre los puntos muestreados. El drawdown es por equity al cierre de vela; no afirma medir el peor riesgo intravela. Se mantiene `latest.json` solo tras un análisis completo. Más días inspeccionando el mismo holdout no constituyen nueva validación.

**Seguimiento futuro:** se fija una cohorte inicial de hasta cinco Spot y hasta quince Futures con reglas y costos congelados. Solo se usan barras abiertas después del registro; no se retunan ni ordenan por resultados posteriores. Se reejecutan las reglas sobre los nuevos datos públicos, reportando valoración neta de una salida final hipotética; ese cierre terminal no cuenta entre los cierres del mínimo 30. Son observaciones PAPER de mercado público, no fills ni resultados operativos. Se muestran días, cierres y datos incompletos; un cambio de configuración registra otra cohorte conservando la anterior. No promueve candidatos automáticamente ni sustituye el forward test de ejecución revisado por el propietario.

Fuentes de endpoints públicos: [klines USD-M](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data), [mark klines](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data), [funding](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).

Las secciones siguientes documentan los controles Spot y antecedentes del laboratorio. Cuando describen cinco activos o la agregación aproximada, corresponden al informe anterior, ahora separado de la nueva cartera conjunta.

# Nota de auditoría de la copia aislada

En esta copia se aplican las correcciones descritas en `AUDIT_REPORT.md`: elección fija solo en entrenamiento inicial, ventana final reservada, costos duplicados, 14 puertas de evidencia en 0.6.10 y bootstrap circular por bloques. La agregación portfolio es una ilustración por ventanas alineadas, no ejecución conjunta. Las cifras y descripciones anteriores de v0.6.2 que difieran deben interpretarse como antecedentes. No se ha ejecutado aquí una investigación con datos reales nuevos.

# Metodología del Research Lab 0.6.12

## Objetivo

Comparar ideas de estrategia de forma reproducible y conservadora. El laboratorio busca evidencia para descartar ideas débiles; no demuestra que una estrategia vaya a ganar dinero.

## Separación operacional

- El laboratorio solo lee datos públicos de mercado y escribe `data/research/latest.json`.
- No puede enviar órdenes, cambiar `config.toml`, mover capital ni sustituir la estrategia del motor.
- Todo resultado se etiqueta `RESEARCH_ONLY`.

## Supuestos de ejecución

- Las señales calculadas con una vela cerrada se ejecutan en la apertura siguiente.
- Se cobran comisión y slippage configurados en entrada y salida.
- Stops y objetivos usan OHLC intravela. Si ambos pudieron ocurrir en la misma vela y no hay datos de menor frecuencia, se registra primero el stop.
- El tamaño de posición respeta riesgo por operación, máximo por posición y efectivo disponible.

## Validación

Para cada activo se usan 5,000 velas y ventanas rodantes de 1,200 velas de entrenamiento y 400 de prueba. La estrategia ganadora en entrenamiento se evalúa en el bloque siguiente, no visto. El informe muestra retorno compuesto fuera de muestra, buy-and-hold equivalente, porcentaje de bloques positivos y la frecuencia con que la selección terminó en la mitad inferior fuera de muestra.

Los bloques se clasifican como alcistas, laterales o bajistas según el benchmark del periodo. Además, se combinan los retornos de todos los activos con ponderación uniforme para observar el comportamiento aproximado del portafolio y se calcula una matriz de correlaciones usando fechas coincidentes.

La sensibilidad repite el candidato con el umbral de entrada cinco puntos por encima y por debajo. Si un cambio pequeño destruye el resultado, se considera una señal de fragilidad; sigue siendo un diagnóstico de muestra completa y no una prueba independiente.

## Estrategia fija y selector adaptativo

La estrategia fija usa el mismo candidato en todos los bloques fuera de muestra. El selector adaptativo elige únicamente con información del bloque de entrenamiento anterior. Si el ganador de entrenamiento tiene retorno o Sharpe no positivo, o menos de tres operaciones, el siguiente bloque permanece en efectivo. Los dos resultados se muestran separados y nunca se atribuye el retorno adaptativo al candidato fijo.

El detalle por activo muestra también el retorno OOS acumulado, número de operaciones y proporción de bloques positivos de cada candidato *solo durante el desarrollo*. Son comparaciones descriptivas sujetas a selección múltiple: no se usa la ventana final reservada para ordenarlos, no cambia la elección del campeón ni se transfieren parámetros al motor PAPER.

El efectivo en USDT se modela como un benchmark de 0% antes de intereses. Una estrategia no califica solo por perder menos que una criptomoneda: debe superar también el efectivo. Desde 0.6.10, debe superar comprar y mantener **su propio activo** con comisión y slippage en ventanas fuera de muestra y en la ventana final reservada. La comparación BTC del portafolio PAPER es otra medición, con observaciones posteriores a 0.6.9.

## Puertas de promoción

Un candidato solo obtiene la etiqueta `PROMISING_RESEARCH_ONLY` si simultáneamente supera efectivo fuera de muestra, Sharpe medio, 60% de folds positivos, estabilidad de ranking, Monte Carlo, Sharpe completo, sensibilidad de parámetros, límite de rotación y calidad de datos. Incluso esa etiqueta no autoriza su uso operativo: después requiere revisión y forward test independiente.

El portal resume estas puertas en un criterio único: ventaja neta frente a efectivo y al activo, consistencia fuera de muestra, actividad mínima, costos duplicados en la ventana reservada y forward test con datos posteriores. La etiqueta nunca cambia la configuración del motor.

Monte Carlo remuestrea los retornos de operaciones fuera de muestra 1,000 veces para estimar rango de resultados, drawdown adverso y probabilidad de terminar en pérdida. Es una prueba de incertidumbre, no una predicción.

## Limitaciones conocidas

- OHLC de cuatro horas no revela el orden exacto de eventos dentro de cada vela.
- El modelo actual es long-only y no modela profundidad del libro, latencia variable, impuestos ni fallas de exchange.
- Cinco candidatos reducen la búsqueda indiscriminada, pero no eliminan sesgos de selección.
- El laboratorio predeterminado cubre BTC, ETH, SOL, BNB y XRP; el motor PAPER rota entre los pares líquidos del día. La cobertura real de cierres se informa en el portal desde 0.6.11. No se puede atribuir a los otros activos el resultado histórico de estos cinco.
- El historial de un régimen no representa necesariamente el siguiente.
- La heurística de sobreajuste no equivale a una implementación formal de Probability of Backtest Overfitting.

## Puertas antes de cambiar el motor

1. Calidad de datos aprobada.
2. Múltiples folds fuera de muestra y ventaja estable frente al benchmark.
3. Drawdown compatible con los límites definidos.
4. Resultado Monte Carlo tolerable bajo escenarios adversos.
5. Revisión humana de operaciones y sensibilidad a costos.
6. Forward test separado durante varias semanas.
7. Cambio versionado, nuevas pruebas y autorización explícita.
