# Crypto AI Trader — contexto para ChatGPT Work

Lee este documento y el código de la rama de trabajo antes de proponer cambios. No asumas que una conversación de Codex se comparte automáticamente con Work. No actives LIVE ni prometas rentabilidad.

## Estado del proyecto

El canal estable de `jlboper/Crypto-BOT` publica ZIP y latest.json; su versión estable es 0.6.2. La auditoría local partió de ese paquete: 54 archivos coincidieron, y config.toml contiene ajustes locales que no deben sobrescribirse. La instalación Windows mantiene su motor original; las mejoras auditadas del motor todavía requieren una migración controlada.

Windows ejecuta el motor PAPER y un agente independiente. El portal remoto usa Cloudflare Workers Free y D1; el agente conecta hacia fuera por HTTPS cada unos 30 segundos, sin VPN, túneles ni puertos públicos en la PC. Una tarea de Windows inicia el agente 30 segundos después del login. No inicia otra instancia del motor.

## Código y responsabilidades

- trader/engine.py, broker.py, database.py: estrategia, riesgo, contabilidad y persistencia.
- trader/ai_advisor.py: IA limitada a validar/reducir/vetar entradas; modelo configurado gpt-5.6-luna, susceptible de override OPENAI_MODEL. No entregar control arbitrario de órdenes a la IA.
- trader/research.py: comparación multi-activo, selección sobre entrenamiento, walk-forward, holdout final reservado y estrés de costos. No promover estrategias automáticamente.
- web/: frontend compartido por localhost y Cloudflare. portal-bridge.js adapta autenticación y consultas; build_unified_portal.py copia assets al Worker.
- trader/remote_agent.py y scripts/windows_agent.py: telemetría, pausa/reanudación con expiración y checkpoint. La BD operativa se abre en modo de solo lectura. Una pausa local/automática no se libera remotamente.
- trader/portal_snapshot.py: proyección acotada de operaciones, métricas, IA e informe Research; nunca exportar settings completos, entornos ni registros crudos.
- cloudflare/src/worker.mjs: sesión con cookie segura, CSRF, origen exacto, clave de propietario y token de agente independientes, cola idempotente y D1.
- trader/update_manager.py: verificación Ed25519, límites y rutas permitidas, protección contra downgrade, backups y recuperación con journal. No detiene/arranca procesos por sí mismo.

## Implementado y comprobado a 2026-09-15

Portal privado publicado, autenticación y telemetría PAPER en funcionamiento. Interfaz compartida distribuida al panel local y remoto. Pantallas de posiciones, operaciones, revisiones IA, equity y Research Lab. El portal puede solicitar Research mediante una cola idempotente y Windows lo ejecuta como proceso separado. La aplicación Windows abre el portal remoto y el mismo centro de actualizaciones. La validación vigente comprende 66 pruebas Python offline y 32 pruebas del Worker/frontend. Iconos del escritorio y del acceso directo dentro de la carpeta apuntan al mismo ICO de la aplicación.

## Pendiente; no presentar como terminado

El centro de actualizaciones puede descubrir el commit actual y llevar al propietario a la aprobación protegida de GitHub para publicar el portal. No instala el bot Windows. Para el motor faltan el canal firmado, la custodia de firma y el supervisor de parada/reinicio con verificación real de salud. El latest.json antiguo tiene SHA-256, pero no firma Ed25519; nunca rebajar verificación para instalarlo remotamente. La interfaz local conserva las APIs del proceso original hasta una migración controlada. No hay integración MCP de control desde Work ni app Android/notificaciones push activa.

## Cómo trabajar desde Work

En una tarea de Work, conectar GitHub y pedir explícitamente leer este archivo y la rama de desarrollo del proyecto. Revisar cambios, trabajar en una rama y preparar PR. No sobrescribir paquetes estables ni latest.json hasta validar la release. Después del merge, revisar el commit y sus pruebas desde el centro de actualizaciones; la aprobación final ocurre en el entorno protegido de GitHub. El acceso al repositorio aporta código/documentos, no acceso implícito a la PC ni a sus claves. Consulta `GITHUB_RELEASES.md` y la documentación oficial de Work y plugins en https://learn.chatgpt.com/docs/get-started-with-work y https://learn.chatgpt.com/docs/plugins.

## Reglas de publicación

No subir .env*, data/, bases SQLite, posiciones, registros, respaldos, .secrets/, claves privadas, configuraciones de producción, credenciales OAuth ni archivos de estado de la PC. No guardar secretos en prompts, argumentos CLI ni salidas de tests. Conservar configuración y datos operativos al actualizar. No arrancar un segundo motor; no matar procesos Python por nombre. Una release debe indicar exactamente qué se probó y qué sigue pendiente.

Validación: Python 3.11+; `python scripts/test_offline.py`. Para actualizaciones instalar la dependencia opcional cryptography indicada por pyproject.toml. Portal: Node 24, pnpm install --frozen-lockfile, node --test tests/*.test.mjs desde cloudflare. No usar claves de producción en tests. No publicar desde Work si no se ha configurado expresamente una identidad de despliegue con permisos limitados.
