# Crypto AI Trading Bot — Binance Spot

> Copia de desarrollo aislada de la instalación Windows. El repositorio no contiene credenciales ni datos de la instancia operativa. No inicies un segundo motor. Consulta `BOT_UPDATE_PROGRESS.md` para distinguir versión preparada, publicada e instalada.

Bot de capital para swing trading de varios días/semanas, **sin apalancamiento** y **solo en simulación**. Consume precios reales de Binance Spot, crea señales cuantitativas y utiliza OpenAI como una segunda barrera de riesgo. La versión 0.6 incorpora un laboratorio independiente para comparar activos y estrategias sin modificar el motor operativo.

La IA no puede inventar compras, aumentar el tamaño de una posición, eliminar stops ni cambiar límites. Únicamente puede `ALLOW`, `REJECT` o `REDUCE` una entrada que ya pasó las reglas cuantitativas.

## Límites iniciales

- Capital simulado: 1,000 USDT.
- Máximo 5 posiciones.
- Máximo 15% por posición y 60% de exposición total.
- Riesgo objetivo: 0.75% del portafolio por operación.
- Detención diaria: −2%; semanal: −5%.
- Stops por ATR, objetivo 2R y trailing stop después de alcanzar 1R.
- Sin futuros, margen, cortos ni promedio de pérdidas.
- Kill switch manual y automático después de tres errores consecutivos. Bloquea entradas nuevas, pero el motor continúa vigilando stops y salidas de posiciones existentes.

Todos estos valores están en `config.toml`.

## Requisitos

- Windows 10/11 o Linux.
- Python 3.11 o superior.
- Conexión estable a internet.
- El motor usa la biblioteca estándar. El portal requiere Waitress 3.0.2; las firmas requieren cryptography 50.0.1. Son dependencias opcionales declaradas en pyproject.toml.

## Inicio rápido en Windows

1. Descomprime el proyecto.
2. Abre PowerShell dentro de la carpeta.
3. Coloca `OPENAI_API_KEY` en `.env.local`. No compartas ese archivo ni lo subas a Git.
4. Ejecuta:

```powershell
.\scripts\start_windows.ps1
```

5. Abre `http://127.0.0.1:8765`.

La clave creada durante esta sesión está guardada de forma segura en el entorno actual; no se incluye dentro del ZIP. Para instalar el bot en otra PC, configura allí la credencial mediante un canal seguro.

## Inicio rápido en Linux

```bash
chmod +x scripts/start_linux.sh
./scripts/start_linux.sh
```

## Comandos útiles

```bash
# Ejecutar un solo ciclo
python -m trader once

# Motor continuo + dashboard
python -m trader run

# Solo dashboard
python -m trader dashboard

# Estado local
python -m trader status

# Backtest conservador con hasta 10,000 velas cerradas de Binance
python -m trader backtest BTCUSDT --limit 2000

# Research Lab: BTC, ETH, SOL, BNB y XRP
python -m trader research

# Emergencia / reanudación
python -m trader kill
python -m trader resume

# Verificar credenciales Binance Spot Testnet sin operar
python -m trader check-testnet

# Preparar una orden hipotética con filtros públicos de Testnet (sin enviarla)
python -m trader testnet-plan BTCUSDT --side BUY --quote-amount 25

# Simular conciliación NEW → PARTIALLY_FILLED → FILLED sin red ni credenciales
python -m trader testnet-simulate
```

## Binance Testnet (preparado, no activado)

`BINANCE_API_KEY` y `BINANCE_API_SECRET` pueden añadirse a `.env.local`. El comando `check-testnet` consulta la cuenta de Testnet y no envía órdenes. `testnet-plan` consulta únicamente filtros y precio públicos para redondear una orden hipotética; `testnet-simulate` prueba la conciliación con datos sintéticos. No existe transporte de escritura y la activación de órdenes se hará solo después de validar backtests, varias semanas de paper trading, pruebas de conciliación y una autorización separada.

Las claves de Binance deben pertenecer a una subcuenta separada, permitir únicamente lectura/trading, tener retiros desactivados y estar restringidas a la IP fija del servidor.

## Qué hace cada ciclo

1. Selecciona los pares USDT con mayor volumen y excluye stablecoins y tokens apalancados.
2. Descarga únicamente velas cerradas de 4 horas.
3. Calcula EMA 20/50, RSI 14, ATR 14, volumen, momentum y breakout de 20 velas.
4. Penaliza nuevas entradas cuando el régimen de BTC es bajista.
5. Revisa stops, objetivos y trailing stops de posiciones existentes.
6. Envía como máximo tres candidatos a la IA.
7. Dimensiona cada entrada según la distancia al stop y los límites globales.
8. Registra señales, revisiones, operaciones y equity en SQLite.

## Monitorización remota

La versión 0.2 añade:

- Semáforo del motor basado en la hora real del último ciclo exitoso.
- Estados `OPERATIVO`, `RETRASADO` y `SIN ACTIVIDAD`.
- Precio spot, valor de mercado y P&L no realizado estimado de cada posición.
- Vigilancia de posiciones abiertas aunque salgan temporalmente del top de volumen.
- Stops y objetivos evaluados contra el precio spot más reciente disponible, mientras las señales técnicas continúan usando velas cerradas.
- Panel de errores y advertencias recientes.
- `/health` devuelve HTTP 200 cuando el ciclo está al día y HTTP 503 cuando falta actividad.

El dashboard continúa escuchando en localhost. El portal remoto está publicado en Cloudflare y recibe conexiones salientes de `trader.remote_agent`; no necesita VPN ni puertos entrantes en Windows. Consulta `DEPLOYMENT.md`.

## Research Lab v0.6

El portal incluye un laboratorio multi-cripto para `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` y `XRPUSDT`. Por cada activo compara cinco familias: tendencia base, momentum rápido, tendencia conservadora, pullback en tendencia y reversión a la media.

Cada ejecución descarga hasta 5,000 velas cerradas por activo y aplica:

- Señal al cierre y ejecución en la apertura de la vela siguiente, evitando anticipación de datos.
- Comisión y slippage en entradas y salidas.
- Stops y objetivos intravela; cuando el orden es ambiguo, supone primero el stop.
- Walk-forward rodante con selección en entrenamiento y evaluación fuera de muestra.
- Ranking ajustado por Sharpe, Calmar, drawdown, exceso frente a buy-and-hold, rotación y número de operaciones.
- Heurística de sobreajuste basada en el rango fuera de muestra de la estrategia seleccionada.
- 1,000 simulaciones Monte Carlo de las operaciones fuera de muestra.
- Auditoría de duplicados y huecos en las velas.
- Separación de resultados en regímenes alcistas, laterales y bajistas.
- Comparación de asignación por ventanas alineadas y matriz de correlaciones; no es un backtest conjunto de ejecución del portafolio.
- Sensibilidad del candidato ante cambios pequeños del umbral de entrada.
- Separación explícita entre estrategia fija y selector adaptativo.
- Benchmark de efectivo USDT al 0%: superar un mercado bajista no basta si la estrategia pierde dinero.
- Cash gate: el selector adaptativo no opera cuando el periodo de entrenamiento no demuestra retorno, Sharpe y actividad mínimos.
- Catorce puertas de evidencia en 0.6.10, incluyendo ventaja frente a comprar y mantener cada activo en desarrollo y ventana final, costos duplicados y mínimos de actividad.

El cálculo se ejecuta en un proceso independiente para no bloquear el motor ni el portal. Pulsa una fila del informe para ver el diagnóstico del activo o utiliza `Exportar CSV` para conservar el resumen.

Los resultados son `RESEARCH_ONLY`: ni el ganador ni sus parámetros se transfieren al motor automáticamente. La columna `OOS fija` pertenece siempre al candidato mostrado; `Selector adaptativo` representa una política distinta que puede cambiar de estrategia entre ventanas o conservar USDT. Un candidato debe superar las catorce puertas y validaciones adicionales antes de entrar siquiera a paper trading. Consulta `RESEARCH_METHODOLOGY.md` para límites y criterios.

El portal local y el remoto distribuyen la misma interfaz. El remoto exige autenticación, no almacena datos privados en caché y puede solicitar Research al agente Windows sin modificar decisiones del motor.

## Actualizaciones asistidas

La app de Windows dispone de un centro de actualización **local**: puede buscar y verificar el paquete firmado por Internet, o instalar uno ya descargado incluso si el portal web no está disponible. Solicita aprobación de la identificación exacta y usa el supervisor independiente para detener el motor PAPER de manera cooperativa, conservar respaldo y comprobar el arranque. El portal local mantiene la ruta web existente para quien prefiera ese flujo; ninguno instala ZIP sin firma. Para publicar una versión nueva, Work prepara un PR, GitHub prueba el commit y el propietario autoriza el entorno protegido desde el enlace mostrado. Cloudflare recibe credenciales únicamente después de la aprobación; CI rechaza migraciones pendientes y hace rollback si la salud falla. Consulta `GITHUB_RELEASES.md`.

El instalador gráfico antiguo basado únicamente en SHA-256 fue retirado. `trader.update_manager` verifica paquetes Ed25519, evita downgrade, conserva respaldo y recupera cambios incompletos. El supervisor de Windows instala versiones firmadas tras aprobación exacta y ofrece una restauración voluntaria del código anterior desde **Opciones → Restaurar versión anterior** cuando conserva una copia comprobable. La operación deja intactos saldos, operaciones y la secuencia antirretroceso; solo aparece después de una instalación firmada realizada por el supervisor actualizado. `ACTUALIZAR_BOT.cmd` queda como herramienta técnica local.

## Seguimiento financiero PAPER

El panel resume operaciones cerradas, P&L realizado neto de comisiones, costos simulados y drawdown observado en la curva de equity. El agente Windows actual puede enviar solo una muestra reciente; el panel la marca como parcial hasta recibir el historial completo. Un mes de observación y 30 cierres son un filtro mínimo para revisar resultados, nunca una aprobación automática para operar con dinero real. El registro actual no modela aportes/retiros ni contiene un benchmark histórico sincronizado, de modo que el informe no demuestra ventaja sobre comprar y mantener BTC. La ruta posterior es un forward test reproducible, luego Testnet con filtros del exchange y conciliación de órdenes, y solo después una decisión separada sobre dinero real.

En 0.6.8 el informe desglosa resultados realizados por activo, porcentaje de cierres ganadores, exposición y P&L abierto estimado con comisiones y slippage PAPER. Las estimaciones abiertas solo aparecen con precios de mercado recientes; una cotización ausente o vencida muestra «—» y bloquea decisiones de cierre basadas en velas antiguas. Las cifras por activo son diagnósticas, no recomendaciones para activar una estrategia ni permisos LIVE.

En 0.6.9 el panel agrupa la evaluación histórica de estrategias dentro del seguimiento financiero; el motor PAPER sigue siendo uno solo y ninguna estrategia se activa automáticamente. Cada nuevo ciclo guarda juntos equity y BTCUSDT para comparar la variación en un período idéntico. No reconstruye BTC previo ni corrige aportes/retiros, y la referencia BTC spot no incluye comisiones. La lista de actividad muestra tres movimientos; el historial autenticado se consulta desde Opciones por páginas de 25 y se conserva hasta 90 días. El panel enumera umbrales PAPER y tareas manuales pendientes de Testnet y conciliación antes de considerar capital real; esta versión solo opera en PAPER.

En 0.6.10 el informe muestra también BTC con comisión y slippage PAPER en ambos extremos de la misma ventana; el laboratorio exige superar la compra y tenencia del activo evaluado fuera de muestra y en la ventana final para marcar un candidato como prometedor. La evaluación detallada queda plegada para limpiar el panel. Los límites PAPER se leen de la configuración efectiva. Los diagnósticos de más de 90 días se depuran diariamente incluso si el motor está pausado; operaciones, posiciones, equity y referencia BTC se conservan. Consulta `STRATEGY_EVIDENCE.md`. Estas mejoras no activan dinero real.

En 0.6.11 el desglose muestra hasta 50 activos cerrados y concilia el resto en «Otros»; agrupa P&L neto por motivo de salida y muestra cuántas operaciones PAPER pertenecen realmente a los cinco activos del estudio. La proyección HTTPS admite este historial acotado. Antes de cada nueva compra PAPER, un diagnóstico usa las reglas públicas ya descargadas de Binance Spot para estimar si la cantidad y el valor mínimo de una hipotética orden MARKET serían compatibles. La operación simulada sigue igual: el resultado solo sirve para investigar incompatibilidades; no se envía ninguna orden. El precio spot no sustituye al precio medio que Binance puede usar para el filtro de notional, ni valida balances o ejecución Testnet. Los diagnósticos nuevos se conservan hasta 90 días; no se alteran las operaciones ni el historial financiero previo.

En 0.6.12 el portal deja visibles las puertas unificadas de promoción: ventaja frente a efectivo y mantener el activo, consistencia OOS, costos duplicados en la ventana reservada, actividad mínima y un forward test futuro. Aunque un activo supere las puertas, permanece en `RESEARCH_ONLY` y no modifica el motor PAPER. Testnet añade un planificador de cantidad y notional basado en filtros públicos y una máquina de estados sintética para probar conciliación sin enviar órdenes. La revisión de IA sigue en GPT-5.6 Luna porque es el identificador disponible en la API; `OPENAI_MODEL` permite seleccionar un modelo API confirmado en una instalación autorizada. `gpt-6-luna` no se configura sin un identificador oficial.

## Centro de control de Windows

Haz doble clic en `Crypto AI Trader.vbs` para abrir una aplicación gráfica sin consola. Desde allí puedes comprobar el estado, equity, rendimiento, efectivo, exposición, posiciones y último ciclo; abrir el portal local o el remoto; buscar e instalar actualizaciones firmadas directamente desde la PC; reiniciar el motor; manejar el kill switch y configurar el inicio automático. Si Internet falla, el botón puede comprobar un paquete firmado previamente descargado; no puede descubrir versiones que no estén ya en la PC. El supervisor independiente debe estar configurado y la versión debe estar firmada, vigente y ser más reciente. Al minimizar o cerrar, el indicador continúa en el área de notificaciones de Windows y cambia de color según el estado.

## Seguridad operacional

- El dashboard escucha solo en `127.0.0.1`; no abras el puerto 8765 en el router.
- Si cambias el host para acceder remotamente, define `DASHBOARD_TOKEN` y usa una VPN privada.
- Conserva `mode = "paper"`. Esta versión rechaza cualquier otro modo deliberadamente.
- Una simulación favorable no garantiza resultados reales: existen slippage, gaps, cambios de régimen, fallas de conectividad y riesgo de contraparte del exchange.

## Pruebas locales

```bash
python -m unittest discover -s tests -v
```

La siguiente fase debe comenzar solo tras revisar resultados fuera de muestra, costos, drawdown, estabilidad por activo y comportamiento durante varias semanas en simulación.
