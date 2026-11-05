# Auditoría de arranque LIVE — 5 noviembre 2026

Estado del código auditado: **LIVE no comisionado**. No existe una fecha de arranque
verificada. La autorización para actualizar software no construye el ejecutor ni
certifica sus entradas financieras. Los permisos del exchange son otro requisito.

## Hallazgos que impiden arrancar

| Componente | Hecho verificable | Trabajo necesario |
| --- | --- | --- |
| Integración del motor | `TradingEngine.__init__` rechaza LIVE. El ciclo crea `LiveSupervisionService` sin runtime. | Ensamblar y conectar el recorrido operativo completo; no retirar el rechazo para caer en PaperBroker. |
| Hechos de cuenta | `ReadOnlyAdmissionFactsSource.__call__` conserva GETs y siempre rechaza la admisión. | Producir `AdmissionFacts` a partir de fuentes verificadas: inventario, órdenes, costes, cashflows, riesgo y baselines. |
| Puesta en servicio | `LocalAuthorizationProvider` lee autoridad protegida; no hay flujo distribuido que la prepare y escriba. El marcador de integración también falta. | Implementar revisión y emisión protegidas, ligadas al código, política, claves y evidencia reales. Un marcador o un JSON manual no basta. |
| Evidencia financiera | Las ventanas BOUNDED_SYMBOLS y los cortes asincrónicos no certifican toda cuenta ni protección continua. | Mantener huecos explícitos y reconstruir fronteras e identidades propias antes de certificar. |
| Política de aceptación | Se exigen días cualificados y evidencia independiente; el tiempo transcurrido no los genera. | Evaluar los resultados conciliados y la política explícita del propietario; no convertir resultados sintéticos en autorización. |

Referencias principales: [engine](trader/engine.py), [supervisor](trader/live_supervisor.py),
[autorización](trader/live_authorization.py), [admisión](trader/central_admission.py),
[propuestas](trader/live_proposal_source.py), [venue](trader/live_venue.py).

## Lo que sí existe

Spot Testnet y Futures Demo operan con ledgers separados y protección nativa.
La publicación firmada, instalación supervisada y recuperación técnica están
implementadas. Hay cadenas sintéticas de entrada, OCO Spot, protección Futures,
recuperación por identidad, reducción residual y conservación de reservas.
Estas pruebas usan fuentes/autoridad sintéticas; no equivalen a commissioning
con el autorizador local y datos reales. Pulse/Quant siguen en SHADOW.

## Contrato de cierre del ejecutor

Un cierre real debe probar un recorrido completo con el mismo autorizador,
fuente financiera, propuesta, filtros, ledger y recuperación que se distribuirán.
Debe fallar cerrado ante pérdida de identidad, datos incompletos, costes o
límites desconocidos; conservar reservas e intentos y recuperar sin reenvíos.
No puede etiquetar una wallet virtual como cuenta real, apropiarse de fills
por coincidir símbolo/cantidad o inventar baselines DAY/WEEK en fronteras UTC.

El estado de revisión del capital es inactivo hasta una decisión explícita con
importe, límites y alcance. Ni una clave con trading ni una instalación nueva
constituyen esa decisión. Este documento no es una autorización ni una señal
de rentabilidad.

## Permisos mínimos del exchange

La operativa futura necesita lectura y los permisos correspondientes a cada
producto: Spot & Margin Trading para las órdenes Spot y Futures para Futures.
No requiere habilitar retiros o transferencias. La capacidad de órdenes del bot
mantiene su allowlist propia. Revisar restricción IP y compatibilidad de las
claves antes de ampliar derechos; una clave creada antes de abrir Futures puede
no admitir ese permiso después.

Fuentes: [FAQ de Binance](https://www.binance.com/en/support/faq/detail/360002502072),
[seguridad Spot](https://developers.binance.com/en/docs/products/spot/rest-api#request-security),
[permisos de API](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/account#get-api-key-permission-user_data).
El resultado de consultar claves particulares permanece en los informes privados,
nunca en este repositorio.

## Limpieza y mantenimiento

Las notas históricas se conservaron por bytes y SHA256 en
[el archivo documental](docs/archive/before-0.10.59/INDEX.md). Los documentos de
entrada describen el estado vigente. Los datos financieros, claves, cohortes,
respaldos y agente independiente no se descartan por su nombre o antigüedad.
La limpieza de la instalación tiene manifiesto privado y no modifica estrategias
o límites. La correctiva59 elimina una carrera de heartbeat detectada por CI,
sin relajar la detección de regresiones de reloj.
