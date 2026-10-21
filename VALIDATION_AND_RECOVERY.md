# Validación, trazabilidad y recuperación — candidata 0.10.47

## Estado y autoridad

Implementación en desarrollo desde main46 a851908a; pruebas, PR, CI, publicación,
firma e instalación son checkpoints separados. Guardian sigue LEVEL0. Spot Testnet
y Futures Demo conservan sus presupuestos, revisiones individuales y protecciones.
Pulse y Quant siguen SHADOW. Nada de esta entrega puede admitir, vetar o ejecutar
órdenes, reservar fondos reales, promover estrategias o habilitar LIVE.

## Trazabilidad de los cuatro motores

Las aperturas, parciales y cierres se observan después del commit financiero,
mediante cola acotada sin espera. Spot registra metadatos de recibo en el pending
ya existente dentro de su transacción; Futures utiliza su ledger central, Pulse
y Quant sus transacciones. Las conciliaciones GET se distinguen del POST inicial.
No se repite una orden para completar evidencia ni se consulta IA en las salidas.

La asociación exacta de entrada y posición vive sólo en tablas nuevas del observer.
Reutilizar BTC en una operación posterior no permite cerrar la reserva equivocada.
Un replay idéntico no revive un cierre; una divergencia queda latched. Metadatos
internos adicionales conservan las cuatro claves públicas históricas del resultado.
Un lector/escritor46 congelado verifica compatibilidad con el nuevo journal en
fixtures sintéticas; esto no es un rollback operativo ejecutado en Windows.

Límites: eventos perdidos, crash entre commit y hook, posiciones anteriores sin
asociación y rutas no instrumentadas permanecen UNKNOWN. PaperBroker y entradas
manuales no constituyen cobertura completa. CLOSED_OBSERVED prueba el ledger,
incluido el criterio nativo de dust de Spot; no certifica saldo o cierre Binance.
Un cierre parcial conserva la hipótesis retenida hasta un terminal conciliado.
No liberar incertidumbre por TTL ni usar estas cifras como fondos disponibles.

## Capital y preparación de riesgo

El laboratorio conserva el CapitalManagerShadow transaccional previo: cohortes
SIM nuevas, idempotencia, concurrencia, parciales, órdenes desconocidas, reinicio
y liberación por conciliación. No reutiliza cuentas o wallets de motores.

GlobalRiskShadow recibe políticas e inventario tipados y exclusivamente SIM.
Calcula exposición/riesgo antes y después, sin compensar LONG/SHORT o patas;
comprueba límites explícitos por motor, activo, grupo, apalancamiento, margen,
pérdidas, drawdown, frescura, liquidez y protección. Datos desconocidos rechazan
la admisión hipotética. Los cinco estados son diagnósticos de simulación, nunca
estados aplicados a los motores. Los costes y márgenes son hipótesis conservadoras,
no calibración de brackets Binance; no incluye latches durables de pérdida/reset.

```powershell
python scripts/run_control_validation.py --output-dir <carpeta-local-del-laboratorio>
python scripts/run_control_validation.py --read-report <reporte-SIM/report.json>
```

El primero crea cohortes nuevas y un artefacto con hashes; el segundo verifica
reporte/recetas sin crear wallets. PASSED significa invariantes de esas recetas,
no reconciliación Binance, rentabilidad, identidad de cuenta ni autorización.

Faltan para capital común: identidad de cuenta verificable, inventario inicial
completo de posiciones/órdenes estándar y algo, pending/fills/funding, timestamps
causales, semántica de balance TOTAL/FREE y reconciliación integral. Spot documenta
uid y Futures balance v3 accountAlias; disponibilidad y consistencia en Demo deben
comprobarse antes de usarlos. No inferir identidad de una clave o nombre de entorno.
No descontar reservas observadas de un saldo libre que ya las incluya.

La alerta Futures EXISTING_ENGINE_BUDGET_EXCEEDED coincide con el presupuesto
inclusivo nativo al corte auditado: 1.078459 del máximo, bruto0.724225 del máximo.
El nominal sin costes medía0.932420; las métricas difieren. Guardian no ejerce veto,
no se elevan topes ni se fuerzan cierres para ocultar la alerta.

## Investigación y consultas

Quant añade lectura RO de conteos y replay determinista de hasta16 decisiones:
cuatro primeras y cuatro últimas por estrategia disponibles en el corte. Se usan
evidencias congeladas, nunca noticias o precios actuales para rehacer el pasado.
Una divergencia o falta de evidencia queda visible. No es una muestra aleatoria,
validación fuera de muestra ni reconstrucción de fills. StatArb sigue bloqueado;
la correlación no acredita cointegración, estabilidad ni ejecución de dos patas.

Cada nuevo estudio archiva una matriz acotada de cuatro motores. Spot/Futures
históricos siguen modelos de mercado público y SIGNAL_PARITY_ONLY donde aplique;
Pulse/Quant son observación SHADOW. No se publican un ganador, cartera total,
pérdidas evitadas o resultado sin IA sin cohortes comparables. Monte Carlo, costes
y walk-forward existentes se conservan; el nuevo resumen sólo informa su presencia.

```powershell
python scripts/audit_research_validation.py --data-dir <datos> --research-report <informe-existente>
```

Esta lectura no genera retrospectivamente una matriz en un estudio antiguo ni
inicia proveedores. La matriz del portal aparece al existir un nuevo estudio
válido; una fecha de informe no acredita salud actual de motores.

Las13 consultas locales de Guardian leen reportes acotados, incluido exposición
por activo, última observación y restricciones hipotéticas. Citan fuente, corte
y registros; no almacenan preguntas ni invocan modelos, APIs, SQL o herramientas.
Sin historial completo no explican por qué no hubo compras todo el día. Una
respuesta de exchange FILLED no demuestra commit/protección. Los rechazos SIM no
son vetos reales ni ahorro atribuible. Historial de pestaña no es auditoría durable.

Guardian IA conserva modelo, schema, instrucciones, validador y cuotas. Los dos
intentos ordinarios21Oct recibieron respuestas completadas del API, pero fallaron
validación local; no hay comentario válido observado ni causa específica histórica.
La instrumentación nueva guarda sólo subcódigos/tipos/conteos de rechazos futuros,
nunca textos, IDs de evidencia, headers o credenciales. No repara, trunca, reintenta
ni resetea cuotas para conseguir una respuesta aceptada. CLI privado RO:

```powershell
python scripts/guardian_ai_diagnostics.py --data-dir <datos> --limit 8
```

Las filas antiguas conservan diagnóstico desconocido; no se reescriben. La próxima
evaluación ordinaria con cuota disponible proporcionará evidencia adicional.

## Portal y recuperación

El presupuesto remoto480000bytes se decide después de compactar detalle legacy;
Guardian se calcula antes con marcas completas. Protecciones y agregados conservan
prioridad. La reproducción RO sobre Windows preservó el DTO omitido por46 sin
ampliar el límite; no sustituye HTTP autenticado o UI remota de propietario.
La nueva matriz usa el mismo validador del navegador y Worker, fuente `web/` única,
un plegable adicional y recurso estático GET explícito con CSP/no-store.

```powershell
python scripts/backup_observation_evidence.py --source-data-dir <datos> --output-dir <carpeta-nueva-fuera-de-datos>
```

Herramienta explícita de copias locales SQLite RO de ocho ledgers/journals; no lee
credenciales ni modifica la fuente, restaura, reinicia o actúa desde GET del portal.
Destino nuevo exclusivo, allowlist, rechazo de enlaces, manifiesto INCOMPLETE
inicial, quick_check/hash individual y manifiesto final atómico. Un fallo conserva
evidencia parcial y nunca declara éxito. El deadline limita copia/comprobación,
no toda la E/S del sistema. Las copias son privadas: no subirlas a Git ni al portal.
No son una captura global atómica, backup de credenciales o protocolo de rollback.
Updater, firma Ed25519, anti-downgrade y recuperación supervisada no cambian.

## Pendientes de evidencia y autorización

Acumular cierres e intenciones auténticas sin forzar actividad, verificar la
respuesta IA ordinaria sin resetear cuotas, observar uso sostenido Windows y
probar hipótesis prospectivas. La muestra corta, entornos diferentes y simulaciones
no acreditan ventaja. Nivel1 y reservas efectivas requieren revisión concreta y
autorización separada; nivel2/3 y promociones también. LIVE permanece excluido.

## Validación local final — 21Oct2026

- Python offline: **1042/1042 PASS**,142.563s,02:14:50.718520UTC,
  sin fallos/errores/skips; claves vacías, red externa bloqueada, ningún bot iniciado.
- Node: **242/242 PASS**,39.280s, incluidos workerd/D1, autenticación/CSRF,
  contrato compartido y recurso GET nuevo. Windows PowerShell5.1 lifecycle/vistas,
  build compartido, paquete allowlisted227archivos y diff-check PASS.
- Ejecución explícita SIM:18/18riesgo+7/7capital PASSED; siete wallets nuevas.
  Lectura del artefacto conserva archivos y no recrea wallets. No certifica cuentas.
- Auditoría Quant RO auténtica02:15:19UTC:29280decisiones, cero cierres/funding
  pendiente,16/16replays coincidentes de muestra acotada; OOS/backtest válido false.
- Preview sintético360/768/1366px: cuatro tarjetas,13consultas,51plegables,
  sin overflow global; cierre/Enter/reapertura comprobados. POST403/red bloqueada.
  No es prueba de UI remota de propietario ni de instalación47.
- Primeras suites dentro del sandbox fallaron por loopback no permitido; Node
  además detectó la expectativa antigua50plegables frente a51. Se actualizó esa
  expectativa y ambas suites completas pasaron con loopback permitido, sin
  flexibilizar seguridad o el bloqueo de red externa del runner Python.

CI del head/main, firma, publicación, instalación y salud posterior47 pendientes.
No declarar completada Fase3 operativa ni activar Control por estas pruebas.
