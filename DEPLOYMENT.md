# Despliegue del portal

## Alternativa gratuita seleccionada

La implementación Cloudflare Workers + D1 compatible con el agente HTTPS se publicó el 15-09-2026 en Workers Free. La guía vigente y el estado de verificación están en [cloudflare/README.md](cloudflare/README.md). El agente Windows está conectado mediante HTTPS saliente y se inicia al iniciar sesión. Las instrucciones VPS siguientes corresponden a la alternativa Python original y no son requisitos para Cloudflare.

## Alojamiento y presupuesto previo

Opción propuesta: VPS Linux pequeño (por ejemplo Hetzner CX23), Caddy para HTTPS automático, Waitress para la aplicación y SQLite en disco persistente. La tarifa oficial de CX23 es 5.49 EUR/mes sin IPv4 ni impuestos en Alemania/Finlandia: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ (consulta 14-09-2026). Reservar margen para IPv4, dominio propio, backup externo y tráfico. No se ha cerrado un costo total; se debe confirmar en la cuenta antes de contratar. Render es alternativa administrada, pero requiere servicio pagado y persistencia; no se verificó una cotización final: https://render.com/pricing.

Faltan elección/aprobación del alojamiento, cuenta con facturación, dominio o subdominio y acceso al servidor. No es necesario instalar VPN/túneles ni abrir puertos en la PC. El servidor público sí necesita recibir HTTPS y resolver el dominio.

## Componentes reales

1. En servidor: subir únicamente `trader/remote_portal.py`, `trader/__init__.py`, `portal_web/` y `deploy/`. No subir `.env.local`, ZIP de respaldo, datos de trading, código de firma privada ni toda la carpeta de trabajo indiscriminadamente.
2. Preparar Python 3.11+, entorno virtual y `deploy/requirements-portal.txt`. Crear usuario de sistema `crypto-portal`; colocar código en `/opt/crypto-portal`, estado en `/var/lib/crypto-portal`. El servicio incluido escucha solo 127.0.0.1:8080.
3. Proveer secretos usando `scripts/provision_portal.py --output RUTA_NUEVA --origin https://DOMINIO`. La contraseña se solicita sin eco. No se ejecutó esta utilidad durante la auditoría. En Windows revisar que ACL de la carpeta limite acceso al usuario; chmod no sustituye ACL Windows.
4. Llevar `server.env` por un canal seguro a `/etc/crypto-portal.env`, propietario root y permisos 0600. Contiene hashes de contraseña/token, no la clave del dispositivo. Configurar servicio con `deploy/crypto-portal.service`.
5. Configurar Caddy con `deploy/Caddyfile` y `PORTAL_HOST=DOMINIO`, DNS y certificados. No abrir 8080 públicamente. Restringir SSH, usar actualizaciones de seguridad del SO y respaldo consistente de SQLite mediante sqlite3.backup, con restauración ensayada.
6. En Windows, incorporar solamente PORTAL_ORIGIN y PORTAL_DEVICE_TOKEN de `device.env` al entorno privado de esta instalación. No copiar claves OpenAI/Binance al servidor. El módulo lee `.env.local` de su propio proyecto, no archivos del padre.
7. Tras planificar migración y detener la versión operativa de forma controlada, validar el cambio en PAPER. El agente se inicia explícitamente con `python -m trader.remote_agent`; no inicia motor ni dashboard. No se inició durante esta tarea. Integrarlo como tarea programada Windows o servicio es un paso posterior del despliegue, con su propia identidad/ACL.
8. Probar login desde PC y teléfono, expiración/logout, controles y confirmación recibida, pérdida de Internet y reinicio. Un control en estado queued no está aplicado todavía. El bot debe seguir protegiendo localmente si el portal no responde.

## Recuperar el código auditado

No reemplazar la instalación activa automáticamente. `../baseline-v0.6.2.zip` restaura código/configuración original, sin secretos ni datos. Extraer en carpeta nueva, comprobar BASELINE_SHA256.json, y planear el intercambio con el motor detenido. Nunca sobrescribir data o `.env.local` con este respaldo.

## Paquetes firmados

Instalar cryptography 50.0.1 en el entorno que verificará actualizaciones; el Python del bot original no lo tenía. El entorno de pruebas de Codex sí lo incluye. Mantener una clave Ed25519 privada cifrada offline; provisionar únicamente sus 32 bytes públicos como `data/trusted-update.pub`. No aceptar una clave pública incluida por el mismo paquete.

El publicador prepara ZIP sin directorios explícitos, credenciales ni datos; solo rutas permitidas por `safe_name`, con `pyproject.toml` y `trader/__main__.py`, versión semántica superior a la instalada. Firmar con `scripts/sign_release.py --package RELEASE.zip --private-key CLAVE_OFFLINE.pem --version VERSION --sequence NUMERO --package-url https://ORIGEN/RELEASE.zip`. Solicita contraseña de la clave sin mostrarla. Subir ZIP y `RELEASE.zip.manifest.json` al mismo origen HTTPS.

En Windows:

```text
python -m trader.update_manager stage --root RUTA_PROYECTO --public-key RUTA_CLAVE_PUBLICA --manifest-url https://ORIGEN/RELEASE.zip.manifest.json
python -m trader.update_manager verify --root RUTA_PROYECTO --public-key RUTA_CLAVE_PUBLICA --package RUTA_ZIP --manifest RUTA_MANIFIESTO
python -m trader.update_manager apply --root RUTA_PROYECTO --public-key RUTA_CLAVE_PUBLICA --package RUTA_ZIP --manifest RUTA_MANIFIESTO
python -m trader.update_manager recover --root RUTA_PROYECTO --public-key RUTA_CLAVE_PUBLICA
```

`apply` y `recover` se niegan si los procesos relacionados están activos. No paran ni arrancan procesos. El servicio de salud postarranque, activación remota, rotación de claves, revocación de releases y migraciones SQLite reversibles están pendientes. El callback de salud interno está probado con fallos sintéticos, no equivale a verificar el motor real.

La interfaz Windows ya no ofrece el instalador heredado basado únicamente en SHA-256; abre el centro remoto de actualizaciones. Integrar el canal firmado y el supervisor antes de habilitar la instalación del motor. No eludir la firma para recuperar comodidad.

## Evolución Android

Mantener la API `/v1` y el servidor como intermediario. La app futura necesita autorización de usuario (OAuth/OIDC o sesión apropiada), almacenamiento seguro del token móvil, registro/revocación FCM y una outbox persistente de eventos con clave de deduplicación. Notificar cambios de estado/control, no cada sondeo. La clave del dispositivo Windows no debe convertirse en credencial de la app. Nada de FCM/Android/push está desplegado todavía.
