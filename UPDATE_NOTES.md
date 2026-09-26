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
