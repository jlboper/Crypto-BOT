# Preparación de migración — candidata 0.10.50

Esta entrega implementa diagnósticos de solo lectura y cálculos hipotéticos.
No implementa transporte de órdenes LIVE, autorización financiera, promoción,
veto de Guardian o reservas efectivas. Los transportes firmados existentes siguen
restringidos a Spot Testnet y Futures Demo. Pulse/Quant permanecen SHADOW.

## Contrato y propuesta de capital

`trader/live_preparation.py` evalúa cuatro motores a partir de la proyección
existente, sin importar clientes de exchange ni abrir ledgers. El endpoint
autenticado `/api/platform`, la app Windows y el portal remoto comparten el
panel plegable de System & Settings y el contrato `web/live-preparation.js`.
La proyección opcional es acotada y no contiene credenciales, identificadores
de cuenta u órdenes, contenido de noticias, preguntas o respuestas de modelos.
Un Worker anterior puede omitir sólo este campo en el reintento compatible.

Una propuesta privada opcional vive en `data/live-preparation/proposal.json`:
claves cerradas `schema:1` y `amount_usd` como texto decimal positivo. No es una
wallet, depósito, presupuesto de riesgo o autorización. El importe USD no se
convierte implícitamente a USDT ni se suma al capital observado. Archivo ausente
o inválido significa propuesta desconocida. Ningún GET crea o modifica archivos.
Los límites de pérdida y drawdown no se deducen de ese importe.

La CLI `scripts/audit_live_preparation.py --snapshot <dashboard.json>` evalúa un
JSON privado existente; permite `--proposal-file <propuesta.json>` o
`--proposed-capital-usd <importe>` explícitos. No inicia motores ni consulta APIs.
Los reportes y propuestas operativos quedan fuera de Git y del paquete firmado.

## Evidencia exigida y secuencia de transición

| Paso | Evidencia necesaria | Situación inicial |
|---|---|---|
| Cohortes por motor | Estrategia/configuración/IA/ejecución congeladas, tiempos, gaps, calidad, costes netos y episodios completos | Los spans históricos no la certifican |
| Revisión cuantitativa | Forward y fuera de muestra independientes; estabilidad por régimen, costes y sensibilidad; atribución IA separada | Replays/métodos presentes no demuestran ventaja |
| Cuenta | Identidad verificable, inventario completo, órdenes estándar/algo, fills, comisiones, funding y aportes/retiros | No certificada por un ledger local |
| Protocolo de capital | Reserva atómica→único envío→conciliación; parciales, incertidumbre, cancelaciones y recuperación | Laboratorio SIM; sin admisión de motores |
| Risk Engine | Límites explícitos aprobados, latches durables de pérdida, exposición y protección antes/después | Shadow; sin autoridad efectiva |
| Operación | Protección nativa, pérdida de red/IA/Guardian, reinicio, copia y recuperación firmada | Pruebas sintéticas y cortes no acreditan todo el ciclo LIVE |
| LIVE MICRO | Adaptador segregado revisado, claves dedicadas/permisos mínimos/retiros deshabilitados, límites y motores aprobados | No implementado ni activado por esta entrega |
| LIVE LIMITADO | Nueva revisión de evidencia obtenida en MICRO y autorización separada | Sin calendario automático |

No transferir fondos entre entornos ni convertir posiciones Testnet en posiciones
reales. No conectar varios motores al mismo capital hasta integrar y validar el
protocolo común. Las órdenes desconocidas retienen reservas hasta conciliación;
no liberar por timeout. Las salidas protectoras conservan independencia de IA,
Guardian y de esta pantalla. No aumentar riesgo para alcanzar mínimos de orden.

El cálculo `trader/migration_costs.py` comprueba escenarios numéricos explícitos
con Decimal: redondeo adverso, comisiones de ida/vuelta, deslizamiento, lotes,
capital y riesgo. Factibilidad matemática no valida todos los filtros Binance,
inventario, fills, comisiones en otros activos, liquidación, funding o protección.
No produce órdenes. El capital no utilizado permanece disponible en la hipótesis.

## Fuentes oficiales revisadas el21Oct2026

- [Spot Account](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account):
  identidad `uid`, balances libres/bloqueados y permisos; `canWithdraw` de la cuenta
  no acredita los permisos de una clave. No consultar producción sin una fase RO
  explícita y claves segregadas; no inferir cuenta por hash de API key.
- [USD-M Trade](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade):
  órdenes condicionales usan su familia algo; el inventario y reconciliación futuros
  deben incluirla. Dos patas siguen sin constituir ejecución atómica.
- [Binance API keys](https://www.binance.com/en/support/faq/detail/360002502072):
  revisar permisos e IP; mantener controles de seguridad, retiros deshabilitados
  y no reutilizar las claves Testnet para producción. No crear claves en esta entrega.

No hay servicio nuevo de pago ni llamadas adicionales a IA en este diagnóstico.
Los costes reales futuros dependen de la cuenta, activo, tamaño y ejecución;
la pantalla no presenta una tarifa universal o rentabilidad garantizada.
