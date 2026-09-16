# Portal privado en Cloudflare

## Despliegue del 15-09-2026

Actualización posterior: agente Windows conectado y telemetría PAPER real verificada. Ver [../WINDOWS_CONNECTION.md](../WINDOWS_CONNECTION.md). El motor original no se migró; sus controles no son instantáneos. No se enviaron órdenes de prueba. Para verificar un portal ya conectado usar `node scripts/check-connection.mjs`; el smoke de instalación inicial exige que aún no haya telemetría.

Publicado en https://crypto-paper-private-portal.jlboper.workers.dev con Workers Free confirmado en el panel ($0, plan actual). D1 es dedicada al portal. El frontend local/remoto está unificado; las pantallas privadas se alimentan de una proyección acotada y el Research Lab puede solicitar un trabajo idempotente al agente. El despliegue del Worker no arranca el agente ni el motor de Windows.

Las claves se generaron localmente en `.secrets`, con ACL restringida al usuario propietario; solo sus hashes se enviaron al Worker. La clave de acceso del portal está en `.secrets/owner-access-key.txt`; no es la contraseña de Cloudflare. No publicar ese archivo ni windows-agent.env. El script `scripts/smoke-production.mjs` valida HTTPS, autenticación y cierre de sesión sin enviar comandos ni telemetría; aprobó las 18 comprobaciones y dejó sus resultados en `production-verification.json`. El error TLS inicial se resolvió durante la activación. Se corrigió también la combinación de cabeceras del proveedor de assets mediante Headers.set y se añadió cobertura al test existente. La pantalla de acceso se comprobó en navegador. No se probó aún desde un teléfono físico ni se conectó Windows.

Esta implementación sustituye el servidor Python del portal por un Worker y una base D1. El bot y el Research Lab siguen en Windows. El agente usa conexiones salientes HTTPS cada 30 segundos; no requiere VPN, túnel ni puertos entrantes en la PC. El navegador consulta el mismo servidor público desde PC o celular.

## Costo previsto

Usar exclusivamente Workers Free, D1 Free y el subdominio gratuito workers.dev. No hace falta comprar dominio ni contratar VPS. Los límites publicados son 100 000 solicitudes de Worker/día, 10 ms de CPU por solicitud, 5 millones de filas leídas D1/día, 100 000 filas escritas/día y 5 GB de almacenamiento D1 por cuenta. Los índices también consumen escrituras. Consultados el 14-09-2026:

- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/workers/configuration/routing/workers-dev/

Un agente cada 30 segundos hace unas 2880 solicitudes/día. Cada navegador visible añade unas 2880/día. Se conserva una instantánea, hasta 10 sesiones y 90 días de comandos; no se suben históricos de velas. No hay llamadas de IA desde el portal. El consumo real, el tráfico malicioso y otros proyectos de la cuenta pueden agotar cuotas. Las pruebas locales no certifican el límite de CPU de producción. El plan gratuito no asegura disponibilidad; confirmar el plan de la cuenta antes de publicar. Los costos de IA del bot y electricidad/Internet de Windows son independientes.

## Seguridad y alcance

Clave aleatoria de propietario de 256 bits; el Worker almacena únicamente su SHA-256. No introducir una contraseña humana: este mecanismo depende de la alta entropía de la clave generada. No es compatible con el hash scrypt del portal Python. La clave del agente es distinta y también se verifica por hash. Sesión de una hora mediante cookie Secure/HttpOnly/SameSite, CSRF, origen exacto, presupuesto de intentos de login y respuestas sin caché. Rotar la clave del propietario invalida las sesiones.

Los controles kill/resume tienen expiración, identificador idempotente y confirmación del agente. Resume requiere telemetría reciente. La cola de trabajos admite únicamente Research y las acciones del actualizador explícitamente permitidas; no acepta shell, rutas ni URL del navegador. Solo se acepta telemetría PAPER. No permite cambiar a LIVE ni operar directamente en el exchange. No enviar claves OpenAI/Binance al servidor.

El centro de actualizaciones descubre de forma solo lectura la ejecución del commit actual de GitHub y abre su aprobación protegida. La credencial de Cloudflare permanece como secreto del entorno GitHub y nunca se entrega al Worker. Este flujo publica el portal; el Update Manager firmado del bot permanece en Python y la instalación remota del motor está deshabilitada. Android, notificaciones push, recuperación de acceso, MFA y comprobación real desde un teléfono siguen pendientes.

## Publicación reproducible

Ejecutar desde esta carpeta con Node 24 y pnpm. Instalar con `pnpm install --frozen-lockfile`. Wrangler está fijado en 4.131.1 y solo se autorizan los scripts de esbuild/workerd.

1. Iniciar sesión con `node node_modules/wrangler/bin/wrangler.js login`. La autorización ocurre en Cloudflare; no pegar contraseñas ni tokens en el chat. Confirmar Workers Free y elegir el subdominio workers.dev en la cuenta.
2. Consultar la cuenta con `node node_modules/wrangler/bin/wrangler.js whoami` y crear una base dedicada con `node node_modules/wrangler/bin/wrangler.js d1 create crypto-paper-private-portal`.
3. Crear configuración con `node scripts/configure.mjs ACCOUNT_ID DATABASE_ID https://crypto-paper-private-portal.SUBDOMINIO.workers.dev`. Los identificadores no son credenciales. El script rechaza valores de ejemplo, otros dominios y sobrescrituras.
4. Generar claves con `node scripts/provision.mjs https://crypto-paper-private-portal.SUBDOMINIO.workers.dev`. Debe coincidir exactamente con el origen del paso anterior. No muestra secretos. Proteger la carpeta `.secrets` con ACL de Windows del propietario; los modos POSIX no sustituyen esas ACL. Guardar owner-access-key.txt en un gestor de contraseñas. windows-agent.env contiene solo origen y clave del agente. No compartir esa carpeta ni añadirla a Git.
5. Ejecutar `node scripts/deploy.mjs` para verificar sin publicar. Tras comprobar plan y cuenta, `node scripts/deploy.mjs --apply` aplica las migraciones revisadas a la base dedicada y publica Worker, assets y hashes mediante un archivo de secretos. No inicia el agente ni el bot. Para publicaciones posteriores desde Work/GitHub, usar el entorno protegido descrito en `../GITHUB_RELEASES.md`.
6. Comprobar HTTPS, login/logout y denegación sin sesión desde PC y celular. Antes de conectar Windows, acordar la migración controlada de la instalación activa. Incorporar solo PORTAL_ORIGIN y PORTAL_DEVICE_TOKEN al entorno privado de la instalación seleccionada. No lanzar una segunda instancia del motor. Validar PAPER, kill/ack/resume, desconexión y reconexión antes de dar el despliegue por terminado.

No subir datos, secretos, configuraciones de producción ni respaldos. Wrangler publica únicamente el módulo y los assets declarados. No habilitar cuentas temporales, upgrades automáticos ni productos adicionales para sortear problemas de autenticación.

## Validación y recuperación

`node --test tests/*.test.mjs` comprueba autenticación, separación de credenciales, CSRF, límites, validación PAPER, expiración, idempotencia, trabajos, descubrimiento GitHub de solo lectura, transacciones y configuración. Incluye una prueba real con workerd y D1 locales sin conexiones al exchange ni a IA. `node node_modules/wrangler/bin/wrangler.js deploy --dry-run` comprueba el empaquetado, no despliega ni verifica la cuenta.

Validación del 16-09-2026: 32 pruebas Node/Worker y 66 pruebas Python offline aprobadas, sin arrancar el motor ni hacer llamadas a IA/exchange. Consumo sostenido de CPU, recuperación D1 completa y comprobación en teléfono físico siguen pendientes.

Antes de estos cambios se conservó `../../before-cloudflare-v0.6.2.zip`, SHA-256 `062BB98DBFB9D6286EAD1AF4390C8C0132672ED88005B3CF880ECC2719C401CD`. Es respaldo de código, no de credenciales ni de datos operativos. Para volver al portal anterior, planificar la restauración de código y su configuración correspondiente; las sesiones y hashes de ambos portales no son intercambiables.
