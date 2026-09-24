# Nota de auditoría de la copia aislada

En esta copia se aplican las correcciones descritas en `AUDIT_REPORT.md`: elección fija solo en entrenamiento inicial, ventana final reservada, costos duplicados, 14 puertas de evidencia en 0.6.10 y bootstrap circular por bloques. La agregación portfolio es una ilustración por ventanas alineadas, no ejecución conjunta. Las cifras y descripciones anteriores de v0.6.2 que difieran deben interpretarse como antecedentes. No se ha ejecutado aquí una investigación con datos reales nuevos.

# Metodología del Research Lab 0.6

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
