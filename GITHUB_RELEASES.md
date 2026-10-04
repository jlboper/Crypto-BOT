# Actualizaciones desde Work, GitHub y Windows

## Flujo autorizado desde el 4 de octubre de 2026

1. Work prepara una rama/PR contra `main`, preserva datos/credenciales y aumenta la versión si cambian archivos del paquete.
2. Los PR pasan pruebas sin acceso al job de publicación. Tras integrarlos, un push a `main` valida otra vez el commit exacto en Linux y Windows, incluyendo el supervisor Windows y los tests del Worker/frontend.
3. Solo ese push validado puede ejecutar `publish` en `portal-production`. El propietario retiró la revisión obligatoria para automatizar las publicaciones; si la vuelve a configurar, la revisión pendiente debe respetarse.
4. Los scripts comprueban que la revisión siga siendo el HEAD de main. CI conserva preflight de versión, Actions fijadas por SHA, credenciales limitadas, rechazo de migraciones pendientes y health-check con rollback.
5. Tras desplegar el portal, construye y verifica el paquete firmado. El firmante valida OIDC, repositorio/propietario inmutables, entorno, workflow/push de main, main actual y coincidencia con el commit desplegado. No acepta PRs ni secretos de firma permanentes en GitHub.
6. El agente Windows existente solicita automáticamente la release firmada exacta al sincronizar. El supervisor verifica Ed25519, hashes, secuencia, propiedad del proceso, parada cooperativa, barrera de arranque y salud; conserva recuperación y datos financieros. Un fallo real no se reintenta en bucle.

El centro de actualizaciones muestra la ejecución de main actual. **Buscar actualizaciones** e **Instalar versión verificada** siguen como alternativas manuales. Publicado/firmado e instalado/conectado son hechos distintos; verificar ambos antes de comunicar éxito completo.

## Configuración de GitHub

- Conservar `portal-production` y sus credenciales existentes. Limitar despliegues a `main`; no añadir bypasses, tokens de aprobación ni administración GitHub al portal.
- `CLOUDFLARE_API_TOKEN`: token limitado a la cuenta necesaria, Workers Scripts:Edit y D1:Read. No copiar OAuth local de Wrangler ni mostrar el token.
- `DEPLOYMENT_ENABLED`: valor `portal-production-v1`; su ausencia bloquea el despliegue.
- Variables `CLOUDFLARE_ACCOUNT_ID`, `PORTAL_D1_ID` y `PORTAL_ORIGIN`, con el origen existente del portal.
- El propietario puede restaurar revisores obligatorios; el workflow esperará esa aprobación real.

## Migraciones y recuperación

El despliegue no aplica migraciones D1. Si existen pendientes, revisar compatibilidad y respaldo, aplicarlas mediante el flujo autenticado y volver a comprobarlas. Reintentar publicación solo mientras ese commit siga siendo main actual. No reactivar trabajos obsoletos ni crear PRs vacíos para fabricar eventos push.

Esta política automatiza publicaciones y actualizaciones firmadas; no habilita Binance LIVE ni promoción automática de estrategias o límites de riesgo. El motor, sus ledgers y el agente conservan sus responsabilidades separadas.
