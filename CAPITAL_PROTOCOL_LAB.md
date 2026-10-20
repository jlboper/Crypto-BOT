# Capital Protocol Lab — laboratorio sintético

Entrega 0.10.44 en preparación. Es una base comprobable para Capital Manager,
todavía sin adaptador de cuentas ni propuestas previas a las órdenes de los bots.
No completa la Fase 3 operativa. Guardian conserva LEVEL 0 y reservas
`NOT_INTEGRATED`; Spot, Futures, Pulse y Quant mantienen sus decisiones actuales.

## Ejecución explícita y lectura

```powershell
python scripts/run_capital_protocol_lab.py
python scripts/run_capital_protocol_lab.py --read-only
```

El primer comando ejecuta siete recetas cerradas con financiación de ejemplo,
crea cohortes `SIM_` nuevas y guarda sus propias bases `.simulation.sqlite3` bajo
`data/research/capital-lab`. Cada ejecución tiene un UUID distinto: no reinicia
wallets anteriores. No importa motores, clientes de exchange, IA ni credenciales.
Los presupuestos de las recetas son ejemplos sintéticos, no límites aprobados
para trading. No hay proceso continuo, servidor ni tarea de Windows adicionales.

El segundo comando, el portal y la sincronización leen únicamente el último
informe JSON terminado. No abren las bases del laboratorio ni ejecutan recetas.
La ausencia de informe produce `NOT_RUN`; un informe inválido produce
`UNAVAILABLE`. Sus timestamps no certifican actividad de ningún motor.

## Qué comprueba

1. Reserva atómica de dos patas dentro de una transacción SQLite.
2. Conflicto de activo entre estrategias que comparten una cuenta simulada.
3. Competencia concurrente por un presupuesto que no puede utilizarse dos veces.
4. Reinicio, orden incierta y TTL sin liberar capital pendiente de conciliación.
5. Cancelación parcial que conserva principal abierto y costes de salida.
6. Fallo de una pata y cierre simulado explícito del riesgo residual.
7. Comisiones y pérdidas confirmadas que muestran un déficit con signo.

El protocolo usa enteros en micro-USDT, transacciones `BEGIN IMMEDIATE`, claves
idempotentes y reservas por cuenta, estrategia y activo. Conserva terminales por
pata incluso ante mensajes UNKNOWN posteriores. Un balance anterior a una
mutación financiera no certifica el estado nuevo. Una divergencia exige
`RECOVERY_REQUIRED`, sin revivir capital liberado ni permitir nuevas reservas.
La confirmación de un cierre válido permanece disponible durante recuperación.

El libro distingue capital reservado, comprometido, libre, déficit, comisiones
y P&L realizado sintético. No oculta pérdidas poniendo a cero el capital negativo.
Capital comprometido mide principal contable; no equivale a exposición de mercado,
nocional, margen ni riesgo hasta stops.

## Portal y límites de interpretación

Research Lab presenta un bloque plegable **Capital Lab · escenario sintético**.
La procedencia y auditoría quedan en otro plegable cerrado al inicio. Cada caso
muestra título, LAB SIM y resultado; su ámbito, estados y libro se consultan en
el detalle independiente. La fecha y los avisos esenciales permanecen visibles.
Los siete casos conservan cuenta, política, fecha, checks y referencias de
auditoría. El formato monetario mantiene seis decimales mediante aritmética
entera. No suma cohortes entre sí ni incorpora sus importes a Portfolio & Capital,
las cuatro tarjetas de motores, Guardian o resultados de estrategias.

`PASSED` significa que esas recetas cumplieron sus invariantes. Un caso puede
pasar precisamente porque conservó `RECOVERY_REQUIRED` y un déficit. No demuestra
rentabilidad, reconciliación Binance, cobertura eficaz, promoción ni autorización
financiera. Los hashes identifican evidencia; no constituyen firma de release ni
servicio completo de reproducción del journal.

El DTO opcional `capital_lab` está acotado a 8.000 bytes y tiene esquema cerrado
en el lector Python y el Worker. Se conserva la compatibilidad de portal previo:
un rechazo del campo opcional no debe ocultar motores, Guardian, autenticación o
actualizaciones. Windows abre el mismo Research Lab mediante sus enlaces actuales.
No hay botones de ejecutar, liberar, aprobar, asignar fondos o promover.

## Persistencia y trabajo pendiente

Los informes y SQLite del laboratorio son evidencia local sintética y quedan
fuera del repositorio y de los paquetes firmados. No se borran automáticamente.
El patrón `.simulation.sqlite3` no amplía los backups del updater: antes de una
futura integración continua se necesita una política explícita para preservar y
recuperar esas cohortes. Este laboratorio no modifica el actual updater ni sus
backups financieros.

Faltan el contrato común de oportunidad inmutable, identidad de cuenta verificada,
adaptadores previos a envío, conciliación del exchange y observación prospectiva
del Capital Manager sobre propuestas auténticas. También faltan riesgo global de
mercado, correlaciones, margen, pérdidas diarias/semanales, funding/rebates y
salidas parciales. Los casos no sustituyen esos componentes.

Conectar dos motores al mismo capital Testnet requiere protocolo común validado
de reserva, ejecución y conciliación, pruebas separadas y autorización del dueño
para activar Guardian Control. LIVE, retiros y promociones automáticas permanecen
fuera de esta entrega. Los cierres protectores siguen independientes de Guardian.

## Estado de validación

Los prototipos exteriores aprobaron 61 pruebas y seis probes independientes;
core/Lab/CLI integrados aprobaron 64 pruebas enfocadas. Antes de la compactación UI:
**850/850 Python offline** (181.531 s en `TEST_RESULTS.json`, 2026-10-19 13:19:52.904728
UTC; sin fallos, errores ni skips, red externa bloqueada y sin iniciar el bot),
**202/202 Node** (69.325 s), 84 pruebas UI enfocadas (13.643 s), lifecycle/vistas
Windows PowerShell 5.1, build y diff PASS, con las validaciones UI de política y
coherencia contable reforzadas.

El [PR #121](https://github.com/jlboper/Crypto-BOT/pull/121) está en draft, head
`5138e51a1f37001629ac1420e3b0d7e48a439170`; CI 39259777367/39259777360 PASS
corresponden a ese head. La compactación posterior conserva 47 plegables y
aprobó 84 pruebas UI de foco (7.046 s) y diff. QA visual PASS en preview sintético
local, sin trading/red, a 360/768/1366px: client/scroll 345/345, 753/753 y 1351/1351.
Los siete casos aparecen sin overflow; auditoría cerrada 42.53px frente a 815.9px,
primer caso aproximadamente a 534px frente a 1215px. Apertura individual,
cierre por Enter, auditoría y pérdida/deficit −204.000000/204.000000 verificados.
Evidencia: `capital-lab44-visual-qa.json` y capturas mobile/tablet/desktop en artifacts.
Validación final tras compactar, **2026-10-19 17:56:01.749748 UTC**:
**850/850 Python offline** (171.844 s en TEST_RESULTS; runner 171.835 s),
**202/202 Node** (37.430 s), build y diff PASS. Sin fallos, errores ni skips;
Python 3.12.14, fixtures sintéticas, red bloqueada y bot no iniciado.
Nuevo head/CI final y merge siguen pendientes. No se afirma
publicación/firma/instalación44 ni ejecución del CLI firmado instalado. La QA
del preview no es evidencia de instalación; la CI anterior no valida el nuevo
head pendiente. Esos checkpoints se registran por separado en
`BOT_UPDATE_PROGRESS.md`; las pruebas del laboratorio no completan Fase 3 runtime.

La auditoría RO de las 13:18:23 UTC verificó todas las filas del backup Spot 43:
trades 80/80 y receipts 48/48, sin ausencias/cambios y con SHA del backup intacto
(`append-only-backup43-verification.json`). El updater 43 sólo respaldó Spot;
Futures/Pulse/Quant tienen comparaciones de prefijos muestreados, sin backup 43
multiledger ni prueba exhaustiva de todas las filas previas. Esta limitación no
se elimina por ejecutar las recetas sintéticas del Lab.


## Verificación posterior44 y transición45 (20Oct2026)

44 fue publicada, firmada e instalada: main f79578360f7870321d29cb842966bac2a250dba5,
PR121, publicación39407655253 SUCCESS Linux/Windows,195/195 hashes. El CLI firmado
se ejecutó exactamente una vez: siete casos PASSED/siete SQLite nuevas; lecturas
posteriores sin cambios. Exportación real414020bytes/Lab7489bytes y dos HTTPS
aceptados. Esta evidencia posterior prevalece sobre los estados de preparación
anteriores. No completa capital operativo.45 agrega observación independiente de
intenciones; no reutiliza wallets SIM ni cambia los resultados del Lab44.
