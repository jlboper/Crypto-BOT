# Verificación de la copia aislada

Resultado final: **55 pruebas, 0 fallos, 0 errores, 0 omitidas**. Detalle legible por máquina y hora de ejecución en `TEST_RESULTS.json`.

Ejecutor: `scripts/test_offline.py`, con el Python proporcionado por el entorno Codex y cryptography 50.0.1. Bloquea conexiones externas; los únicos servidores usados en pruebas son fixtures HTTP locales del dashboard. No inicia otra instancia del bot ni consulta APIs de pago.

Cobertura relevante:

- Transacciones contables con fallo inyectado y dos ventas concurrentes.
- Prevención persistente de duplicados y presupuesto diario de IA.
- Validación de NaN, infinito, veredictos desconocidos y tamaño cero de IA.
- Dimensionamiento con costos, efectivo, protección sin velas y durante kill switch.
- Fallo de universo después de ejecutar una protección, caché y datos antiguos.
- Reconexión GET acotada y rechazo explícito de escrituras a Binance.
- Walk-forward y holdout: alterar solo el futuro reservado no cambia la elección ni los resultados previos.
- Login, cookies protegidas, CSRF, origen, límite de intentos, controles permitidos, idempotencia y acuses.
- Firma Ed25519, paquete alterado, expiración, rutas peligrosas, downgrade/repetición, bloqueo de instancia activa y rollback.
- Diario de actualización interrumpido: restaura archivos y elimina módulos introducidos por el cambio.

Comprobaciones adicionales: `node --check portal_web/app.js` correcto; parser PowerShell sin errores en los scripts; huellas del código/configuración original comparadas con el respaldo, **0 cambios**.

No probado: conexión pública HTTPS, UX en dispositivos físicos, servicio systemd/Caddy en VPS, llamadas reales OpenAI/Binance, canal publicado de releases firmadas, descarga HTTPS real del staging, salud del motor tras actualización, cortes físicos de energía/disco, Android/FCM. No debe interpretarse esta batería como certificación de producción ni validación de rentabilidad.
