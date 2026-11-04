# 0.10.58 — fuentes y conciliación diagnóstica

Base main `7ca58e3c7ad55042eb1fdce6e2faaa146df578e0`/PR134/0.10.57.
La firma e instalación de esa base se verificaron; esta candidata requiere
sus propias pruebas, PR, validación de main, firma e instalación.

## Implementación

El mismo worker financiero Testnet/Demo normaliza cada ventana retenida mediante
`reconcile_testnet_sources`. Conserva un `reconciliation.dpapi` privado junto a
los originales; sólo el resumen cerrado de estado, razones y recuentos aparece
en `status.json`. Incluye fills por ID nativo/símbolo/cuenta, comisiones por
activo, income Futures, cortes observados e inventario local independiente.
Un ID repetido idéntico se deduplica; versiones contradictorias se excluyen y
rechazan el diagnóstico. Nunca se copia el exchange como supuesto ledger local.

Las cantidades decimales sólo se convierten a unidades enteras de escala8 si
son representables exactamente. Los importes observados que exceden esa escala
conservan su texto original y un gap. Los datos legacy float no se presentan como
decimales originales exactos. Los nombres opacos de activos financieros permanecen
cifrados y no amplían símbolos, rutas ni operaciones de trading.

El capturador incluye símbolos de posiciones/actividad local de la ventana,
además del universo configurado. Una página de1000 filas genera dos consultas
temporales disjuntas inclusivas; conserva el padre y todos los hijos. Un único
milisegundo saturado o el límite de512 consultas deja un gap explícito. El
presupuesto por tick y el backoff existente siguen vigentes. Una página corta
o vacía sólo describe su consulta, nunca acredita toda la cuenta.

Al iniciar una ventana nueva, el productor elige el recibo operacional válido
más reciente posterior a su referencia prospectiva. Una ventana activa mantiene
su original/plan tras reinicios hasta terminar. El diagnóstico expone que esta
captura acotada no rellena todos los intervalos anteriores: los recibos y huecos
originales permanecen. Esto evita atrasos crecientes al disponer de un presupuesto
de consultas menor que el necesario para procesar cada recibo de cinco minutos.
No convierte los intervalos saltados en cobertura continua financiera.

`scripts/reconcile_testnet_financial_sources.py` permite revisar originales
retenidos sin credenciales ni red. Verifica ciphertext/contenido y el enlace de
cada fuente; escribe diagnósticos cifrados en un directorio separado, sin
modificar originales, ledgers, cohortes o recibos. Repetirlo es idempotente si
las fuentes y el diagnóstico son iguales.

La captura suplementaria explícita usa exclusivamente GET para
`collateralRecord` y `assetDividend`, con ventanas/paginación acotadas y
originales cifrados. No introduce llamadas de peso alto en el worker automático.
Sus eventos pueden ayudar a investigar Earn; no prueban un ratio histórico ni
una equivalencia LDUSDT/USDT. Los diagnósticos HTTP conservan sólo códigos
numéricos; una negativa ambigua de clave/IP/permisos no demuestra qué permiso falta.

Contratos oficiales: [collateralRecord](https://developers.binance.com/en/docs/catalog/investment-and-services-simple-earn/api/rest-api/flexible-locked#get-collateral-record)
y [assetDividend](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/asset#asset-dividend-record).
El original de collateral observado usa exactamente `rows=[]`, `total=0` entero;
se admite sólo esa forma vacía adicional al contrato de total string. No se
generaliza a enteros positivos, booleanos o sobres incompletos.

## Límites conservados

El diagnóstico no tiene la forma de un bundle financiero canónico y no se
ingiere como tal. `BOUNDED_SYMBOLS` sigue sin acreditar `ALL_ACCOUNT`. Persisten
las exigencias de fronteras exactas, identidad de fills propios, cobertura de
cashflows y protección continua. Los cortes asincrónicos iguales no acreditan
conciliación histórica. No se producen días financieros cualificados por este
diagnóstico, ni se borran gaps anteriores o se reinicia la historia.

LIVE, promoción de estrategias y el borrador de capital siguen sin activarse.
No se modifican claves, permisos, fondos, riesgo o los cálculos operativos de
Spot/Futures. El guard del ejecutor LIVE y las compuertas financieras permanecen.

## Validación

Validación local final4noviembre2026: **1763/1763 Python offline PASS**, sin
fallos, errores u omisiones, fuentes intactas, red externa bloqueada y ningún
motor operativo iniciado por pruebas. **296/296 Node PASS**. Revisión independiente
y regresiones cubren exponentes extremos antes de operar/formatear, objetos
anidados malformados, checkpoint conjunto de referencia/partición, selección
actual y ventana activa fijada al reiniciar. Pruebas sintéticas de identidad,
precisión, contradicciones, privacidad, replay y capacidades GET completas.

CI, publicación, firma e instalación requieren sus evidencias separadas. Los
ensayos privados con fuentes reales son diagnósticos fechados; no sustituyen
cobertura financiera integral.
