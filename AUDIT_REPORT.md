# Auditoría de la copia v0.6.2 — 14 septiembre 2026

## Alcance y recuperación

Se trabajó en `audit-work-v0.6.2`, dentro de la carpeta del proyecto, sin iniciar `trader run`, `once`, Research Lab con datos reales ni el agente remoto. No se instalaron cambios en la instancia operativa. No se hicieron consultas a OpenAI ni órdenes reales. Las pruebas usan señales y precios sintéticos, bases temporales y transporte simulado; el ejecutor offline bloquea conexiones externas.

No se encontró repositorio Git ni AGENTS.md en el árbol examinado. Se conservó `../baseline-v0.6.2.zip` antes de editar, con SHA-256 `D96FE6EDA0FC6CE7C0CF562D20F102A829A896A649A474D5766804018F089B18`. `BASELINE_SHA256.json` contiene las huellas por archivo. El respaldo contiene código/configuración original, sin `.env.local`, `data` ni respaldos anteriores. Es recuperación de código, no copia del estado financiero SQLite en funcionamiento. Los archivos operativos permanecen en su ubicación original.

## Uso exacto de IA encontrado

- Modelo configurado: `gpt-5.6-luna`. Se detectó también ese valor como override `OPENAI_MODEL`; la configuración da prioridad a la variable de entorno. No se verificó acceso al modelo en la cuenta mediante una llamada real.
- Endpoint: `POST https://api.openai.com/v1/responses`, autorización por variable `OPENAI_API_KEY`, salida JSON Schema estricta, razonamiento `low`, timeout de 30 segundos.
- Entrada: objeto completo Signal (activo, BUY/HOLD, puntuación, precio, stop, objetivo, ATR, RSI, EMAs, volumen, motivo y fecha), régimen alcista de BTC y contexto con equity, efectivo, exposición y número de posiciones. No recibe claves Binance, no consulta noticias ni herramientas, no entrena modelos.
- Consulta original: ciclo cada 900 segundos, señales sobre velas cerradas de 4 h. Candidatos BUY ordenados por puntuación, después de límites de posiciones/exposición y de las pausas por riesgo; máximo tres revisiones por ciclo. No era una llamada por activo en todo ciclo: solo por candidato seleccionado. Podía repetir la misma vela. Límite teórico original: 288 revisiones por día.
- Efecto: REJECT o multiplicador cero descarta la entrada; confianza inferior a 0.60 descarta. REDUCE limita el multiplicador a 0.75. ALLOW conserva como máximo 1. La cantidad final sigue limitada por riesgo, posición, exposición y efectivo. Ni stops/salidas ni Research Lab utilizan la API de IA.
- Ausencia de clave o fallo: con `fail_closed=true`, rechaza. El código conserva la opción explícita `fail_closed=false`, que permite seguir la señal cuantitativa; no se activó.
- Cambios: validación local de tipos/rangos/NaN/infinito, veredictos desconocidos y respuestas incompletas; ALLOW con cero ya no se convierte en tamaño completo. `store=false`, máximo 800 tokens de salida, presupuesto persistente de 30 revisiones/día UTC y un intento por símbolo/vela. Los intentos se reservan antes de llamar; un fallo puede consumir un intento, de forma conservadora. No hay reintentos de pago automáticos.

La API admite salidas estructuradas, pero la validación local y el tratamiento de respuestas incompletas siguen siendo necesarios: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). No se cambió el modelo ni se presupuso que un nombre visible en Codex garantice disponibilidad en API.

## Motor, persistencia y ejecución

| Hallazgo | Corrección en la copia | Límite restante |
|---|---|---|
| Compra/venta actualizaba efectivo, posición e historial por separado | Transacción SQLite BEGIN IMMEDIATE, rollback y conexiones locales por hilo | SQLite requiere disco local sano; no replica datos |
| Repetir una venta podía abonar dos veces | Se comprueba posición actual dentro de la transacción | No implementa reconciliación con un exchange real |
| `once` evitaba el bloqueo usado por `run` | Ambos comandos toman engine.lock | Uso directo de clases es interno y no sustituye los puntos de entrada CLI |
| Error en universo/BTC podía impedir stops | Protección previa del inventario y protección sin velas | Sin precio de mercado no se puede simular una salida fiable |
| Stops se comprobaban normalmente cada 15 min | Tick de protección objetivo de 30 s entre ciclos, incluso pausado | Las llamadas del ciclo son síncronas: 30 s no es un SLA; gaps y desconexiones siguen siendo posibles |
| Entrada simulada al cierre antiguo | Se usa spot validado dentro de los niveles de protección | No representa libro de órdenes ni latencia real de ejecución |
| Riesgo dimensionado sin todos los costos | Pérdida hasta stop incluye entrada/salida, comisiones y deslizamiento | Un gap puede exceder la pérdida objetivo |
| Umbral diario/semanal podía desbloquearse al recuperar equity | Base previa al inicio del periodo y bloqueo persistente por periodo UTC | No incluye aportaciones/retiros ni contabilidad fiscal |
| Errores consecutivos se olvidaban al reiniciar | Contador persistente y kill switch existente | Hay que tratar disco lleno y fallos del SO operativamente |
| Descargas repetidas de velas/metadata | Caché hasta próxima vela, metadata 1 h, validación de frescura/huecos | La caché es de proceso, no sobrevive reinicios |
| Sin reintentos de lectura acotados | Solo GET, hasta tres intentos, backoff/jitter, Retry-After limitado | Un Retry-After largo provoca fallo seguro y espera al próximo ciclo |
| Ruta genérica permitía construir POST/DELETE a Binance | Transporte rechaza métodos distintos de GET | La verificación Testnet sigue siendo únicamente lectura |
| Acumulación de diagnósticos | Retención 90 días de señales/eventos/revisiones; conserva trades/equity | Trades y equity siguen creciendo; archivado financiero está pendiente |
| Dashboard local aceptaba Host arbitrario y token URL | Restricción Host para localhost y token por encabezado, comparación constante | El dashboard local no es el servidor público |
| Scripts Windows seleccionaban procesos globalmente | Gestor identifica configuración de la instalación; instalador no detiene procesos | Revisar migración de arranque con el bot detenido antes de usarlo |

Se preservaron las comisiones de 0.1% y deslizamiento de 0.05% por lado. Backtest y PAPER continúan sin apalancamiento y sin ejecución real. El trailing del backtest se alineó con la activación después de 1R; se conserva el conflicto intravela resuelto primero por stop.

## Research Lab

Ya existían cinco familias y BTC/ETH/SOL/BNB/XRP, walk-forward, costos, benchmark y Monte Carlo. Las mejoras no presentan esas capacidades como nuevas.

El candidato fijo ahora se selecciona exclusivamente con el entrenamiento inicial. La selección anterior maximizaba resultados de las propias ventanas OOS y contaminaba su interpretación. Se reserva al final una ventana adicional de `test_bars`, fuera de selección y sensibilidad, evaluando el candidato con costos base y duplicados. El selector adaptativo sigue eligiendo solo sobre el entrenamiento de cada ventana. Se exigen además tres ventanas, 20 operaciones OOS y tres operaciones en holdout para las puertas correspondientes.

Se rechazan velas inválidas, desordenadas, duplicadas o con huecos detectables. El bootstrap circular utiliza bloques de hasta cinco operaciones; normaliza cada P&L por el capital previo, no siempre por el inicial. Es un diagnóstico, no PBO formal, Sharpe deflactado ni una prueba estadística de rentabilidad. La selección de activos y la repetición de experimentos todavía pueden inducir sesgo. Volver a ajustar tras mirar el holdout consume su independencia; se necesitarán datos futuros.

Las ventanas de activos se agregan solo cuando coinciden las fechas de inicio y fin. La sección portfolio es una ilustración de asignación equiponderada por ventanas; NO simula ejecución conjunta, competencia simultánea por capital, liquidez ni riesgo cruzado. Su drawdown usa extremos de ventanas. Los indicadores usan historial acotado a 250 velas para evitar recalcular todo el pasado; esto cambia resultados respecto de v0.6.2 y requiere validación histórica nueva.

No se descargó mercado real para buscar un ganador ni se transfirieron parámetros al motor. `RESEARCH_ONLY` y `auto_promotion=false` permanecen. No se garantiza rentabilidad.

## Portal remoto y Android

Implementación: `remote_portal.py` (WSGI), `portal_web/` y `remote_agent.py`. El servidor recibe una copia mínima del estado; Windows solo realiza HTTPS saliente. El navegador accede al servidor, nunca al dashboard de la PC. Autenticación de propietario mediante scrypt y sesión de una hora; cookie Secure/HttpOnly/SameSite, CSRF, origen/Host esperados, límite global de intentos y cuerpos, headers de seguridad y no-store. El dispositivo utiliza un token independiente; el servidor almacena su hash. No recibe credenciales OpenAI/Binance.

Los controles disponibles son únicamente kill/resume: pausa de entradas, no liquidación de posiciones. Cola persistente, clave de idempotencia, vigencia de dos minutos, acuse y sustitución de solicitudes pendientes por el último estado deseado. Windows conserva el último ID aplicado y no vuelve a aplicar un resume ya procesado. Desconectarse del servidor no impide el funcionamiento local; sí impide controles remotos inmediatos.

La interfaz muestra equity, efectivo, exposición, posiciones y recepción/último ciclo. No incluye aún informes detallados de Research Lab remoto, MFA/WebAuthn, OAuth móvil, múltiples propietarios, histórico de equity remoto o notificaciones push. API versionada `/v1` y separación de credenciales preparan el siguiente paso Android: cliente autenticado, registro de token FCM y cola de notificaciones con deduplicación. **No existe aún app Android ni envío push.**

El portal no se ha publicado ni provisionado con credenciales reales. Se incluyen configuración Caddy, servicio systemd y utilidad explícita de provisión; no se ejecutaron. Las pruebas verifican el contrato WSGI, no certificados públicos ni UX en teléfonos físicos.

## Actualizaciones firmadas

`update_manager.py`: firma Ed25519 con biblioteca cryptography, manifiesto con hashes de archivos y ZIP, tamaño, expiración, aplicación, modo y secuencia. Rechaza downgrade de versión/repetición, rutas peligrosas, enlaces, nombres Windows reservados, sobrescritura de datos/config/credenciales, ZIP excesivo y archivos no declarados.

`stage` descarga exclusivamente HTTPS sin redirecciones y con origen coincidente; solo prepara el paquete. `apply` requiere libres los locks del motor, agente y Research Lab; guarda originales y diario antes de aplicar, valida sintaxis Python y recupera tras error. `recover` repara un diario incompleto. Se elimina también el código nuevo introducido por una instalación fallida. La clave pública se provisiona localmente fuera del paquete; la privada se mantiene offline y nunca se instala en Windows o el portal.

La validación de salud por callback se probó con fallo inyectado, y la recuperación de un diario interrumpido se probó en fixtures. La CLI no arranca el motor: no hay prueba de salud real automática postarranque, migración reversible de esquema ni garantías frente a toda falla física de disco. El instalador PowerShell antiguo fue sustituido y rechaza ZIP sin manifiesto firmado. El canal GitHub y botón de consulta existentes no publican/descargan aún ese manifiesto lateral; su instalación queda bloqueada hasta integrar el canal firmado. No se firmó una release de producción.

## Costos y publicación pendiente

Propuesta: VPS pequeño Linux, Caddy + Waitress + SQLite, un solo proceso servidor. Sin Kubernetes, Redis ni IA en servidor. Consultar `DEPLOYMENT.md` antes de contratar. Para VPS CX23 en Alemania/Finlandia la tarifa oficial publicada es 5.49 EUR/mes, excluye IPv4 e impuestos; dominio, respaldo externo y tráfico excedente pueden sumar costo: [Hetzner tarifas](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/). Es base de presupuesto, no contratación ni costo total confirmado.

Con 30 revisiones/día el techo configurado es 900 revisiones/30 días y 720,000 tokens de salida como máximo configurado; entrada y facturación dependen del uso/modelo. No se estimó un costo monetario de IA sin tarifa del modelo y acceso confirmados. El agente consulta cada 30 s más jitter (aproximadamente hasta 2,880 conexiones/día) y retrocede hasta cinco minutos en fallo. El navegador deja de sondear cuando la pestaña está oculta.

## Validación

Ver `TEST_RESULTS.md` y `scripts/test_offline.py`. Incluye pruebas heredadas y nuevas de rollback, concurrencia, costos, deduplicación persistente, presupuesto, protección, autenticación, CSRF, caducidad, firma/tampering y recuperación. PowerShell se valida con su parser, sin ejecutar el gestor. No se hicieron pruebas de Binance/OpenAI reales, despliegue HTTPS público, inicio de otra instancia, compra/venta real ni actualización sobre la instalación activa.
