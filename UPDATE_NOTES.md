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
