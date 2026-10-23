# Backend

Entrada Lambda: `ecommerce_agent.handler.lambda_handler`. Las dependencias AWS se construyen de forma diferida, únicamente en `MODE=aws` (predeterminado). `MODE=local` usa memoria y reglas, sin LLM ni AWS. Nunca hay fallback silencioso.

## Contrato HTTP

Todas las respuestas incluyen `request_id`. Éxito: `{ "ok": true, "data": {} }`. Error: `{ "ok": false, "error": { "code": "ACCESS_DENIED", "message": "..." } }`.

| Método y ruta | Entrada | data |
|---|---|---|
| GET /health | Disponible en handler local; no publicada en API Gateway | status |
| GET /api/me | Access token | sub, role |
| GET /api/orders/{id} | Access token | order, decision |
| POST /api/tools | action: read_order o request_return; order_id | order, decision, executed para mutaciones |
| POST /api/chat | message, máximo 2.000 caracteres | message fijo, results con resultados autorizados |
| POST /api/refunds/approve | order_id, expected_version entero, confirm: true | order, decision, executed |
| GET /api/audit | Solo supervisor | events, últimas 50 decisiones mediante Query descendente |

`order`: order_id, product, amount entero, currency CLP, status entregado, return_status NONE/REQUESTED/REFUNDED, version entero. El monto procede de DynamoDB; no se acepta del navegador. Los importes son ficticios; no existe integración de pagos.

La identidad solo se toma de `requestContext.authorizer.jwt.claims`: `sub`, `token_use=access`, `cognito:groups` customer/supervisor. API Gateway debe verificar emisor y audiencia; el backend rechaza JWT enviados solo por headers. No exponga una Lambda Function URL ni conceda invocación directa a usuarios finales.

Chat y `/api/tools` jamás aprueban reembolsos. La aprobación está en una ruta distinta y requiere un supervisor autenticado y confirmación explícita de un pedido y su versión. Repetir la misma versión ya aprobada no duplica efectos. El backend no puede demostrar por sí solo que hubo una persona frente al navegador: para producción agregar autenticación reforzada y un flujo de aprobación independiente según riesgo.

## Evidencia y persistencia

Cada lectura se audita antes de entregar datos. Las mutaciones usan una transacción DynamoDB que actualiza pedido y evidencia juntas, con condición de propietario, versión y estado. Una falla de auditoría interrumpe la operación. Los eventos incluyen actor_sub, role, action, order_id, decision, reason, executed, request_id, policy_version, created_at y expires_at; no incluyen prompts, tokens, productos ni montos. `actor_sub` es un identificador pseudónimo que igualmente requiere protección y retención limitada.

La tabla de auditoría usa partition key stream=DECISIONS y sort key event_id (fecha UTC y UUID). Query descendente y fuertemente consistente entrega las últimas 50 decisiones de la demo, sin Scan ni índice secundario. Esta partición única es adecuada para la demostración; para producción diseñar particiones por tenant y volumen, paginación y retención según necesidades de operación.

## Entorno

`ORDERS_TABLE`, `AUDIT_TABLE`, `BEDROCK_MODEL_ID`, `MODEL_REGION`, `AWS_REGION`, `AUDIT_TTL_DAYS` (30). `APP_NAME` queda disponible para infraestructura. El modelo usa Converse con herramientas de consulta y solicitud, y exactamente una propuesta por mensaje. Texto libre del modelo no se usa como evidencia ni como dato del pedido. Una salida desconocida o sin herramienta falla de forma cerrada.

## AgentCore Gateway opcional

Configurar **ambas** `AGENTCORE_GATEWAY_URL` y `AGENTCORE_MAC_KEY_ID` hace que chat ejecute herramientas por MCP/SigV4 `AWS_IAM`. Si Gateway falla, no hay ejecución directa de respaldo. Sin ambas variables, chat usa el backend directo de forma explícita. Las rutas directas continúan disponibles y aplican las mismas reglas de negocio.

Las herramientas se llaman `EcommerceTools___read_order` y `EcommerceTools___request_return`; el nombre del target debe ser `EcommerceTools`. El target Lambda privado es `ecommerce_agent.gateway_handler.lambda_handler`. Su esquema de entrada exige `order_id` y `context: {payload, mac}`. El payload contiene exactamente sub, role, action, order_id, request_id, expires_at y nonce. El backend lo crea después de verificar la identidad, lo firma con KMS `GenerateMac/HMAC_SHA_256` y lo envía directamente al Gateway: no pasa al modelo, navegador ni logs. El target usa `VerifyMac`, valida acción, pedido y expiración de 30 segundos, y recién entonces autoriza contra DynamoDB. Las dos funciones necesitan permisos KMS distintos. Las transacciones DynamoDB requieren las acciones sobre sus elementos (por ejemplo PutItem y ConditionCheckItem), no una acción IAM denominada TransactWriteItems.

El contexto se obtiene de `context.client_context.custom.bedrockAgentCoreToolName`, proporcionado por AgentCore. No se permite invocación directa pública al target. IAM y la política de Gateway deben restringir el caller al rol del backend y limitarlo a estas dos herramientas. El esquema no contiene ningún JWT. `nonce` aporta unicidad, pero no es una caché antirreplay: una capacidad firmada podría repetirse durante 30 segundos. Las devoluciones son idempotentes; nunca existe una herramienta de aprobación financiera. La aprobación humana permanece en el endpoint autenticado separado. Los eventos de decisiones del Gateway los escribe el target, sin duplicarlos en el backend.

El transporte usa MCP stateless 2026-07-28, con versión, método y nombre de herramienta en headers firmados y metadatos de protocolo en cada llamada; no requiere initialize. Bedrock: conexión de 2 segundos, lectura de 10 y sin reintentos. DynamoDB/KMS: conexión de 2 segundos, lectura de 3 y máximo un reintento. MCP: 8 segundos, sin redirecciones y respuesta máxima de 64 KiB. Cada mensaje propone una sola herramienta; propuestas múltiples se rechazan antes de ejecutar efectos.
