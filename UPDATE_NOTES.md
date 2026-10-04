# 0.10.20 — Laboratorio diario, carteras conjuntas y seguimiento futuro

- Ejecución automática cada 24 horas con Windows/app encendidos; botón «Actualizar análisis ahora» para adelantarla. Estado durable, última/próxima ejecución, progreso, exclusión mutua manual/diaria/remota/CLI, prioridad reducida y límite de duración. El análisis cede cooperativamente ante mantenimiento de actualizaciones y conserva el último informe completo.
- Hasta 30 activos Spot del universo público líquido y los 15 configurados de Futures, separados. Datos cerrados públicos, cache incremental, mark/funding históricos USD-M y activos sin datos identificados; jamás sustituir Futures por Spot ni missing funding por cero. Histórico público de referencia, no fills Demo.
- Carteras con un reloj, capital compartido, cinco posiciones, límites de riesgo/notional/exposición, LONG/SHORT en Futures y ejecución siguiente apertura. Stops primero, gaps, comisiones/slippage, funding y estrés de liquidación por mark. Tres perfiles simulados, con 1/2/3/5/10x en Futures (18 escenarios). Leverage cambia margen, no multiplica cantidades. Mantenimiento supuesto del 1%; sin calibración de brackets, estos resultados Futures no califican para promoción.
- Selección de modelos solo en entrenamiento inicial; desarrollo OOS separado de ventana final y costos ×2. Comparar escenarios no selecciona automáticamente al ganador. Se conservan las puertas previas Spot y Monte Carlo; las ilustraciones antiguas por ventanas se etiquetan como tales.
- Archivos completos de ejecuciones inmutables, hashes de datos, parámetros, curvas/netos/drawdowns/motivos de descarte. Portal local/remoto comparten proyección acotada, hasta doce ejecuciones recientes y las carteras conjuntas; cobertura de cierres usa los activos del último informe completo.
- Cohorte de observación futura con reglas congeladas: hasta cinco Spot y hasta quince Futures. Solo velas abiertas después del registro; días/cierres separados (excluye cierres artificiales de fin de ventana), resultados simulados y gaps visibles. Ninguna promoción automática ni cambio de órdenes, configuración de riesgo operacional, capital o LIVE.
- Trabajo remoto ejecuta el código instalado en un intérprete aislado nuevo; evita reutilizar el módulo de investigación del supervisor anterior. Inventarios de dependencias del supervisor permanecen iguales.

# 0.10.19 — Confirm completed updates without the previous config validator

- Update/install and restore jobs no longer parse trading settings through an already imported independent-supervisor validator. Research still uses the full configuration; signed staging, exact approval, runtime health and committed activation remain mandatory.
- After a successful install, validate the returned healthy status, exact release identity and staged version before recording completion. Restoration similarly requires its confirmed restore identity. Actual install failures continue to fail.
- Reproduced the previous 0.10.17 validator rejecting the signed fifteen-asset 0.10.18 configuration with `ValueError: Unsupported Futures forward symbol`. The former post-install `source_settings` call could therefore mark a healthy committed installation as failed.
- Regression tests exercise the real remote-job entry point with a stale validator, confirmed install/restore, real failure and mismatched completion identity. Both independent-agent dependency inventories remain unchanged and their isolated refresh/import regression passes.
- Authenticated portal audit observed installed 0.10.18, connected Windows, fifteen Futures assets/max five positions, the failed job at 21:26:06 Mexico City, and a subsequent completed signed check reporting current 0.10.18. The generic historical ValueError alone does not expose a full Windows traceback; the reproduced defect matches the post-upgrade scenario. No operating data or historical job was rewritten.

# 0.10.18 — Fifteen Futures assets with aggregate entry budgets (candidate)

- Observe BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, AVAX, DOT, LTC, BCH, TRX, ATOM and NEAR USDT perpetual contracts. Up to five positions; current Demo availability is verified per candidate.
- Size against current exchange filters, a 100 USDT entry ceiling, 300 USDT gross portfolio ceiling and 7.5 USDT estimated loss-to-stop ceiling including a 0.5% cost reserve. Reserve another 2% in pre-submit sizing for price movement. Exchange minimums never override caps; fewer than five positions may qualify.
- Reconcile actual position identities and marks, block unknown exposure, and recheck budgets after AI review. Existing positions retain protection even over a new limit. Fills, gaps, fees and funding can exceed estimates; no guaranteed loss bound is claimed.
- Keep confirmed-entry 1x/2x/3x rotation and repair the low-level submission reset: confirm the durable plan's leverage before the order. Keep crash recovery, native stops and independent account loss gates.
- Extend shared UI and bounded Worker synchronization to fifteen signals and five positions with measured portfolio budgets. Block incompatible restoration while expanded positions/plans remain. Preserve financial history.
- Local validation: 291 offline Python tests and 76 Node tests passed, covering gross budgets, post-AI refresh, missing marks/untracked exposure, per-asset availability, five-position rotation, actual submit-layer leverage and expanded restoration/snapshot contracts. Linux/Windows CI, protected publication and installation remain separate.

# 0.10.17 — Five-asset Futures Demo and bounded leverage trials (candidate)

- Add BNBUSDT and XRPUSDT to the existing BTC/ETH/SOL forward universe; retain three positions, 4H signals, score 75 and AI review.
- Alternate confirmed Demo entries at 1x/2x/3x without scaling order quantity or the 100 USDT notional ceiling. Stops must consume less than 80% of estimated initial margin; existing account loss gates and native conditional protection remain.
- Record the selected leverage/index in the durable open plan. Commit position accounting and rotation together; reconstruct an interrupted 2x/3x fill without resubmitting. Preserve existing positions' leverage and block incompatible code restoration while leveraged state remains.
- Shared portal shows effective trial levels, next entry, leverage per close and dated gross strategy-close totals. Previous snapshots remain accepted; a bounded optional contract validates the new trial shape.
- This is infrastructure testing with fictional funds, not a matched return comparison. Different entries and missing fees/funding prevent profitability conclusions. Histories remain; trial evidence starts separately.
- Local validation: 282 offline Python tests and 76 Node tests passed, including rotation, 2x/3x configuration, crash recovery, caps, native protective-close integration and legacy/current snapshot acceptance. Linux/Windows CI, protected publication and signed Windows rollout remain separate pending checks.

# Actualización 0.10.16 — auditoría de métricas y estados del portal

- Separa cierres de estrategia y cierres técnicos Futures en los resúmenes. Win rate, profit factor y expectativa de estrategia usan únicamente su historial; los totales brutos y LONG/SHORT conservan todos los cierres y lo indican. Los cierres técnicos no completan las puertas de evidencia.
- La curva Futures representa wallet más P&L no realizado. El P&L de toda la cuenta Demo se muestra aparte y nunca se usa para inferir el precio o el resultado de un contrato. Con varias posiciones, las tarjetas por activo muestran cantidad, entrada y protecciones sin atribuirles el total de la cuenta.
- Selecciona la última revisión IA por fecha y muestra su activo y momento, también junto a las señales. Una revisión histórica no se presenta como evaluación de la señal actual.
- Corrige la pérdida media Spot: los cierres en cero no se cuentan como pérdidas. Los activos cerrados sin exposición muestran cero; una posición abierta sin cotización reciente mantiene sus estimaciones ausentes.
- Cuenta los preflights bloqueados y explica que el diagnóstico incluye versiones anteriores, sin confundir candidatas con órdenes ejecutadas. Aclara costos, períodos de los contadores y puntos porcentuales del benchmark.
- El diagnóstico Futures detecta el último ciclo atrasado aunque una concentración de muestras antiguas produzca cobertura alta. La comparación conjunta también exige ausencia de errores consecutivos activos.
- Durante una verificación pendiente del actualizador, el centro conserva el estado ocupado hasta recibir resultado de Windows. No ofrece otra instalación ni vuelve prematuramente a reposo.
- El laboratorio muestra «Sin muestras» para regímenes vacíos y explica los informes anteriores sin desglose OOS por candidata. Las pequeñas pérdidas Futures conservan seis decimales; el sentinel del profit factor sin pérdidas se presenta con texto.
- Conserva señales, estrategias, riesgo, cantidades, stops, leverage, journals y LIVE deshabilitado. No borra observaciones ni reinicia el período de auditoría. Publicación e instalación de esta versión requieren verificaciones separadas.

# Actualización 0.10.15 — conexión del agente e indicador único

- Corrige una dependencia omitida en el refresco del supervisor independiente: copia `native_protection_compat.py` desde el inventario firmado. La 0.10.14 podía instalar correctamente el bot y dejar al agente con `ModuleNotFoundError` después de la reparación.
- Prueba la igualdad de los inventarios de refresco/capacidad y los imports desde una instalación independiente vacía en un proceso Python aislado, para impedir que el checkout de desarrollo oculte dependencias faltantes.
- Si fallan los metadatos del actualizador/restauración, conserva el heartbeat básico, retira las ofertas y desactiva el rollout automático hasta recuperar el supervisor. No omite firma, secuencia ni controles de instalación/restauración.
- Un mutex por instalación/sesión evita abrir dos indicadores de Windows. Una apertura manual vuelve a mostrar el existente; el inicio minimizado no lo interrumpe. El mutex se libera al salir y se recupera tras un cierre inesperado.
- Serializa la reparación del agente entre el motor, la app y el watchdog, sin detener el motor de trading. Solo muestra conexión recuperada tras dos sincronizaciones HTTPS nuevas; los estados pendiente, deshabilitado o reparación en curso se muestran como advertencia.
- Pruebas Windows ejecutan procesos temporales con PowerShell 5.1 para validar duplicados, activación, autostart silencioso, salida/crash, exclusión de reparaciones y mensajes. No usan tareas ni datos de la PC operativa.
- Una PC afectada por la dependencia omitida de 0.10.14 puede necesitar la recuperación local de ese único módulo desde su instalación ya firmada antes de recibir el rollout. Publicación e instalación de 0.10.15 deben verificarse por separado.
- Conserva estrategias, riesgo, stops, ledgers y LIVE deshabilitado. Esta corrección no prueba por sí sola el estado de Binance o la continuidad de la conexión real.

# Actualización 0.10.14 — protección nativa Spot y Futures

- Spot Testnet instala OCO `STOP_LOSS` + `TAKE_PROFIT` con ejecución MARKET al dispararse. Futures Demo instala `STOP_MARKET` + `TAKE_PROFIT_MARKET`, cierre de posición y disparador MARK_PRICE, para LONG y SHORT.
- Conserva las señales, cantidades piloto, ISOLATED 1x y límites. Ajusta los niveles a `PRICE_FILTER` de forma conservadora; la ejecución MARKET puede deslizarse y no garantiza el precio del trigger.
- Registra identidades e intención antes de cada POST. Un envío incierto se consulta por identidad y nunca se repite a ciegas, aunque Binance no encuentre la orden. Los rechazos explícitos de validación mantienen disponible la salida local y bloquean nuevas entradas.
- Reconoce ejecuciones nativas después de un reinicio, exige evidencia del fill, contabiliza una sola vez y cancela únicamente las órdenes hermanas registradas. Un cierre local cancela y confirma sus protecciones antes de enviar otra venta/cierre.
- Reconcilia ejecuciones parciales, cancelaciones inciertas y carreras entre stop y cierre manual. Los estados ambiguos bloquean nuevas escrituras; nunca inventa un cierre a partir de un saldo o posición ausentes.
- El trailing Spot reemplaza su OCO tras cancelación confirmada. Este reemplazo tiene un intervalo sin orden nativa; si falla, se muestra sin confirmar. Sin conexión permanece el último par confirmado, mientras el trailing y las salidas por señal requieren al bot conectado.
- Migra posiciones existentes al pasar la reconciliación y verificar su identidad. El portal separa integración disponible de confirmación por posición, muestra errores y cantidad cubierta; un remanente bajo los mínimos del exchange exige revisión y no se presenta como protegido.
- Impide restaurar código sin soporte nativo mientras persista un journal de órdenes nativas. Verifica otra vez con el motor detenido para cerrar la carrera con la restauración. Los journals y ledgers no se borran para forzar un downgrade.
- Guarda `native_protection_started_at` para separar la observación de esta versión sin eliminar historia. Reinicia la ventana de estabilidad de 48–72 horas al instalar; la integración se valida en Binance durante la operación Demo.
- LIVE sigue deshabilitado. Publicación e instalación mantienen el flujo firmado con aprobación del propietario.

# Actualización 0.10.13 — integridad de ejecución y evidencia

- Une la exposición de Futures `positionRisk` V3 con `symbolConfig`, reconoce `CROSSED` y exige margen CROSS confirmado antes de una reparación. Los campos ausentes ya no provocan cierres técnicos falsos.
- Usa velas cerradas del contrato USD-M Demo y una decisión durable por símbolo/vela. Limita las revisiones IA diarias de Futures, envía el contrato y tamaño propuesto, y comprueba la pausa después de la revisión y antes del envío.
- Aplica límites diarios/semanales de pérdida a la cuenta Futures con su propio historial, sin desactivar el ciclo independiente de protección. Conserva todos los puntos financieros disponibles.
- Normaliza cantidades Spot con filtros del propio Testnet antes del preflight y combina `LOT_SIZE` con `MARKET_LOT_SIZE`. El broker vuelve a validar con precio actual antes del envío.
- Confirma contabilidad, recibo único del fill y journal aplicado dentro de una sola transacción SQLite. Un reinicio no vuelve a acreditar un SELL parcial. Incluye las comisiones en activo base en el costo y P&L.
- Separa cierres técnicos y de estrategia; los técnicos no satisfacen el mínimo de evidencia. Publica señales recientes en ambos portales y reconoce motivos de salida con prefijo TESTNET.
- Corrige umbrales propios y rendimiento SHORT del shadow lab. Inicia muestras `v2` separadas, conserva el historial anterior y etiqueta la suma bruta por cierre; no calcula rentabilidad ficticia multiplicando por leverage.
- Mantiene cantidades piloto fijas, ISOLATED 1x y los límites de riesgo; el notional estimado por entrada ahora respeta el tope configurado, sin tolerancia adicional del 25%. Una orden MARKET puede variar respecto al precio de señal. No promueve estrategias ni habilita LIVE.
- Las pruebas usan bases temporales y transportes simulados. Esta versión requiere publicación protegida y verificación de instalación; las cifras históricas borradas o las comisiones no registradas no se reconstruyen artificialmente.

# Actualización 0.10.12 — diagnóstico y robustez Spot

- Sustituye el evento genérico `Cycle failed: ValueError` por diagnósticos seguros y accionables con códigos persistentes, sin exponer excepciones crudas ni credenciales.
- Separa los rechazos esperados de guardrails de entrada (riesgo por operación, exposición, filtros del exchange, saldo Testnet y movimiento de precio antes de enviar) de los fallos reales del ciclo.
- Un guardrail esperado ahora omite esa entrada y continúa el ciclo; no incrementa el contador de errores consecutivos ni puede activar falsamente el kill switch.
- Los fallos desconocidos siguen fallando de forma cerrada y conservan el kill switch de seguridad.
- La salud de Spot muestra errores consecutivos activos y el último diagnóstico persistente; cuando el siguiente ciclo sano recupera el motor, queda registrado como recuperado.
- No cambia estrategia, score, stops, riesgo, posiciones máximas, leverage ni LIVE.

# Actualización 0.10.11 — salud de observación, analítica y consistencia visual

- Mejora la salud de observación de 24 h para distinguir incidencias recuperadas de bloqueos activos: Spot pasa a `VIGILAR` cuando hay errores/avisos recuperados con continuidad e integridad sanas, y reserva `ATENCIÓN` para cobertura baja, fallos de integridad o una concentración mayor de errores.
- Futures deja de mostrar el contador histórico ambiguo como “errores totales” y separa claramente errores consecutivos, incidentes, intentos fallidos y ciclos.
- Añade motivos concretos de salud por motor para saber por qué aparece `VIGILAR` o `ATENCIÓN`.
- Amplía la analítica Spot con expectativa neta por cierre, ganancia media, pérdida media y comisiones frente al P&L neto absoluto.
- Amplía la analítica Futures con expectativa por cierre, ganancia media y pérdida media, manteniendo LONG/SHORT separados.
- MAE/MFE no se inventa a partir de datos que el historial actual no registra; el portal lo marca explícitamente como `PENDIENTE DE TELEMETRÍA` hasta instrumentarlo de forma fiable.
- Homologa estados, mayúsculas y estilos entre Spot/Futures: `OPERATIVO`, `PROTECCIONES ACTIVAS`, `PAUSADO`, tarjetas financieras y badges usan el mismo formato visual.
- No cambia estrategia, señales, stops, riesgo, número de posiciones, leverage ni LIVE.

# Actualización 0.10.10 — estabilización del release y menú Opciones

- Corrige la superposición del menú `Opciones` para mantenerlo por encima de los paneles Spot/Futures animados.
- El cambio visual forma parte del paquete firmado del bot, por lo que requiere una versión nueva en lugar de reutilizar 0.10.9.
- Conserva la validación OIDC endurecida para PRs `release/*` del mismo repositorio hacia `main`, con `portal-production` y SHA atestiguado por GitHub.
- Añade validación temprana de sintaxis para todos los módulos JavaScript críticos del release antes de pedir aprobación de producción.
- No cambia estrategia, Spot, Futures, IA, riesgo ni LIVE.

# Actualización 0.10.9 — identidad OIDC alineada con el SHA atestiguado por GitHub

- Corrige el 403 `invalid_publisher_repository` observado después de que el portal ya se desplegara correctamente.
- El job protegido publica ahora exactamente el merge-ref SHA que GitHub atestigua en el token OIDC de una PR, eliminando la discrepancia entre el SHA empaquetado y el SHA firmado por GitHub.
- El firmante acepta solo dos identidades: el flujo histórico de `push` protegido a `main` o una PR del mismo repositorio con base `main`, rama `release/*`, ref `refs/pull/<n>/merge`, workflow exacto y environment `portal-production`.
- Se añadieron pruebas positivas y negativas para impedir ampliar accidentalmente esa identidad en el futuro.
- No cambia estrategia, Spot, Futures, IA, riesgo ni LIVE. Conserva las animaciones ligeras del portal.

# Actualización 0.10.8 — publicación firmada compatible con PR aprobada

- El portal ya pudo desplegarse y superar el health check desde la PR aprobada.
- Corrige el último guard heredado: el publicador del paquete firmado del bot exigía todavía un `push` directo a `main`, aunque el nuevo flujo de release usa una PR `release/*` aprobada.
- El publicador firmado ahora acepta únicamente el SHA validado de una PR del mismo flujo seguro: evento `pull_request`, base `main`, rama `release/*` y SHA explícito de 40 caracteres.
- Mantiene intactas la firma, verificación, rama `bot-releases`, rollback del portal y bloqueo de LIVE.
- No cambia estrategia, Spot, Futures, IA ni riesgo. Conserva las animaciones ligeras ya desplegadas en el portal.

# Actualización 0.10.7 — guard de publicación compatible con PR aprobada

- Corrige el fallo posterior a la aprobación de `portal-production`: el script de despliegue aceptaba únicamente `refs/heads/main`, aunque el workflow aprobado de una PR usa `refs/pull/<n>/merge`.
- El deploy mantiene controles estrictos: repositorio exacto, evento `pull_request`, base `main`, rama `release/*` y SHA de 40 caracteres validado explícitamente.
- El portal se publica y verifica contra el SHA real de la rama de release validada, no contra el merge-ref temporal de GitHub.
- No cambia estrategia, Spot, Futures, IA, riesgo ni LIVE. Conserva las animaciones ligeras del portal.

# Actualización 0.10.6 — aprobación protegida antes del merge

- Cambia el flujo de release para no depender de que un merge hecho por API dispare otro workflow, algo que GitHub puede suprimir para evitar cadenas recursivas de automatización.
- Las ramas `release/` ejecutan validaciones completas y, si pasan, el job de publicación queda esperando la aprobación obligatoria de `portal-production` dentro de la propia PR.
- La publicación usa exactamente el SHA de la rama de release validada. Solo después de una publicación exitosa se mergea la PR a `main`.
- Con esto, la única acción humana necesaria sigue siendo aprobar `portal-production`; el merge posterior lo realiza el asistente.
- Conserva las animaciones ligeras del portal y no cambia contenido, estrategia, riesgo, Spot, Futures, IA, credenciales ni LIVE.

# Actualización 0.10.5 — un solo disparador de publicación protegida

- Elimina la duplicidad de publicaciones que podía ocurrir al mantener simultáneamente `push main` y `pull_request_target closed`.
- La publicación protegida queda ligada a un único evento: PR mergeada. Esto evita que dos jobs intenten publicar la misma versión y que uno termine marcado como fallo aunque el otro haya avanzado.
- Las PR abiertas/sincronizadas siguen ejecutando validaciones normales antes del merge.
- Tras el merge, el workflow toma exactamente el `merge_commit_sha`, vuelve a validar y espera la aprobación obligatoria de `portal-production` antes de publicar.
- Conserva las animaciones ligeras del portal y no cambia contenido, estrategia, riesgo, Spot, Futures, IA, credenciales ni LIVE.

# Actualización 0.10.4 — publicación protegida y animaciones

- Mantiene la capa visual de animaciones ligeras introducida en 0.10.3.
- Incrementa la versión porque el paquete cambió también al corregir el workflow de publicación protegida; el guard de release bloqueó correctamente 0.10.3 al detectar archivos distintos con la misma versión.
- Ajusta el flujo de PR mergeada para usar `pull_request_target` y publicar el commit mergeado tras la aprobación de `portal-production`.
- No cambia estrategia, riesgo, Spot, Futures, IA, credenciales ni LIVE.

# Actualización 0.10.3 — animaciones ligeras del portal

- Añade una capa visual de movimiento al portal sin cambiar contenido, estrategia, cálculos, APIs ni comportamiento de trading.
- Tarjetas y paneles ganan transiciones suaves y un desplazamiento mínimo al pasar el cursor, manteniendo el diseño actual.
- Botones y controles tienen respuesta visual ligera al hover/click.
- Estados y métricas hacen una animación corta únicamente cuando cambia su texto; no se añade polling adicional ni llamadas al servidor.
- Las gráficas Spot y Futures hacen un fade corto al redibujarse con los datos que ya recibían cada 30 segundos; no se añade un loop de render continuo.
- Los estados operativos tienen un pulso muy sutil para dar sensación de actividad sin usar canvas, partículas ni GPU intensiva.
- El logo tiene una microinteracción discreta al hover y los menús/details aparecen con transiciones cortas.
- La carga inicial usa una entrada suave de encabezado, motores y paneles.
- Respeta `prefers-reduced-motion`: si el sistema solicita movimiento reducido, las animaciones se desactivan prácticamente por completo.
- Todo se ejecuta en el navegador; no añade carga relevante al Worker/servidor ni modifica el intervalo de sincronización existente.

# Actualización 0.10.2 — preflight Futures alineado con Binance v3

- Corrige el fallo observado en 0.10.1: `Futures Demo symbol state unavailable: BTCUSDT / ETHUSDT`.
- Binance `GET /fapi/v3/positionRisk` omite por diseño los símbolos sin posición ni órdenes abiertas. El preflight estaba tratando esa ausencia como error, cuando en realidad es el estado plano esperado.
- La lógica ahora separa dos fuentes oficiales: `positionRisk v3` se usa solo para detectar exposición real y `GET /fapi/v1/symbolConfig` se usa para verificar margin type y leverage de símbolos planos.
- La cuenta sigue verificando ONE_WAY con `positionSide/dual`; solo cambia a ONE_WAY cuando no hay exposición.
- Tras configurar un símbolo, vuelve a comprobar exposición cero, `ISOLATED`, `1x` y ONE_WAY antes de permitir reanudación.
- Se añadió una prueba de regresión que simula exactamente la respuesta vacía de `positionRisk v3` para un símbolo plano.
- No cambia estrategia, riesgo, sizing, IA, credenciales ni LIVE.

# Actualización 0.10.1 — preflight Futures compatible con cuenta HEDGE plana

- Corrige la causa común detrás de `bloqueados: BTC, ETH, SOL` en la reanudación supervisada de 0.10.0.
- Binance puede devolver dos filas `LONG/SHORT` por símbolo cuando la cuenta está en **HEDGE mode**, incluso con exposición cero. El preflight anterior interpretaba esas dos filas planas como estado ambiguo y bloqueaba los tres símbolos antes de poder devolver la cuenta a ONE_WAY.
- El preflight ahora distingue **HEDGE plano** de **exposición ambigua real**. Si todas las filas del símbolo están en cero, puede cambiar de forma segura la cuenta a ONE_WAY y continuar con ISOLATED + 1x. Si cualquier fila tiene exposición, falla cerrado y no cambia el modo automáticamente.
- La reanudación y el portal ahora muestran el error exacto por símbolo cuando un preflight queda bloqueado, en vez de solo listar BTC / ETH / SOL.
- No cambia estrategia, riesgo, leverage objetivo 1x, sizing, IA, credenciales ni LIVE.

# Actualización 0.10.0 — auditoría integral Futures y recuperación por estado real

Esta versión nace de una auditoría completa del flujo Futures Demo después de observar una pausa persistente con cientos de repeticiones del mismo incidente. El hallazgo principal es que el problema no era un único error de margen: era una interacción entre el journal durable, la ventana de crash entre Binance y SQLite, la caducidad de consultas históricas de órdenes y la recuperación de una apertura confirmada que podía reaparecer como posición CROSS antes de quedar registrada localmente.

Cambios de raíz:

- **Estado actual primero:** la recuperación deja de depender exclusivamente de que Binance todavía conserve una orden histórica. Antes de decidir, contrasta journal, posición local y exposición actual del exchange para el símbolo exacto.
- **Apertura confirmada + posición CROSS sin posición local:** si el journal de apertura, el plan durable, la dirección y la cantidad coinciden con una única exposición actual, reconstruye primero la posición local. Si esa exposición está en CROSS, limpia el journal de apertura ya confirmado y ejecuta un único cierre `reduceOnly` identificado; luego restaura el símbolo plano a ONE_WAY / ISOLATED / 1x. Esto corrige específicamente el ciclo que producía `Automatic Futures margin is not isolated` sin poder avanzar.
- **Crash después del commit local:** si la posición local ya existe pero quedó el journal de apertura, valida identidad contra Binance, elimina solo el journal obsoleto y repara configuración de forma segura.
- **Órdenes históricas expiradas:** Binance `-2013 Order does not exist` deja de ser una excepción infinita. Si una apertura antigua no puede consultarse y la exposición actual es cero, el journal se pone en cuarentena y se limpia, dejando una marca explícita de brecha de evidencia. Si existe exposición, no se limpia.
- **Cierres `reduceOnly`:** mantienen la regla anterior: solo se elimina un journal antiguo sin consultar la orden cuando local y exchange están inequívocamente planos.
- **Reanudar deja de ser un simple borrado del kill switch:** la acción ahora pasa por mantenimiento supervisado, detiene cooperativamente el motor, reconcilia journal, valida identidad, corrige/neutraliza exposición CROSS permitida, ejecuta preflight de todos los símbolos y solo entonces quita la pausa y reinicia el motor.
- **Anti-spam operativo:** un mismo fallo repetido se conserva como un incidente con contador, pero los WARN idénticos del motor se limitan a uno cada 15 minutos. Se separan `incidentes`, `intentos fallidos` y `ciclos` para no volver a presentar cientos de chequeos de protección como cientos de causas distintas.
- **Diagnóstico durable:** el portal recibe la última recuperación de journal y cualquier brecha de evidencia sin secretos, para que una recuperación no quede invisible.
- **Spot Testnet auditado:** el broker Spot ya reconcilia su journal por `clientOrderId` antes de cada ciclo, protege posiciones con precio de ejecución Testnet y mantiene su ledger separado. No se encontró el patrón de bloqueo de Futures ni se cambió su estrategia/riesgo.
- La tipografía de **Posiciones abiertas · Spot** permanece en el tamaño estándar restaurado en 0.9.9; el scroll horizontal es intencional para conservar homologación visual.
- No habilita LIVE ni cambia estrategia, scores, riesgo, leverage automático 1x, sizing, credenciales o límites financieros.

# Actualización 0.9.9 — cierre definitivo del journal Futures plano

- Corrige el caso que todavía podía mantener Futures en **PAUSADO + conciliación pendiente** después de 0.9.8: un journal `reduceOnly` antiguo podía quedar huérfano cuando Binance y el ledger local ya estaban planos, pero la consulta histórica de esa orden fallaba antes de que el motor comprobara ese estado seguro.
- La recuperación ahora inspecciona primero el tipo de journal. Si es un cierre `reduceOnly`, no existe posición local y Binance confirma exposición cero para ese símbolo, el journal se limpia como bookkeeping obsoleto **sin reenviar ninguna orden** y sin depender de que Binance todavía conserve la orden histórica.
- Esta excepción segura nunca aplica a aperturas ni a estados con exposición: cualquier journal de entrada o cualquier posición todavía visible sigue requiriendo reconciliación exacta por identidad.
- Se conserva un registro `forward_last_journal_recovery` con el motivo y timestamp de la limpieza segura para diagnóstico posterior.
- Añade pruebas de regresión que garantizan que el atajo plano no consulta ni reenvía órdenes y que nunca se usa para una apertura pendiente.
- Revierte únicamente el ajuste tipográfico compacto de **Posiciones abiertas · Spot**: vuelve al tamaño/espaciado original para mantener la homologación visual general, aceptando nuevamente scroll horizontal cuando sea necesario.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA, credenciales, histórico financiero ni LIVE.

# Actualización 0.9.8 — recuperación Futures y paridad visual

- Corrige un bloqueo real de recuperación de Futures: una orden de cierre `reduceOnly` ya confirmada por Binance podía dejar un `forward_pending_order` durable aunque la posición local y la del exchange ya estuvieran planas. Ese journal huérfano impedía la auto-reanudación y mantenía el motor en PAUSADO.
- La auto-recuperación ahora reconcilia primero cualquier journal pendiente. Si Binance confirma el cierre y ambos lados están planos, limpia el journal de forma segura y continúa la recuperación; si todavía hay exposición, no reenvía la orden y espera/escala sin duplicar ejecución.
- Cuando Futures está en una pausa automática y ya está plano, el bucle de protección puede completar la recuperación segura sin esperar al siguiente ciclo de estrategia. Las pausas manuales nunca se reanudan solas.
- Evita convertir la latencia transitoria del endpoint de posiciones después de un cierre FILLED en cientos de errores repetidos.
- Conserva los errores históricos, pero el portal deja de presentarlos como un porcentaje contra ciclos (que podía superar 1000% por incluir varios chequeos de protección por ciclo). Ahora los identifica explícitamente como eventos históricos.
- Homologa la tarjeta **IA final** de Futures con Spot: muestra el veredicto/estado y debajo el mismo modelo compartido. Spot y Futures continúan usando la configuración IA común; actualmente `gpt-6-luna` cuando ese es el modelo activo.
- La tabla de posiciones Spot usa tipografía/espaciado más compacto en escritorio para evitar scroll horizontal innecesario; en pantallas pequeñas conserva scroll deliberadamente.
- No cambia estrategia, señales, umbral de entrada, riesgo, leverage automático 1x, sizing, credenciales, ledgers ni LIVE.

# Actualización 0.9.7 — contrato portal/Windows y versión visible

- Corrige el HTTP 400 de sincronización introducido al añadir `pause_diagnostics.incident` en 0.9.6: el agente Windows ya emitía el campo, pero el validador del Worker todavía no lo aceptaba.
- El Worker acepta ahora el objeto `incident` únicamente con su forma acotada y validada, conserva compatibilidad con snapshots anteriores sin ese campo y rechaza formas malformadas.
- Añade pruebas de regresión específicas para que el contrato de diagnóstico Futures actual y el legado sean aceptados por el portal antes de publicar.
- Regla permanente: todo campo nuevo del snapshot remoto debe actualizar en la misma PR el validador del portal y una prueba de compatibilidad. Una release no debe romper los heartbeats por evolución unilateral del esquema.
- El encabezado compartido del portal muestra en letra pequeña la versión instalada junto al nombre **Crypto AI Trader**. En remoto toma `installed_version` del heartbeat; en local la obtiene del `pyproject.toml` instalado.
- No cambia estrategia, señales, riesgo, leverage, sizing, credenciales, ledgers ni LIVE.

# Actualización 0.8.14 — portabilidad y memoria durable del proyecto

- Añade `PROJECT_HANDOVER.md` como punto de entrada obligatorio para futuros mantenedores o modelos de IA: misión, arquitectura, invariantes, estado, ideas futuras y checklist de toma de control.
- Añade `PROJECT_HISTORY.md` para conservar decisiones arquitectónicas, enfoques abandonados, lecciones de seguridad y razones detrás de la evolución PAPER → Spot Testnet + Futures Demo.
- Añade `PORTABILITY.md` con separación explícita entre código, secretos, estado persistente y supervisor del host.
- Añade bootstrap reproducible para Windows y Linux, más un preflight de portabilidad de solo lectura. No inicia el motor, no crea credenciales y no habilita LIVE.
- `AGENTS.md` obliga a futuras sesiones de Work/IA a leer el handover e historial antes de cambiar el proyecto y a actualizar esa memoria cuando cambie la arquitectura o el roadmap.
- El objetivo es que ni la PC actual ni el historial de este chat sean puntos únicos de conocimiento: el proyecto debe poder reconstruirse y comprenderse desde el repositorio.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA de decisión, credenciales, ledgers ni LIVE.

# Actualización 0.8.13 — arquitectura Windows estable sin PowerShell en el agente

- Corrige la causa demostrada del supervisor inestable: el self-heal podía arrancar el watchdog y luego reescribir la tarea con `Set-ScheduledTask`, terminando el host PowerShell con `0xC000013A` y dejando `pythonw.exe` huérfano.
- La tarea `Crypto Paper Portal Agent` pasa a ejecutar **`pythonw.exe windows_agent.py` directamente**. PowerShell deja de formar parte de la ruta normal del agente remoto.
- Task Scheduler conserva `RestartCount=999`, por lo que si el agente termina, Windows lo relanza sin abrir consola.
- El self-heal ahora sigue un orden cerrado: detener agente → refrescar módulos firmados → reconfigurar la tarea mientras está detenida → arrancar → exigir **dos heartbeats HTTPS consecutivos** con la tarea en estado `Running`.
- Un único heartbeat ya no basta para declarar el agente saludable.
- El updater local se relanza automáticamente con el **mismo Python del supervisor** aunque lo invoque la app o el portal local, eliminando diferencias de runtime y errores de dependencias.
- Buscar actualizaciones estando en la release actual devuelve **`up_to_date` / “Ya estás actualizado”** en vez de `LOCAL_VALIDATION_FAILED`.
- El portal local acepta ese estado como éxito y no muestra 503 por estar ya actualizado.
- Mantiene firma Ed25519, hash, secuencia anti-downgrade, health-check, rollback, ledgers y credenciales sin cambios.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA ni LIVE.

# Actualización 0.8.12 — cierre de dependencias del supervisor Windows

- Corrige el `ModuleNotFoundError` persistente del updater/agente independiente.
- Añade `trader/config.py` al conjunto firmado y sincronizado del supervisor; `windows_agent.py` y `remote_agent.py` lo importan directamente.
- El agente independiente deja de importar `portal_snapshot.py` como fallback al arrancar. La proyección financiera se obtiene únicamente mediante el exportador aislado de la instalación activa.
- Esto evita que una carpeta histórica como `audit-work-v0.6.2` oculte dependencias antiguas y produzca un supervisor parcialmente actualizado.
- El self-heal reescribe siempre la acción de Task Scheduler al formato watchdog oculto después de recuperar conectividad, eliminando definiciones heredadas que abren ventanas PowerShell.
- Mantiene firma, hashes, secuencia anti-downgrade, health-check y rollback.
- Incluye todos los cambios visuales de 0.8.11 para paridad Spot/Futures.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA, credenciales, ledgers ni LIVE.

# Actualización 0.8.11 — paridad visual Spot + Futures

- Reorganiza el portal para que los dos motores tengan el mismo peso visual en desktop: Spot a la izquierda y Futures a la derecha; en móvil se apilan.
- **Límites:** añade un panel Futures equivalente con leverage automático, margen, máximo de posiciones, presupuesto de margen, score mínimo, stop mínimo/ATR y reward/risk.
- **Posiciones:** mantiene la tabla Spot y añade una tarjeta Futures con contrato/dirección, cantidad, entrada, precio estimado actual, P&L no realizado, stop/objetivo, leverage/margen y hora de apertura.
- **Seguimiento financiero:** añade un panel Futures completo con días observados, cierres, retorno, P&L, drawdown, win rate, profit factor, LONG/SHORT, errores, puertas pendientes y cierres recientes.
- Los datos Futures provienen exclusivamente de su ledger/configuración independiente. No se mezclan con Spot y no se inventan controles manuales que el motor no soporte.
- Reduce la tabla Spot para que la comparación sea más legible sin eliminar las protecciones relevantes.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA, credenciales, ejecución ni LIVE.

# Actualización 0.8.10 — runtime correcto para el updater local de Windows

- Corrige el `ModuleNotFoundError` del centro local de actualizaciones después de introducir el watchdog PowerShell.
- Si la tarea `Crypto Paper Portal Agent` ejecuta `powershell.exe`, el updater extrae el `-PythonPath` firmado/configurado en los argumentos de la tarea y deriva el `python.exe` correspondiente.
- El updater deja de caer silenciosamente a `py -3` u otro Python del sistema, evitando ejecutar el supervisor con un entorno sin sus dependencias.
- Si no puede identificar el runtime exacto del supervisor, falla de forma cerrada con un mensaje claro en vez de intentar otro intérprete.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA, credenciales, ledgers ni LIVE.

# Actualización 0.8.9 — recuperación del agente y diagnóstico persistente

- Corrige un defecto de 0.8.8 donde la autoreparación podía intentar modificar la tarea programada antes de recuperar la conexión HTTPS. Si Windows rechazaba esa modificación, el proceso terminaba antes de refrescar/reiniciar el agente.
- El orden pasa a ser: detener solo el agente → refrescar módulos firmados → arrancar con la tarea existente → confirmar sincronización HTTPS → endurecer la tarea como paso no bloqueante.
- El watchdog PowerShell se ejecuta con `-WindowStyle Hidden`; ya no debe quedar una consola visible aparentemente “pegada”.
- Añade `data/agent-self-heal.json` y `data/agent-watchdog.json` con estados seguros de fase, reintentos y exit code. No almacenan secretos, URLs privadas ni cuerpos de respuestas.
- Si endurecer Task Scheduler falla por permisos, el agente conectado permanece vivo; la recuperación remota tiene prioridad sobre la mejora de la tarea.
- Mantiene el watchdog persistente, backoff, refresh firmado del supervisor y rollback del updater.
- No cambia estrategia, señales, riesgo, leverage, sizing, IA, credenciales, ledgers ni LIVE.

# Actualización 0.8.8 — Self-Healing Rollout

- El motor Windows, después de que una release firmada quede comprometida y activada, lanza una reparación asincrónica del agente remoto. La visibilidad remota nunca bloquea el trading.
- La tarea `Crypto Paper Portal Agent` pasa a ejecutar un watchdog persistente que relanza únicamente el agente HTTPS con backoff; no inicia ni reinicia el motor de trading.
- La tarea conserva una política secundaria de hasta 999 reinicios con intervalo de un minuto, evitando agotar tres intentos y quedar desconectada indefinidamente.
- La autoreparación refresca los módulos del agente desde la instalación firmada, conserva respaldo, reinicia solo el agente y comprueba una nueva sincronización HTTPS.
- El mismo mecanismo se usa desde la opción manual **Reparar conexión del portal**, eliminando dos rutas de mantenimiento divergentes.
- Una PC que todavía tenga 0.8.6 y no haya instalado 0.8.7 puede saltar directamente a 0.8.8 cuando el agente vuelva a conectarse: el portal siempre ofrece la última release firmada superior.
- Corrige la leyenda del publicador para mostrar el modo real de la release (TESTNET/PAPER) en vez de imprimir siempre PAPER.
- No cambia estrategia, señales, riesgo, sizing, leverage, IA, credenciales, ledgers ni habilita LIVE.

# Actualización 0.8.7 — observabilidad e integridad de la muestra

- Añade un panel **Salud de observación · 24 h** separado para Spot Testnet y Futures Demo.
- Mide cobertura de ciclos contra el tiempo realmente observado, muestras esperadas, gap promedio y antigüedad del último ciclo sin penalizar un arranque reciente.
- Spot resume errores/avisos, revisiones IA/rechazos, cierres y P&L realizado de las últimas 24 horas.
- Futures resume continuidad, cierres/P&L, errores consecutivos y total de errores.
- Añade comprobaciones locales de integridad: journal de órdenes pendiente, frescura de precios, límite de posiciones Spot y restricción de una posición Futures.
- El panel clasifica la muestra como INICIANDO, ESTABLE, VIGILAR o ATENCIÓN para distinguir problemas operativos de resultados financieros.
- No cambia señales, estrategia, riesgo, leverage, sizing, universo, IA, credenciales ni rutas LIVE. Es observabilidad únicamente.

# Actualización 0.8.6 — puente de actualización remota

- Release puente compatible con el updater instalado en 0.8.4: el paquete se publica temporalmente como `PAPER` y no incluye `config.toml`, evitando el `ValueError` del verificador antiguo.
- Instala el updater/verificador nuevo, que ya acepta releases TESTNET y `config.toml` firmado para versiones posteriores.
- En modo TESTNET, Futures forward queda habilitado por diseño; la pausa operativa usa exclusivamente el kill switch dedicado. Esto corrige el estado `INACTIVO · FORWARD DESHABILITADO` aun cuando la PC conserve el config histórico.
- Mantiene firma Ed25519, secuencia anti-downgrade, health-check y rollback supervisado.
- No modifica credenciales, ledgers, estrategia, leverage ni habilita LIVE.

# Actualización 0.8.5 — Unified Rollout portal + Windows

- Una release aprobada y firmada pasa a ser una actualización integral: el portal se publica y el agente Windows detecta automáticamente si la PC sigue en una versión anterior.
- Windows recibe automáticamente un trabajo `update_install` para la release exacta. El supervisor conserva parada cooperativa, firma Ed25519, health-check y rollback.
- Si la PC estaba apagada o desconectada, el rollout se genera al volver a sincronizar.
- Una instalación que falla no se reintenta en bucle; queda registrada para revisión. Una nueva release puede volver a intentarse normalmente.
- El botón manual de instalación permanece como recuperación/fallback, pero deja de ser el paso normal.
- Esta versión es la transición: debe instalarse y refrescar el agente independiente una vez para activar el rollout automático de las versiones siguientes.
- No cambia estrategia, riesgo, leverage, credenciales, ledgers ni rutas LIVE.

# Actualización 0.8.4 — corrección de activación Futures

- Corrige el caso en que una variable local antigua `FUTURES_FORWARD_ENABLED=false` podía seguir deshabilitando el forward test aunque la configuración firmada tuviera `forward_enabled=true`.
- La activación del forward test ahora proviene únicamente de la configuración firmada. Pausar/reanudar Futures sigue usando su kill switch dedicado desde el portal.
- No cambia estrategia, leverage, tamaño, credenciales, ledger ni rutas LIVE.

# Actualización 0.8.3 — consolidación final Spot + Futures

- **Binance Spot Testnet pasa a ser el modo operativo predeterminado** del paquete. PAPER permanece disponible únicamente como respaldo técnico/CI; Binance LIVE sigue sin implementación.
- El forward test Futures Demo queda habilitado automáticamente cuando el motor está en TESTNET. El portal deja de mostrar un “INACTIVO” ambiguo y explica si el motivo es entorno incorrecto, forward deshabilitado o pausa.
- Portal local y remoto comparten una sola interfaz consolidada: dos bloques simétricos para Spot y Futures, métricas comparables y una curva independiente por motor.
- La app de Windows usa la misma jerarquía conceptual: Spot Equity/Return y Futures Wallet/P&L, con estado explícito del segundo motor.
- Se simplifica el menú normal a Motores e IA, Actualizaciones, Actividad y Diagnóstico avanzado. PAPER y smoke tests quedan plegados como herramientas técnicas.
- Las pruebas unitarias ahora declaran explícitamente su entorno en vez de depender del modo global, evitando que una prueba PAPER intente tocar Testnet por accidente.
- El paquete firmado declara su modo real desde config.toml; deja de etiquetarse siempre como PAPER.
- Se actualiza documentación obsoleta y se preservan deliberadamente ledgers, históricos, rollback, journal durable, kill switches y nombres internos de compatibilidad.
- La revisión IA final permanece en ambos motores. Los cierres protectores, stops, reconciliación y recuperación nunca esperan a la IA.

# Actualización 0.8.2 — cierre operativo para observación dual

- **Futures Demo usa el mismo modelo IA que Spot** como confirmación final fail-closed antes de una entrada automática. La IA solo puede `ALLOW` o `REJECT`; no crea la operación, no cambia LONG/SHORT, no aumenta tamaño/leverage y no elimina protecciones.
- Las escrituras Futures inciertas ahora se recuperan desde el journal durable después de fallas de Internet, proceso o energía. Una apertura confirmada puede reconstruirse desde Binance + el plan persistido; un cierre confirmado se concilia sin reenviar la orden.
- Se mantiene un **kill switch separado de Futures** y tres errores consecutivos pausan ese motor sin detener Spot.
- El portal normal se limpia alrededor de **Spot Testnet + Futures Demo**; PAPER queda plegado como respaldo técnico/CI.
- El estado Futures distingue **ACTIVO · ESPERANDO SEÑAL**, posición abierta, pausado e inactivo. El panel muestra además la última confirmación IA y el estado de recuperación.
- El centro de control de Windows refleja los dos motores y añade un watchdog con backoff que recupera el proceso del motor si desaparece inesperadamente, sin interferir con mantenimiento/updates firmados.
- Desde **http://127.0.0.1:8765** se puede buscar, verificar e iniciar directamente una actualización firmada usando el supervisor independiente de Windows; ya no hace falta abrir el portal remoto para instalar.
- La observación comparativa de 0.8.1 se conserva: días, cierres, P&L, retorno, drawdown, win rate, profit factor, LONG/SHORT, ciclos y errores.
- **LIVE sigue bloqueado.** Los stops/targets nativos persistentes en el exchange todavía no forman parte del forward test; mientras la PC esté completamente sin Internet o energía, la protección local no puede actuar. Esa capacidad queda como puerta obligatoria antes de considerar capital real.

# Actualización 0.8.1 — observabilidad comparativa Spot + Futures

- Añade un scorecard persistente del forward test Futures Demo: días observados, cierres, P&L realizado bruto, retorno observado de la cuenta, win rate, profit factor, drawdown muestreado y desglose LONG/SHORT.
- Registra ciclos y errores acumulados del segundo motor para distinguir problemas operativos de resultados de estrategia.
- El portal muestra Spot Testnet y Futures Demo en un panel comparativo con puertas de observación separadas.
- La regla mínima para una revisión formal se mantiene en **30 días y 30 cierres por motor**. Alcanzarla solo habilita revisión humana; nunca activa Binance LIVE.
- Durante el warm-up se evitan cambios de estrategia, riesgo o leverage basados en pocos días. Las correcciones operativas y de seguridad sí pueden aplicarse cuando sean necesarias.
- No cambia señales, tamaño de Spot, presupuesto Futures, leverage automático ni límites de riesgo. LIVE continúa bloqueado.

# Actualización 0.8.0 — Spot Testnet + Futures Demo en paralelo

- El portal pasa a mostrar dos motores claramente separados: **Spot Testnet** y **Futures Demo**.
- Spot conserva su estrategia multi-activo, ledger y controles actuales.
- Futures deja de ser solo un smoke lab y añade un forward test persistente de **BTCUSDT LONG/SHORT**, máximo una posición, margen `ISOLATED`, modo `ONE_WAY` y **1x automático fijo**.
- El forward test Futures arranca automáticamente al instalar 0.8.0 mientras el motor principal esté en TESTNET; no requiere un botón inicial.
- Futures usa su propio ledger, journal de órdenes y kill switch. Pausar Futures no pausa Spot, y pausar nuevas entradas Futures mantiene la protección de una posición ya abierta.
- Las pruebas manuales 1x/2x/3x quedan plegadas como diagnóstico; 2x/3x no forman parte de la ejecución automática.
- La cantidad automática inicial es `0.001 BTC`, validada con `/order/test`, y se bloquea si supera el presupuesto configurado de 100 USDT con margen de tolerancia.
- El portal muestra wallet, posición, P&L cerrado y número de cierres de Futures por separado de las métricas Spot.
- Tres errores consecutivos del forward test activan únicamente el kill switch de Futures; Spot continúa.
- Binance LIVE continúa sin host, ruta de escritura ni activación automática.

# Actualización 0.7.9 — acciones de portal de un solo clic

- Las acciones manuales mantienen un estado ocupado persistente desde el primer clic: el botón cambia a **Procesando…** y queda bloqueado mientras Windows trabaja.
- El refresco periódico del dashboard ya no puede reactivar prematuramente **Verificar Futures**, **Prueba Futures**, **Reconciliar Futures** ni el smoke Spot mientras una acción sigue en curso.
- El portal sigue automáticamente la solicitud remota hasta que Windows devuelve `completed`, `failed` o `expired`, y muestra el mensaje final sin requerir otro clic.
- **Instalar actualización** muestra inmediatamente **Instalación solicitada** después de aceptar el job y deja claro que no hay que volver a pulsar.
- Se conserva el estado fresco de Windows antes de cada acción y la idempotencia por `request_id`.
- Si Binance omite `avgPrice` en la respuesta inmediata del cierre Futures, el bot usa `cumQuote / executedQty` o consulta la orden firmada por `clientOrderId`; nunca reenvía el cierre.
- No cambia estrategia, balances, riesgo ni ejecución Binance; LIVE continúa bloqueado.

# Actualización 0.7.8 — smoke Futures 100% privado/Testnet

- La **Prueba Futures** ya no depende de ticker, funding ni exchangeInfo públicos.
- Antes de abrir una posición, valida la cantidad exacta con `POST /fapi/v1/order/test` en Futures Demo; esa llamada no ejecuta ninguna orden.
- Para BTCUSDT usa inicialmente `0.001`, la misma cantidad ya validada por **Verificar Futures**.
- El notional y margen mostrados se calculan después de la apertura a partir de `positionAmt`, `entryPrice` y leverage obtenidos mediante endpoints firmados.
- `funding_rate` queda en `null` durante este smoke técnico porque ya no consulta el endpoint público de funding.
- Apertura, lectura de posición, cierre `reduceOnly` y reconciliación siguen exclusivamente en `testnet.binancefuture.com`.
- LIVE continúa bloqueado.

# Actualización 0.7.7 — diagnóstico privado independiente de datos públicos

- **Verificar Futures** ya no depende de ticker, funding ni exchangeInfo públicos. Usa directamente `POST /fapi/v1/order/test` con BTCUSDT y cantidad `0.001`, que valida permiso TRADE sin ejecutar una orden.
- Las lecturas públicas de Futures usan la configuración de red/proxy normal de Windows; las llamadas firmadas mantienen el transporte sin proxy y el host fijo de Testnet.
- Esto separa claramente un problema de conectividad pública de un problema de credenciales o permiso Futures.
- El smoke real conserva datos públicos para dimensionar una orden válida; si ese paso falla, el mensaje ya permite distinguirlo de la verificación privada.
- LIVE continúa bloqueado para cualquier llamada firmada o escritura.

# Actualización 0.7.6 — Futures Demo resiliente a fallos públicos

- El preflight de permiso TRADE deja de consultar funding; para construir `order/test` solo usa ticker y filtros del contrato.
- Las lecturas públicas de Futures intentan primero `testnet.binancefuture.com` y, si ese GET falla, usan `fapi.binance.com` únicamente como respaldo de datos públicos.
- Las llamadas firmadas siguen fijadas exclusivamente a `testnet.binancefuture.com`: cuenta, posiciones, `order/test`, leverage, marginType y órdenes nunca tienen fallback a producción.
- El fallback público no recibe API key ni secret y no puede escribir.
- Mantiene los diagnósticos detallados de 0.7.4/0.7.5 y los botones de primer clic.
- LIVE continúa bloqueado para cualquier acción de trading.

# Actualización 0.7.5 — host REST correcto para Binance Futures Demo

- Corrige el host de USDⓈ-M Futures: la interfaz se denomina **Binance Demo Trading**, pero la API REST de prueba usa `https://testnet.binancefuture.com`.
- Revierte el host experimental `demo-fapi.binance.com`, que provocaba `Futures Testnet public connection failed`.
- Conserva todas las mejoras de 0.7.4: `POST /fapi/v1/order/test` como preflight de permiso TRADE, cantidad compatible con filtros del contrato y mensajes reales de Binance.
- Conserva los cambios de fiabilidad de primer clic del portal.
- Futures sigue separado de Spot, con fondos ficticios, ISOLATED, One-way, 1x/2x/3x, reduceOnly, journal durable y recovery.
- Binance LIVE continúa sin host ni ruta de escritura.

# Actualización 0.7.4 — diagnóstico Futures Demo + acciones de un solo clic

- **Verificar Futures** construye ahora una orden de prueba con una cantidad compatible con `minQty`, `stepSize` y `MIN_NOTIONAL`; deja de asumir que 10 USDT siempre producen una cantidad válida para BTCUSDT.
- Los rechazos HTTP de Binance conservan de forma acotada el código y mensaje de API y los muestran en Actividad, sin exponer credenciales.
- El portal ya no recomienda reconciliar de forma genérica cuando el fallo ocurrió antes de una escritura; solo el estado de recovery pendiente exige **Reconciliar Futures**.
- Las acciones manuales consultan estado fresco de Windows antes de ejecutarse, evitando depender de una caché de hasta cinco segundos.
- **Buscar actualizaciones** deja de ignorar silenciosamente un clic por el throttle usado para comprobaciones automáticas; un clic manual siempre inicia una comprobación nueva o informa que ya hay una en curso.
- **Instalar**, **Verificar Futures**, Research y otros controles remotos usan el mismo patrón de estado fresco para mejorar la respuesta al primer clic.
- Mantiene Binance Futures Demo, fondos ficticios, ISOLATED, One-way, 1x/2x/3x, reduceOnly, journal durable y LIVE bloqueado.

# Actualización 0.7.3 — verificación real de permiso Futures Demo

- Deja de bloquear Futures Demo únicamente por el campo `canTrade` de `/fapi/v3/account`.
- **Verificar Futures** ahora usa el endpoint oficial `POST /fapi/v1/order/test`: exige permiso TRADE pero no crea ni ejecuta una orden.
- El smoke también realiza ese preflight no ejecutable antes de cualquier cambio de leverage o apertura real en Demo.
- Conserva host `demo-fapi.binance.com`, fondos ficticios, margen ISOLATED, One-way, 1x/2x/3x, reduceOnly, journal durable y recovery.
- El valor reportado por la cuenta queda disponible solo como diagnóstico (`reported_can_trade`) y no como única fuente de verdad.
- Binance LIVE continúa bloqueado.

# Actualización 0.7.2 — Binance Futures Demo correcto

- Corrige el endpoint del laboratorio de derivados para usar el entorno que corresponde a las claves creadas en Binance Demo Trading: `https://demo-fapi.binance.com`.
- La v0.7.1 apuntaba al antiguo host `testnet.binancefuture.com`; por eso una clave válida de Demo podía devolver un estado de cuenta incompatible como `canTrade=false`.
- Mantiene credenciales, ledger y controles de Futures separados de Spot.
- Conserva margen `ISOLATED`, modo One-way, leverage 1x/2x/3x, cierre `reduceOnly`, journal durable y recuperación explícita.
- El portal pasa a nombrar este entorno como **Futures Demo** para coincidir con Binance.
- Binance LIVE sigue sin host, selector ni ruta de escritura.

# Actualización 0.7.1 — hardening de Futures Testnet

- Mantiene la arquitectura 0.7.0: Spot Testnet como motor principal, PAPER como respaldo/CI y Futures Testnet como laboratorio separado.
- Antes de intentar cambiar el modo de posiciones de USDⓈ-M Futures, consulta `GET /fapi/v1/positionSide/dual`; solo envía el cambio a One-way si la cuenta realmente está en Hedge Mode.
- Evita una escritura de configuración innecesaria en cada smoke test y reduce el riesgo de conflictos con cambios recientes de Binance al sincronizar modos de posiciones entre productos.
- Conserva margen `ISOLATED`, leverage limitado a 1x/2x/3x, cierre `reduceOnly`, journal durable y reconciliación explícita.
- Documenta en `.env.example` las credenciales separadas de Futures Testnet.
- Binance LIVE continúa sin host, selector ni ruta de escritura.

# Actualización 0.7.0 — TESTNET principal + laboratorio Futures aislado

- PAPER queda funcionalmente congelado como respaldo, CI y diagnóstico; las capacidades nuevas pasan a Testnet salvo correcciones de seguridad.
- Mantiene Spot Testnet como motor automático principal y conserva `trader.db`, `testnet-trader.db` y ahora `futures-testnet.db` separados.
- Añade un laboratorio paralelo de Binance USDⓈ-M Futures Testnet con credenciales independientes de Spot.
- Futures Testnet queda limitado por código a margen `ISOLATED`, modo `ONE_WAY` y leverage 1x/2x/3x.
- Añade verificación de cuenta Futures, smoke LONG/SHORT con margen ficticio pequeño, lectura de funding/liquidation price y cierre `reduceOnly`.
- Cada escritura Futures guarda primero un journal durable con `clientOrderId`; una respuesta incierta no se reintenta y exige reconciliación explícita.
- La reconciliación solo puede cerrar el símbolo registrado por el smoke y valida dirección, leverage y margen aislado antes de enviar `reduceOnly`.
- El portal reorganiza Modelo IA y motor en dos tarjetas: Motor principal (Spot/PAPER) y Laboratorio Futures Testnet.
- Binance LIVE sigue sin host, selector ni ruta de escritura.

# Actualización 0.6.26 — responsive global y Smoke Test aislado

- Unifica el ancho de todos los paneles del portal para que Actualizaciones, Modelo IA, Historial, Diagnóstico y paneles financieros compartan la misma geometría.
- Añade una capa responsive coherente para desktop, tablet y móvil: tipografías fluidas, grids 4→2→1, botones y selects de ancho completo cuando corresponde, tablas con scroll táctil y zonas de interacción de al menos 44 px.
- Corrige el panel Modelo IA y motor en móvil para que labels, selects y botones no se deformen ni desborden horizontalmente.
- La app de Windows identifica de forma explícita Binance Spot Testnet, fondos ficticios y LIVE bloqueado; cuando se alcanza el máximo de posiciones, resalta la exposición en ámbar.
- El Smoke Test Testnet ya no exige un ledger vacío. Selecciona un símbolo válido que no esté entre las posiciones estratégicas existentes, usa un límite temporal exclusivamente para la prueba y verifica que las posiciones preexistentes queden intactas tras BUY → conciliación → SELL → conciliación.
- Las órdenes pendientes siguen bloqueando la prueba. Binance LIVE continúa sin rutas de escritura.

# Actualización 0.6.25 — limpieza PAPER/TESTNET, updater visual y Smoke Test

- Limpia validaciones, mensajes y documentación heredados que todavía asumían PAPER aunque el motor unificado ya soporte PAPER y Binance Spot Testnet.
- El updater local y el supervisor usan terminología neutral y reconocen ambos entornos; el bloqueo de archivos usa el ledger efectivo del modo activo.
- La app y el portal ya no muestran PAPER por defecto mientras esperan el estado real del motor.
- El seguimiento financiero adapta sus etiquetas al entorno activo y evita presentar costos/operaciones Testnet como si fueran simulación PAPER.
- Rediseña el Centro de actualizaciones como una sola experiencia compacta: estado principal, una acción relevante y detalles técnicos plegados.
- Añade una prueba supervisada de ejecución Binance Spot Testnet. Solo funciona en TESTNET, requiere cero posiciones abiertas y ninguna orden pendiente, detiene el motor cooperativamente y usa el mismo BinanceTestnetBroker para una ida y vuelta BTCUSDT pequeña con fondos ficticios.
- El Smoke Test usa un solo escritor, journal durable e idempotencia del portal; no reintenta escrituras inciertas y siempre vuelve a levantar el motor mediante el supervisor.
- Binance LIVE sigue sin host, ruta ni modo de escritura implementado. El Smoke Test valida infraestructura, no rentabilidad.
- Conserva los nombres internos históricos necesarios para compatibilidad, como /v1/paper-controls y paper_close, sin exponerlos como estado efectivo del motor.

# Actualización 0.6.24 — comprobación de updates idempotente

- Corrige la búsqueda de actualizaciones cuando el bot ya está en la versión firmada más reciente: la secuencia actual puede verificarse para descubrimiento sin tratarse como replay ni convertirse en candidata de instalación.
- La instalación continúa siendo estrictamente monotónica: una release con la misma secuencia o una anterior sigue sin poder instalarse.
- Si Windows confirma que no hay una versión nueva, el Centro muestra `Estás actualizado · bot X · firma verificada` en lugar de registrar `ValueError`.
- Si la consulta de detalles de publicación en GitHub falla temporalmente pero Windows sigue disponible, el estado local del bot continúa siendo útil y el error externo queda como detalle secundario.
- No modifica estrategia, riesgo, balances, ledgers ni ejecución Binance Testnet.

# Actualización 0.6.23 — supervisor independiente actualizable en TESTNET

- Corrige una deuda de arquitectura detectada al intentar instalar 0.6.22 desde el portal con el motor en TESTNET: el supervisor independiente sincronizaba el heartbeat y controles, pero conservaba copias antiguas de sus módulos de instalación.
- La reparación firmada sincroniza ahora también `scripts/remote_job.py`, `trader/remote_jobs.py`, `trader/update_manager.py`, `trader/update_supervisor.py`, `trader/runtime.py` y `trader/runtime_control.py`.
- Antes de ofrecer una instalación remota, Windows verifica que todos esos módulos del supervisor independiente coincidan byte a byte con los hashes firmados de la versión instalada. Si están stale, el portal bloquea la instalación y exige reparación en vez de fallar a mitad del update.
- El refresh firmado del supervisor acepta tanto PAPER como TESTNET, siempre que la versión instalada esté comprometida en el journal firmado y cada módulo coincida con su hash.
- La clave pública de confianza, secretos, bases financieras y definición de la tarea de Windows permanecen fuera de esta sincronización.
- Mantiene el único escritor Binance Spot Testnet en el TradingEngine unificado y LIVE bloqueado.

# Actualización 0.6.22 — auto-recuperación, limpieza y pipeline de promoción

- Añade un watchdog local que compara el modo real del motor con el agente del portal y reinicia únicamente el agente saliente cuando queda desincronizado o su heartbeat se estanca. Un error HTTPS reciente no provoca bucles de reinicio.
- «Reparar conexión del portal» reinicia el agente incluso cuando sus módulos ya están actualizados, corrigiendo el caso observado en 0.6.20 donde el motor estaba en TESTNET y el agente seguía reportando PAPER.
- El centro local de actualizaciones devuelve códigos seguros y accionables en vez de mostrar solo `RuntimeError` / `ValueError`.
- La app de Windows muestra el modo real PAPER/TESTNET leído del motor; ya no deja un badge PAPER estático después de un cambio correcto de entorno.
- Retira el antiguo piloto manual de órdenes Testnet del portal y de los controles remotos. El único escritor de Binance Spot Testnet es ahora el broker del TradingEngine unificado.
- Separa el transporte firmado mínimo de Binance Spot Testnet en `trader/testnet_transport.py`, con host fijo de Testnet y sin ruta LIVE.
- Elimina código/UI ya fuera del build activo (`portal_web/`) y el ZIP histórico v0.5.0 almacenado en el repo. No se borran ledgers, historial financiero ni respaldos operativos.
- Conserva deliberadamente dos ledgers: `data/trader.db` para PAPER y `data/testnet-trader.db` para TESTNET. No se fusionan para evitar mezclar posiciones, P&L y equity entre entornos.
- Research Lab muestra un pipeline explícito de promoción: RESEARCH → CANDIDATE → FORWARD_TEST → TESTNET → APPROVED. Una estrategia que supera todas las puertas se recomienda para forward test, pero ninguna etapa se activa automáticamente.
- La recomendación de cada candidato incluye motivo, siguiente acción y requisitos mínimos previstos del forward test (30 días y 30 cierres, retorno neto positivo y ventaja frente al benchmark). Toda promoción exige aprobación del propietario.
- `APPROVED` nunca habilita LIVE. Binance LIVE continúa siendo una autorización separada, no implementada por este release.

# Actualización 0.6.21 — corrección de sincronización PAPER ↔ TESTNET

- Corrige el agente remoto para aceptar el cambio supervisado entre `data/trader.db` y `data/testnet-trader.db` dentro de la misma instalación. En 0.6.20 podía rechazar este cambio y dejar el portal mostrando un snapshot PAPER antiguo aunque el motor hubiera cambiado.
- Añade códigos de fallo seguros y mensajes claros en Actividad para credenciales Binance Testnet, trading deshabilitado, motor no saludable, mantenimiento, timeout de parada, fallo de health-check y configuración local no disponible.
- Mantiene Binance LIVE bloqueado y no modifica las reglas de riesgo ni la promoción automática de estrategias.

# Actualización 0.6.20 — motor único Binance Spot Testnet y promoción de estrategias

- Añade un único motor con dos entornos permitidos: PAPER y Binance Spot Testnet. Binance LIVE continúa sin implementación ni ruta de escritura.
- El modo Testnet usa el mismo TradingEngine, estrategia, revisión IA, límites, stops y seis niveles de riesgo; solo cambia el broker de ejecución.
- PAPER y Testnet conservan bases financieras separadas para no mezclar posiciones, P&L ni equity.
- Las órdenes automáticas Testnet guardan identidad durable antes del único POST, nunca reintentan una escritura incierta y exigen conciliación antes de otra orden.
- El supervisor, agente HTTPS, portal y actualizador reconocen PAPER/TESTNET sin duplicar motores. El cambio de entorno es supervisado desde Opciones y exige credenciales Spot Testnet operables.
- El piloto manual Testnet anterior se bloquea cuando el motor unificado está en TESTNET, evitando dos escritores sobre la misma cuenta.
- El cierre manual de una posición usa PaperBroker en PAPER y BinanceTestnetBroker en TESTNET.
- Research Lab sigue aislado de ejecución y ahora publica un pipeline explícito RESEARCH → CANDIDATE → FORWARD_TEST → TESTNET → APPROVED → RETIRED. Ningún candidato se activa automáticamente.

# Actualización 0.6.19 — seis niveles y evidencia Binance Spot Testnet

- Seis niveles para el tamaño de nuevas entradas PAPER: Mínimo 25%, Leve 35%, Prudente 50%, Moderado 65%, Alto 85% y Muy alto 100% del límite configurado. Los valores guardados anteriormente para Mínimo, Prudente y Normal conservan exactamente su significado; «Muy alto» muestra el límite que antes se llamaba «Normal». No aumenta el riesgo base ni el límite de exposición.
- El panel Testnet distingue posición abierta, una entrada ya realizada en el día UTC, conciliación pendiente y vueltas completas. Solo habilita comprar o cerrar cuando el registro permite esa operación. Muestra variación **bruta** de vueltas cerradas, sin afirmar rentabilidad neta cuando no están verificadas las comisiones.
- «Comprobar órdenes y saldo en Binance» consulta el resultado de hasta diez órdenes propias y los saldos BTC/USDT en Spot Testnet; señala diferencias respecto al registro local y bloquea nuevas operaciones si detecta una. La consulta no envía órdenes. El ensayo sigue siendo manual: ninguna estrategia envía operaciones automáticamente ni utiliza Binance de producción.

## Actualización anterior 0.6.18 — sincronización automática de la conexión del portal

- La app comprueba la instalación firmada al abrirse, después de un update local y cuando detecta uno remoto mientras sigue abierta. Si los módulos del agente independiente cambiaron, los respalda y reinicia únicamente su tarea.
- La actualización conserva «Reparar conexión del portal» como recuperación. Nunca reanuda un agente detenido intencionalmente ni reinicia el motor de trading por este motivo.
- Después de instalar 0.6.18, cierra y abre una vez la app que ya estuviera ejecutándose para cargar la mejora. Desde entonces, las siguientes instalaciones se sincronizan automáticamente mientras la app permanezca abierta.

## Actualización anterior 0.6.17 — controles del motor y primera ejecución Spot Testnet

- Menú Opciones → Modelo IA y motor: selección limitada a GPT-6 Luna o GPT-5.6 Luna y reinicio supervisado del motor PAPER. Windows comprueba la respuesta de IA antes de escribir el override local. La configuración privada sigue en la PC; el portal recibe solo el resultado. Retirados los botones redundantes de comprobación del indicador de Windows.
- Menú Opciones → Binance Testnet: compra manual BTC/USDT limitada a 25 USDT ficticios una vez al día; cierre manual de la posición registrada y conciliación por identificador de cliente. Ninguna orden va a Binance de producción. Una respuesta incierta bloquea nuevas órdenes hasta una consulta de conciliación y nunca dispara reintentos de escritura.
- Testnet y PAPER guardan registros separados. Esta primera etapa prueba ejecución y conciliación reales en Testnet, no migra la estrategia automática ni convierte el historial PAPER en P&L de Binance. El motor permanece PAPER y el uso de dinero real está deshabilitado.
- Después de instalar 0.6.17, usa Reparar conexión del portal en la PC para que el supervisor independiente reciba los nuevos controles. El estado de Testnet está disponible en el portal local y remoto, sin credenciales ni saldo privado en Cloudflare.

# Actualización 0.6.16 — controles PAPER compartidos

- El mismo panel local y remoto permite seleccionar mínimo, prudente o normal para nuevas entradas PAPER y solicitar el cierre de una posición PAPER concreta.
- El cierre exige posición idéntica, cotización nueva dentro del 2% de la vista y bloqueo de reentrada de 24 horas. No envía órdenes a Binance.
- Desde el portal remoto la solicitud permanece pendiente hasta que el supervisor de Windows confirme el resultado. El historial muestra completada, fallida o vencida.
- Después de instalar la versión firmada, el menú del indicador de Windows permite actualizar una vez los módulos verificados del supervisor independiente. El portal remoto habilita los controles cuando detecta la nueva capacidad.
- Las solicitudes remotas se guardan en la tabla de trabajos existente de D1, sin migración ni nuevos permisos para la credencial de publicación.

# Actualización 0.6.2 — estrategia fija, selector adaptativo y cash gate

## Cambios 0.6.2

- Separa el retorno fuera de muestra de la estrategia fija y del selector adaptativo.
- Corrige la ambigüedad visual que asociaba el OOS del selector con el candidato fijo.
- Añade efectivo USDT al 0% como benchmark obligatorio.
- El selector permanece en cash cuando el ganador de entrenamiento no tiene retorno, Sharpe y operaciones suficientes.
- Calcula portafolios separados para estrategias fijas y selector adaptativo con cash gate.
- Añade nueve puertas de promoción: efectivo, Sharpe OOS, consistencia, estabilidad de selección, Monte Carlo, Sharpe completo, sensibilidad, rotación y calidad de datos.
- El detalle por activo muestra resultados fijos/adaptativos, folds en cash y cada puerta aprobada o fallida.
- La exportación CSV distingue todos estos resultados.
- No modifica el motor operativo ni promueve candidatos automáticamente.

# Actualización 0.6.1 — robustez multi-régimen y portafolio

## Cambios 0.6.1

- Amplía el análisis predeterminado de 2,000 a 5,000 velas cerradas por activo.
- Usa ventanas walk-forward de 1,200 velas de entrenamiento y 400 fuera de muestra.
- Separa resultados en regímenes alcistas, laterales y bajistas.
- Añade retorno, benchmark, drawdown y Sharpe del portafolio combinado de cinco activos.
- Calcula la matriz de correlaciones con rendimientos alineados por fecha.
- Prueba sensibilidad del candidato con umbrales de entrada ±5 puntos.
- Añade vista detallada al pulsar cada activo y exportación del resumen a CSV.
- Ejecuta el trabajo pesado en un proceso separado y oculto para mantener fluidos el motor y el portal.
- Impide dos Research Labs simultáneos y detiene de forma segura una investigación antes de futuras actualizaciones.

# Actualización 0.6.0 — Research Lab multi-cripto

## Cambios 0.6.0

- Nuevo Research Lab dentro del portal para BTC, ETH, SOL, BNB y XRP.
- Compara cinco familias de estrategia por activo, sin promoción automática al motor.
- Backtesting conservador con ejecución en la vela siguiente, comisiones, slippage y resolución stop-first cuando una vela toca stop y objetivo.
- Walk-forward rodante, benchmark buy-and-hold, métricas Sharpe/Sortino/Calmar, profit factor, expectativa, exposición y rotación.
- Heurística explícita de selección/sobreajuste y 1,000 simulaciones Monte Carlo.
- Descarga paginada de hasta 10,000 velas cerradas por activo.
- Portal adaptable a móvil e instalable como aplicación web.
- Token del portal retirado de la URL y conservado solo durante la sesión del navegador.
- Cabeceras CSP, anti-framing, no-sniff y comprobación same-origin para acciones.
- El motor continúa bloqueado en PAPER y conserva exactamente sus reglas operativas actuales.

# Actualización 0.5.1 — permanencia e identidad visual de Windows

## Cambios 0.5.1

- La `X` y el botón de minimizar ocultan el Centro de Control, pero mantienen activo el indicador junto al reloj.
- La aplicación solo termina mediante `Salir del indicador` o cuando Windows cierra la sesión.
- Utiliza el bucle nativo de Windows Forms y fuerza el modo STA para mejorar la estabilidad en segundo plano.
- Activa automáticamente el inicio con Windows salvo que el usuario lo deshabilite expresamente.
- Asigna la identidad e icono propios al proceso, la ventana, la barra de tareas, el acceso de inicio y el indicador de estado.
- Reinicia el Centro de Control únicamente después de que la instancia anterior haya cerrado por completo.

# Actualización 0.5.0 — canal automático seguro

## Cambios principales

- El Centro de Control consulta automáticamente el canal estable al abrirse y cada seis horas.
- El botón de actualización descarga el paquete correcto sin pedir que el usuario busque un ZIP.
- Cada descarga se valida por HTTPS, origen, tamaño y huella SHA-256 antes de instalarse.
- La instalación siempre requiere confirmación: nunca se aplican cambios silenciosos.
- Si la red o la verificación fallan, el bot continúa ejecutando la versión instalada.
- El menú del área de notificaciones permite buscar actualizaciones o instalar un ZIP local de recuperación.
- Corrige el logotipo distorsionado del encabezado cargándolo desde PNG.
- Evita el falso aviso de error cuando el registro confirma que la actualización terminó correctamente.
- Rediseña completamente el Centro de Control con una interfaz más limpia y consistente con el portal.
- Añade tarjetas independientes para equity, rendimiento, efectivo, exposición y posiciones.
- Incorpora iconos visuales en las acciones principales.
- Añade un icono propio de Crypto AI Trader en la ventana y barra de tareas.
- El icono del área de notificaciones cambia entre verde, amarillo y rojo según el estado del motor.
- El menú del indicador muestra el estado operativo sin necesidad de abrir la aplicación.
- Corrige los caracteres españoles, acentos y símbolos en Windows PowerShell 5.1.
- Corrige el bloqueo del Centro de Control al esperar que termine el motor reiniciado.
- Reinicia automáticamente la aplicación después de instalar una versión nueva.
- Guarda registros de cada actualización dentro de `data` para facilitar diagnósticos.
- Semáforo de actividad basado en el último ciclo exitoso.
- Hora real del último ciclo, en vez de la hora de actualización del navegador.
- Precio spot y P&L no realizado estimado por posición.
- Equity calculado con el precio spot más reciente disponible.
- Stops y objetivos revisados con precio spot; las señales siguen usando velas cerradas.
- Las posiciones abiertas se vigilan aunque salgan del top de volumen.
- Panel con errores y advertencias recientes.
- Endpoint `/health` para integrar alertas externas posteriormente.

## Actualización segura en Windows

La carpeta `data` y el archivo `.env.local` no forman parte de este paquete. Al actualizar, consérvalos en la instalación existente: contienen el estado paper y las credenciales locales.

1. Detén el proceso actual `py -m trader run`.
2. Copia las carpetas `trader` y `web` de esta versión sobre las existentes.
3. Copia `tests`, `README.md` y `pyproject.toml`.
4. No reemplaces ni elimines `data`, `.env.local` o `config.toml`.
5. Ejecuta `py -m unittest discover -s tests -v`.
6. Reinicia con `py -m trader run` o vuelve a iniciar sesión para usar el arranque automático existente.

Tailscale Serve no necesita cambios: continuará apuntando a `127.0.0.1:8765`.

## Actualizador automático asistido

La versión 0.5.0 incorpora un canal estable en línea. El Centro de Control avisa cuando existe una versión nueva y puede descargarla, verificarla e instalarla con autorización del usuario. `ACTUALIZAR_BOT.cmd` y la opción de paquete local siguen disponibles como mecanismos de recuperación.

## Aplicación gráfica

`Crypto AI Trader.vbs` abre un centro de control sin mostrar PowerShell. Incluye estado, resumen de inversión, último ciclo y botones para abrir los portales, reiniciar, manejar el kill switch, configurar el inicio automático e instalar actualizaciones. Al minimizarlo queda como indicador en el área de notificaciones. El actualizador continúa disponible por consola como mecanismo alternativo de recuperación.
