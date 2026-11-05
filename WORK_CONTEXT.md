# Contexto de desarrollo — Crypto AI Trader

Base verificada: main `b79c7dfa2de810a8181b730706a67f2282bd60fe`, PR135,
0.10.58 firmada e instalada. Auditoría local5 noviembre 2026:332/332 archivos,
agente 15/15, dos HTTPS nuevos, un solo motor Testnet, fuentes y datos preservados.
El workflow de publicación41899913559 aprobó Linux/Windows y publicó; el workflow
separado de seguridad41899913720 falló una prueba Windows de heartbeat. Se conserva
ese fallo; la candidata 59 corrige la carrera y exige validación propia.

## Trabajo actual: auditoría y correctiva 59

El propietario pidió una auditoría completa, limpiar lo obsoleto y concentrar el
camino hacia Spot/Futures reales. La autorización permanente de actualizaciones
técnicas no asigna capital ni convierte pruebas sintéticas en commissioning LIVE.
Se comprobó el bloqueo estructural descrito en LIVE_LAUNCH_AUDIT.md.59 repara la
carrera de heartbeat y consolida documentación; no elimina guardas financieras.

La instalación supervisada contiene los informes privados, credenciales, ledgers,
manifiestos de limpieza y pruebas de preservación. No copiarlos a este repositorio.
Antes de ejecutar cambios, leer su WORK_CONTEXT local y verificar estado real.

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

## Registro histórico

Las notas anteriores se conservaron sin alterar en
[docs/archive/before-0.10.59](docs/archive/before-0.10.59/INDEX.md), con manifiestoSHA-256.
Esas notas describen cortes pasados; no sustituyen la evidencia de instalación.
