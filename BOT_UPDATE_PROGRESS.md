# Actualización remota del bot: estado comprobado

Estado al 17 de septiembre de 2026. Cambios en la copia de auditoría y propuestos
en GitHub mediante PR #3 (`work/supervised-bot-updates`); no desplegados sobre
el motor o agente operativos.

## Implementado y probado

- Identificación SHA-256 del manifiesto completo firmado. Vincula versión,
  secuencia, caducidad, URL y contenido con una aprobación concreta.
- El receptor de trabajos exige esa identificación para `update_install`, la
  conserva y rechaza reutilizar un identificador de trabajo con otra versión.
- La descarga devuelve la identificación verificada. El ejecutor compara la
  aprobación antes de intentar una instalación.
- `UpdateManager.apply(..., expected_release=..., defer_commit=True)` instala
  con los bloqueos de los escritores y deja la transacción en `pending_health`.
- `commit_pending(release_id, health_check)` comprueba archivos e identificación
  y exige que la comprobación externa devuelva exactamente `True`. No mantiene
  el bloqueo del motor durante esta comprobación. Solo entonces confirma la
  secuencia instalada. Conectado al supervisor con comprobación del proceso y
  una respuesta HTTP local que identifica PID y nonce de arranque.
- Recuperación de una transacción pendiente con el motor detenido: restaura
  archivos y la base SQLite previa, incluida la información del WAL. Si la
  base no existía, elimina la creada durante el arranque fallido.
- Bloqueo de transacciones común a los instaladores y bloqueo de staging
  durante la aplicación para evitar reemplazar el paquete mientras se instala.
- Supervisor de Windows con parada cooperativa, barrera antes del primer ciclo,
  recuperación de transacciones interrumpidas y reinicio de la versión anterior.
  Solo puede terminar hijos propios; nunca mata un PID descubierto en un archivo.
- Si la transacción ya se confirmó, la recuperación conserva su base de datos:
  no revierte balances después de autorizar ciclos financieros.
- Puerto HTTP exclusivo en Windows, arranque con error visible si está ocupado,
  bloqueo de controles HTTP durante mantenimiento e invalidación de bytecode al
  instalar y al restaurar archivos Python.
- 88 pruebas Python satisfactorias con red externa bloqueada, datos sintéticos
  y directorios temporales; se ejecutaron procesos ficticios, nunca el bot
  operativo. Además, 10 repeticiones satisfactorias de recuperación posterior
  al commit. Esto no equivale a una actualización del motor real en producción.

## Pendiente antes de habilitar instalaciones

1. Preparar la transición inicial de la instalación original al protocolo de
   mantenimiento. El supervisor rechaza instalaciones antiguas que todavía no
   lo soportan, antes de solicitarles la parada. El agente tiene recuperación
   al iniciar, condicionada al aprovisionamiento explícito del canal local.
2. Publicación de paquetes y manifiestos con firma Ed25519 desde un entorno
   GitHub protegido; aprovisionamiento de la confianza pública local.
3. Transporte de `release_id` en el esquema/API de trabajos del portal y
   selección de la versión concreta en la interfaz. El portal actualmente
   todavía no envía ese campo; las solicitudes antiguas de instalación serán
   rechazadas por el nuevo receptor, de forma intencional.
4. Integración completa y pruebas del supervisor con procesos ficticios,
   publicación revisada y primera transición controlada de la instalación
   original. La instancia original sigue usando su código anterior.

`scripts/remote_job.py` integra el supervisor, pero exige
`supervised_install_enabled: true` en el canal local de confianza y que el
agente esté fuera de la carpeta que se actualiza. Este permiso no se ha
aprovisionado. No se ha habilitado un botón funcional de instalación ni
configurado un canal de firma en producción. La publicación del portal es un
circuito separado ya existente. El flujo nuevo de GitHub valida en Windows y
Linux; no publica ni instala paquetes.

Las copias anteriores a estos cambios están en
`data/update-manager-before-supervised.py` y
`data/update-tests-before-supervised.py`.
