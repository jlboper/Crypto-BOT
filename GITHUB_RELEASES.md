# Actualizaciones desde Work, GitHub y el portal

## Flujo previsto

1. En Work, abrir `jlboper/Crypto-BOT`, leer `WORK_CONTEXT.md`, crear una rama y un pull request. No modificar `latest.json` ni los ZIP estables como parte de un cambio ordinario.
2. GitHub ejecuta las pruebas sin credenciales de producción. Al integrar el PR en `main`, vuelve a validar el commit exacto.
3. El trabajo `publish` queda esperando en el entorno protegido `portal-production`. El centro de actualizaciones del portal muestra solo el commit que siga siendo el `HEAD` actual de `main` y enlaza a su ejecución.
4. El propietario revisa el commit y las pruebas en GitHub y aprueba el entorno. La credencial de Cloudflare se entrega al job únicamente después de esa aprobación.
5. CI rechaza migraciones D1 pendientes, publica el mismo commit aprobado, comprueba salud tres veces y solicita rollback de Cloudflare si la salud falla.

La aplicación Windows y el menú del área de notificaciones abren el mismo centro en `https://crypto-paper-private-portal.jlboper.workers.dev/#updates`. Este flujo publica el portal. No instala el motor Windows ni cambia PAPER.

## Configuración única requerida en GitHub

Crear el entorno `portal-production` antes de habilitar el workflow:

- Revisor obligatorio: `jlboper`. En esta cuenta de una sola persona debe permitirse la autorrevisión; si se activa `prevent self-review`, el propietario puede quedar impedido para aprobar una ejecución iniciada al integrar su PR.
- Limitar ramas de despliegue a `main`.
- Deshabilitar el bypass administrativo si la interfaz y el plan lo permiten.
- Secreto de entorno `CLOUDFLARE_API_TOKEN`: token de API nuevo, limitado a esta cuenta, con Workers Scripts:Edit y D1:Read. La comprobación de migraciones ejecuta únicamente SELECT. No copiar el OAuth local de Wrangler.
- Secreto de entorno `DEPLOYMENT_ENABLED`: valor exacto `portal-production-v1`. Su ausencia hace que CI falle antes de publicar.
- Variables de entorno `CLOUDFLARE_ACCOUNT_ID`, `PORTAL_D1_ID` y `PORTAL_ORIGIN`. El origen debe ser exactamente `https://crypto-paper-private-portal.jlboper.workers.dev`.

Cloudflare documenta que CI no interactivo requiere un API token y recomienda limitarlo a la cuenta necesaria. Nunca guardar ese token en el repositorio, un prompt, un log o el Worker. Rotarlo si cambia el equipo o se sospecha exposición.

## Migraciones

El despliegue automático no cambia el esquema D1. Si un PR añade una migración, CI se detiene antes de publicar. Revisar que sea aditiva y compatible con la versión activa, respaldar el estado necesario, aplicarla con el flujo local autenticado y confirmar que ya no hay migraciones pendientes. Entonces se vuelve a ejecutar la publicación aprobada.

## Límites

La aprobación de GitHub protege publicaciones del portal, no sustituye la firma Ed25519 de paquetes del bot. La instalación remota del motor sigue deshabilitada hasta tener canal firmado, supervisor de parada/reinicio, comprobación real de salud y recuperación probada. Un commit que solo esté en una rama o PR no está publicado en Cloudflare ni instalado en Windows.
