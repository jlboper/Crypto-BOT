# Progreso actual de actualización

Base verificada: main `b79c7dfa2de810a8181b730706a67f2282bd60fe`, PR135,
0.10.58 firmada e instalada. Auditoría local5 noviembre 2026:332/332 archivos,
agente 15/15, dos HTTPS nuevos, un solo motor Testnet, fuentes y datos preservados.
El workflow de publicación41899913559 aprobó Linux/Windows y publicó; el workflow
separado de seguridad41899913720 falló una prueba Windows de heartbeat. Se conserva
ese fallo; la candidata 59 corrige la carrera y exige validación propia.

## Candidata0.10.59

- Corrección de heartbeat: memoria actualizada sólo tras commit durable. Regresiones
  de transacción bloqueada y escritura fallida; expectativa CLOCK_REGRESSION conservada.
- Documentos actuales consolidados; versiones previas archivadas sin alteración.
- Auditoría de limpieza y permisos hecha fuera del producto, sin publicar datos
  privados o convertir sus resultados en autoridad financiera.
- Testnet sigue activo. Estrategias/riesgo/IA/claves/permisos/LIVE no modificados.

Validación local final:1765/1765 Python offline PASS, cero fallos, errores u
omisiones, fuentes intactas y red externa bloqueada. Revisión independiente y
34 pruebas enfocadas de observador PASS. La interfaz no cambió.

PR, CI de ambas plataformas, main, firma e instalación59 deben tener resultados
propios antes de declararla entregada. No repetir suites aprobadas salvo cambios,
fallos o preocupaciones concretas pendientes.

## Registro histórico

Las notas anteriores se conservaron sin alterar en
[docs/archive/before-0.10.59](docs/archive/before-0.10.59/INDEX.md), con manifiestoSHA-256.
Esas notas describen cortes pasados; no sustituyen la evidencia de instalación.
