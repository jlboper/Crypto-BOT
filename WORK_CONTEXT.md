# Work Context — Crypto AI Trader

## Estado actual

La rama estable trabaja con un único proceso supervisado y dos motores de prueba en paralelo:

- **Spot Testnet**: motor principal multi-activo, sin margen ni cortos, con estrategia swing, límites de riesgo y revisión IA final.
- **Futures Demo**: forward test separado de BTCUSDT, LONG/SHORT, 1x automático, ISOLATED, ONE_WAY y máximo una posición. Usa ledger, journal y kill switch propios.
- **PAPER**: respaldo técnico, CI, regresiones y recuperación. No es el entorno diario predeterminado.
- **LIVE**: no implementado. Ninguna métrica o estado habilita capital real automáticamente.

## Arquitectura operativa

- `web/`: interfaz única compartida por localhost y Cloudflare. El portal local y remoto deben conservar la misma estructura, nomenclatura y métricas.
- `scripts/manager_windows.ps1`: centro de control compacto de Windows; abre portal local/remoto, reinicia el motor, gestiona inicio automático, kill switch y actualizaciones firmadas.
- `trader/engine.py`: ciclo principal Spot y llamada al forward engine Futures durante TESTNET.
- `trader/futures_forward.py`: señal, revisión IA final, ejecución/recovery y protección del forward test Futures Demo.
- `trader/update_manager.py` + `trader/update_supervisor.py`: actualización firmada, parada cooperativa, health-check, commit/rollback y restauración de código anterior.
- `scripts/windows_agent.py`: agente saliente HTTPS para portal remoto; no crea un segundo motor.
- `data/trader.db`, `data/testnet-trader.db`, `data/futures-testnet.db`: ledgers separados. Nunca fusionarlos.

## Reglas permanentes

1. Nunca introducir una ruta Binance LIVE sin una fase explícita y separada de diseño/revisión.
2. Las claves y `.env.local` permanecen fuera del repositorio y del portal.
3. Spot y Futures deben conservar identidad, ledger, riesgo y kill switch separados.
4. La IA es una última compuerta para nuevas entradas; nunca bloquea un cierre protector, stop, reconciliación o recovery.
5. No borrar históricos, bases financieras, paquetes de rollback o mecanismos de recuperación durante limpiezas visuales.
6. Mantener portal local y remoto sobre los mismos assets web; evitar dos UIs divergentes.
7. Los tests deben declarar explícitamente PAPER/TESTNET cuando el comportamiento depende del entorno.
8. Antes de merge: `python scripts/test_offline.py` en Linux y Windows, parse de PowerShell y tests del Worker/frontend.

## Flujo de releases

Work prepara una rama/PR. GitHub ejecuta validaciones. Al integrar en `main`, el workflow protegido publica el portal y construye el paquete firmado cuando cambia la versión. Windows instala únicamente paquetes verificados mediante el supervisor. El centro local de actualizaciones puede verificar e instalar sin depender del portal remoto.

## Fase actual

La prioridad es **observación**, no añadir estrategia por ruido de pocos días. Spot y Futures acumulan métricas separadas (días, cierres, P&L/retorno, drawdown, calidad y errores). Cambios de estrategia o riesgo deben basarse en evidencia suficiente; correcciones de seguridad/operación sí pueden hacerse antes.
