# Actualización 0.6.16 — controles PAPER compartidos

- El mismo panel local y remoto permite seleccionar mínimo, prudente o normal para nuevas entradas PAPER y solicitar el cierre de una posición PAPER concreta.
- El cierre exige posición idéntica, cotización nueva dentro del 2% de la vista y bloqueo de reentrada de 24 horas. No envía órdenes a Binance.
- Desde el portal remoto la solicitud permanece pendiente hasta que el supervisor de Windows confirme el resultado. El historial muestra completada, fallida o vencida.
- Después de instalar la versión firmada, el menú del indicador de Windows permite actualizar una vez los módulos verificados del supervisor independiente. El portal remoto habilita los controles cuando detecta la nueva capacidad.
- El despliegue protegido aplica una migración aditiva de D1 antes de publicar el portal y comprueba su historial.

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
