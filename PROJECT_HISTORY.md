# Project History and Decision Log

## 5 noviembre2026 — estado vigente separado del registro histórico

La documentación había acumulado estados de preparación de múltiples versiones
que podían confundirse con el estado actual. Se conserva cada documento anterior
exactamente en el archivo histórico, conSHA-256. README/HANDOVER/WORK_CONTEXT y
UPDATE_PROGRESS pasan a describir el estado actual. No se borran datos, incidentes
ni decisiones previas.

La auditoría distingue implementación, instalación técnica y autorización financiera.
LIVE sigue sin ensamblador, hechos certificados ni puesta en servicio operativa;
no se añade un marcador o se retira el guard para simular comisión. La evidencia
BOUNDED_SYMBOLS no acredita toda cuenta. La fuente Testnet elige ventanas actuales
sin rellenar huecos ni borrar cohortes. Los30 días y la evaluación OOS son política
de evidencia separada de la integración del ejecutor.

La correctiva 59 publica el espejo del heartbeat después de la transacción SQLite.
El falloWindows de seguridad58 se conserva como incidencia; no se declara reparado
retrospectivamente por repetir la misma prueba o modificar su expectativa.

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

## 2026-10-03 — Independent supervisor dependency closure and UI ownership

An isolated reproduction of the 0.10.14 refresh found that the signed bot contained `native_protection_compat.py`, while the independent-agent refresh inventory omitted it. Updating the supervisor without that dependency could break recovery/restore imports and block heartbeat delivery. The refresh and capability inventories must match, and CI must import the actual refreshed modules in a separate process without access to the source checkout. Optional updater metadata failure withdraws update/restore capabilities and automatic rollout while preserving the basic heartbeat; installation safety gates remain mandatory.

The Windows indicator has separate ownership from the trading engine. A per-install/session mutex prevents duplicate indicators and their repair timers, and an OS file lock serializes signed agent refresh against other repairs and the app watchdog. Repair success requires new HTTPS evidence; a running process or copied files alone cannot prove reconnection. These protections cannot recover a powered-off PC or fix rejected credentials. An affected old independent supervisor may require a locally verified dependency recovery before remote rollout becomes available again.

### Confirmed incident and recovery record

The owner's PowerShell output confirmed that task `Crypto Paper Portal Agent` was `Running`, but `trader/native_protection_compat.py` did not exist in its actual `WorkingDirectory`. `data/remote-status.json` showed `sync_ok=False`, `error_type=ModuleNotFoundError` and no `last_success`. The 0.10.14 photo also showed two indicator icons; it did not establish two trading engines.

The root cause was an incomplete independent refresh, not an unsigned bot package: `trader/update_supervisor.py` imported `.native_protection_compat`; the signed installation and `scripts/windows_agent.py::SUPERVISOR_MODULES` contained the helper, but `scripts/refresh_independent_agent.py::MODULES` omitted it. A real refresh into an empty agent directory followed by isolated Python imports reproduced `ModuleNotFoundError: No module named 'trader.native_protection_compat'`. Earlier protections verified the signed target and restarted the agent, but did not prove that the separately copied dependency inventory was complete. Testing inside the source checkout could hide this defect.

The successful local recovery derived the agent root from the existing task, checked the committed signed installation journal against installed version and sequence, and verified the helper's SHA-256 against that inventory. It stopped only the agent task, copied the already installed verified helper through a temporary file, rechecked the hash, moved it into the missing destination and restarted that same task in `finally`. It refused mismatched inventories, an existing destination or update maintenance. Do not turn this incident-specific procedure into blind copying from GitHub or a development checkout.

The owner pasted `Módulo verificado recuperado.` and subsequently reported that Windows had updated to 0.10.15 and the connection was visible again. This is owner-reported runtime recovery, not a direct development-session capture of the operating PC. Single-indicator state, two fresh authenticated syncs and native exchange orders remain separate evidence requirements.

### Preventive requirements for future maintainers and AI

- Treat the signed target and independent supervisor as separate installations. Update both inventories whenever adding an agent/supervisor dependency. Preserve `test_refresh_inventory_matches_supervisor_capability_inventory` and `test_refreshed_independent_agent_imports_without_source_checkout` in `tests/test_agent_refresh.py`; the latter exercises actual signed-module refresh and `python -I -B` imports in a clean root.
- Preserve optional updater-metadata isolation in `trader/remote_agent.py`: withdraw update/restore offers and automatic rollout when unavailable, retain the basic heartbeat where startup permits, and report `SUPERVISOR_UNAVAILABLE:<ExceptionClass>`. Never weaken signature, sequence, native compatibility or restore checks to reconnect.
- Preserve indicator ownership in `scripts/manager_windows.ps1`, shared repair exclusion in `scripts/agent_self_heal.ps1` and the manager watchdog, and the real PowerShell child-process checks in `tests/windows_manager_lifecycle.ps1`. Old indicator processes require **Salir del indicador** and one reopening to load the new guard; hiding a window is insufficient.
- Diagnose sync evidence before repeating restart/repair. Two distinct increasing `last_success` values with `sync_ok=True`, a running task and no supervisor degradation are required for a successful repair notice. A missing dependency, offline PC and rejected credentials need different remedies.
- Preserve observation data and trading state during monitoring recovery. Do not change strategy, leverage, risk or financial journals to fix agent connectivity, and never start another trading engine.

The correction is PR [#91](https://github.com/jlboper/Crypto-BOT/pull/91), merged as `2e73c67b68e422bc236fe3e66323e1034b9c2b7a`. Protected publication [37168205095](https://github.com/jlboper/Crypto-BOT/actions/runs/37168205095) succeeded and signed version 0.10.15 for source `4286f185719d080efce4da97f41ef8302b252e0d`. Release validation passed 271 offline Python tests, 75 Node tests and Windows PowerShell lifecycle checks. GitHub timestamps are 2026-10-04 UTC; the incident date above follows the owner's 3 October report. Publication success alone never proves Windows installation. These checks address the reproduced failure class; they do not guarantee that every future connection failure is impossible.


## Registro histórico

Las notas anteriores se conservaron sin alterar en
[docs/archive/before-0.10.59](docs/archive/before-0.10.59/INDEX.md), con manifiestoSHA-256.
Esas notas describen cortes pasados; no sustituyen la evidencia de instalación.
