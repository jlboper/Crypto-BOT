# Evidencia para preparar una migración futura

Preparación de solo lectura; LIVE, promoción y reservas efectivas siguen bloqueados.
Cumplir una fecha nunca activa trading ni sustituye una autorización separada.

## Fechas y actividad comprobadas

Auditoría de las copias privadas pre48, completadas el21Oct2026 a13:29UTC.
No se iniciaron motores, servicios, proveedores o IA. Los conteos son históricos,
sin valores de P&L ni posiciones individuales.

| Motor | Primera muestra equity UTC | Última muestra de esa copia | Cierres registrados |
| --- | --- | --- | --- |
| Spot | 26Sep2026 02:09:47.964104 | 21Oct2026 13:24:34.467835 | 43 filas SELL;42 sin smoke |
| Futures | 26Sep2026 21:25:30.981405 | 21Oct2026 13:29:01.771263 | 80 filas;42 estratégicas y38 técnicas |

Sumar30 días a esas primeras muestras produce **26Oct2026 02:09:47.964104UTC**
y **26Oct2026 21:25:30.981405UTC**, respectivamente. Son referencias aritméticas
de historia legacy, **no fechas de elegibilidad** ni30 días de una cohorte vigente
certificada. Las tablas no guardan entorno/cohorte/fingerprint por operación.
Una fila SELL tampoco prueba por sí sola una posición completa e independiente.

Los settings registran inicio de protección nativa el5Oct para Spot y el9Oct para
Futures. Eso no certifica continuidad histórica de todas las protecciones ni
permite retrotraer ese mecanismo al primer punto equity. La salud actual de24h
tampoco demuestra cobertura completa durante30 días.

## Investigación y sus límites

El informe21Oct2026 13:50:14UTC conserva cohortes de mercado público separadas:

- Spot: registro13Oct02:08:55UTC,4h,8.333 días y0 cierres simulados completos.
- Futures: registro15Oct18:25:40UTC,1h,5.75 días y18 cierres simulados completos.

Sus reglas/costes se congelan y excluyen el cierre terminal forzado del mínimo de
actividad. Son simulaciones de investigación, no fills Testnet/Demo. No completan
el reloj operativo de Spot o Futures. Los fingerprints de investigación no
certifican identidad de cuenta ni todo el comportamiento ejecutor de los bots.

La referencia `SIGNAL_PARITY_ONLY` reutiliza señales operativas, pero excluye IA,
estado de posiciones, filtros/órdenes, costes/fills, salidas y conciliación de
protecciones. No contiene rentabilidad operativa validada. Walk-forward, holdout,
costes duplicados y Sharpe históricos pertenecen a modelos de investigación;
reinspeccionar el mismo holdout no crea nueva evidencia independiente.

Pulse comenzó su ledger SHADOW el16Oct12:45:38UTC y Quant el17Oct05:38:50UTC;
esa copia registraba29 cierres hipotéticos Pulse y0 Quant. No heredan30 días de
los otros motores ni autorización de ejecución. Un replay coincidente verifica
cálculos congelados, no ventaja OOS o una ejecución de múltiples patas atómica.

## Contrato requerido para una evaluación futura

Los scorecards actuales son observacionales: Spot solicita revisión tras30 días
entre muestras y30 filas SELL; Futures usa30 días y30 cierres estratégicos. No
constituyen un certificado de costes, continuidad, cohorte o preparación LIVE.
El profit factor999 de la vista Futures es un sentinel cuando faltan pérdidas;
no debe importarse como una estimación estadística finita válida.

La evaluación nueva deberá separar inicio legacy, cohorte verificable y días con
datos completos; contar episodios cerrados enlazados, sin duplicar parciales o
cierres técnicos; comprobar fees/funding atribuibles, reconciliación, cashflows,
protecciones históricas y políticas/fingerprints vigentes. Sin cadencia histórica
congelada, la cobertura30d es desconocida. Sin cashflows y una serie comparable,
el Sharpe operativo permanece desconocido. No convertir ausencias en cero ni
fijar umbrales estadísticos nuevos como si estuvieran validados.

La atribución a IA individual/Guardian permanece **NO EVALUABLE** en los cuatro
motores: no existe una cohorte contrafactual comparable validada. Pérdidas evitadas
y resultado sin IA son desconocidos. Faltan además cuenta/inventario inicial
certificados y un protocolo común operativo de capital/reconciliación.

Cada requisito debe emitir PASS/FAIL/UNKNOWN con fuente y corte verificables.
Incluso una evaluación completa sólo puede solicitar revisión humana: nunca
habilitar LIVE por fecha, resultado de backtest, simulación de costes o API de UI.
El capital permanece separado por cuenta/entorno y no se suma como una wallet real.
