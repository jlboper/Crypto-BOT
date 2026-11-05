# Project Handover — Crypto AI Trader

## Estado actual y alcance de la candidata 59

Base verificada: main `b79c7dfa2de810a8181b730706a67f2282bd60fe`, PR135,
0.10.58 firmada e instalada. Auditoría local5 noviembre 2026:332/332 archivos,
agente 15/15, dos HTTPS nuevos, un solo motor Testnet, fuentes y datos preservados.
El workflow de publicación41899913559 aprobó Linux/Windows y publicó; el workflow
separado de seguridad41899913720 falló una prueba Windows de heartbeat. Se conserva
ese fallo; la candidata 59 corrige la carrera y exige validación propia.

59 corrige la publicación en memoria del heartbeat antes de su commit SQLite.
La documentación vigente se concentra en un estado actual y una auditoría de
arranque; las notas históricas se archivan sin borrarlas. No activa LIVE ni
cambia estrategias, límites, claves o permisos. Su CI/firma/instalación son pendientes.

## Arranque con dinero real

LIVE no está comisionado. Hay tres faltantes de implementación: ensamblador del
runtime conectado al engine, proveedor operativo de AdmissionFacts certificados,
y flujo protegido de puesta en servicio/activación. Los módulos de ejecución y
recuperación tienen pruebas sintéticas; eso no equivale a integración operativa.
Más permisos o más días transcurridos no conectan esas piezas.

La conciliación integral, el historial de protección, la evidencia forward/OOS y
la revisión explícita del capital/riesgo son requisitos distintos. Los30 días son
una política interna del proyecto, no una espera que genere aprobación automática.
No retirar guardas ni fabricar hechos financieros para convertir el estado enGO.
Ver [auditoría de arranque](LIVE_LAUNCH_AUDIT.md) y [cierre acotado](PREPRODUCTION_CLOSURE.md).

## Reglas de operación y desarrollo

- Conservar claves, configuración, historial y cohortes; nunca reiniciar evidencia
  por una actualización técnica o una limpieza de archivos.
- Un solo motor supervisado. Spot Testnet y Futures Demo tienen cuentas/ledgers
  separados; Pulse/Quant permanecen SHADOW y Guardian observador.
- Código operativo por PR→CI→main→publicación firmada→supervisor. Verificar
  commit, firma, hashes instalados, proceso y dos sincronizacionesHTTPS nuevas.
- Autorización permanente del propietario para actualizaciones técnicas. LIVE,
  capital/riesgo y promoción de estrategias requieren revisión explícita separada.
- No publicar credenciales, DBs, logs, estados o respaldos. No ampliar permisos
  Binance a retiros/transferencias por preparar la operativa Spot/Futures.
- Mantener MODULES/SUPERVISOR_MODULES iguales y la prueba de import aislado antes
  de cambiar dependencias del agente. El nombre audit-work-v0.6.2 sigue activo.
- Validar cambios con `python scripts/test_offline.py`; UI/Worker además con
  `node --test tests/*.test.mjs` desde cloudflare. No tocar datos operativos al desarrollar.

## Ubicaciones

La instalación supervisada no tieneGit. Su WORK_CONTEXT local contiene pruebas
privadas y autorización persistente. El checkout de desarrollo y el agente
independiente son directorios distintos: no sustituir uno por otro. Los antiguos
espacios de trabajo archivados no son fuentes de código operativo. Consultar el
WORK_CONTEXT de la instalación para sus rutas exactas y evidencia privada.

## Registro histórico

Las notas anteriores se conservaron sin alterar en
[docs/archive/before-0.10.59](docs/archive/before-0.10.59/INDEX.md), con manifiestoSHA-256.
Esas notas describen cortes pasados; no sustituyen la evidencia de instalación.
