# ADR-001: contexto confiable entre orquestador y herramientas

**Estado:** decisión implementada en código y Terraform; pendiente validación de despliegue de extremo a extremo en AWS.

## Problema

El backend conoce al usuario mediante claims validados por API Gateway, pero AgentCore Gateway usa AWS_IAM para autenticar a la carga de trabajo que lo invoca. No se puede suponer que el JWT del usuario llegue al target. Tampoco se puede usar como identidad un `actor_sub` incluido entre argumentos que propone el modelo: cualquier prompt podría modificarlo.

## Decisión

Después de recibir la propuesta de herramienta y validar su contrato, el orquestador construye un contexto desde la identidad confiable de la solicitud. Vincula actor, rol, acción, pedido, request ID y vencimiento máximo de 30 segundos. Usa una clave KMS HMAC_SHA_256 para generar su MAC. La clave HMAC es independiente de las CMK de cifrado.

El contexto firmado se agrega después de la inferencia: el modelo no ve ni firma claims, JWT, MAC o material criptográfico. El orquestador firma únicamente la identidad que recibió por el camino autenticado; no copia roles o sujetos indicados por el modelo o el navegador.

Gateway aplica AWS_IAM y Policy ENFORCE a la carga de trabajo y a la herramienta. La Lambda target verifica el MAC con KMS y comprueba plazo, binding de acción/pedido y reglas de negocio. No asigna permisos por el mero hecho de recibir una invocación de Gateway.

## Separación de permisos

- Orquestador: `kms:GenerateMac`; no requiere leer ni exportar la clave HMAC.
- Target: `kms:VerifyMac`; no puede producir contextos nuevos con GenerateMac.
- Gateway: invocar únicamente el target configurado.
- IAM/Policy: autorizar únicamente al workload esperado y las herramientas `read_order`/`request_return`.
- Backend humano: aprobar con supervisor, confirmación y versión; sin herramienta de reembolso en el chat.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Confiar en claims enviados por el modelo | El modelo es una fuente no confiable; permite suplantación |
| Poner el JWT en el prompt | Expone un bearer token y no garantiza que la herramienta lo valide |
| Suponer propagación automática del JWT | La autenticación IAM del workload no equivale a identidad del usuario |
| Guardar un secreto HMAC en variables de entorno | Aumenta distribución de material secreto; KMS permite separar generar y verificar sin exportarlo |
| Permitir cualquier herramienta y filtrar en el prompt | El prompt no es una frontera de autorización |

## Consecuencias y límites

Se añaden llamadas KMS y latencia; el plazo breve puede fallar con demoras o relojes incorrectos. El target falla de manera cerrada: se genera una nueva solicitud, no se amplía el vencimiento de un contexto recibido. Firmar contexto no elimina replay por sí solo: limitar el plazo y conservar idempotencia/controles condicionales en las mutaciones. Las consultas repetidas dentro del plazo pueden volver a ejecutarse; no se promete unicidad criptográfica de ejecución.

Un orquestador comprometido con permiso GenerateMac puede emitir contexto confiable: proteger ese rol, código y despliegue sigue siendo esencial. HMAC no sustituye logs, revisión de permisos ni control de cambios. Una CMK de cifrado no sirve automáticamente como clave HMAC: se usan tipo, algoritmo y políticas específicos.

## Validación necesaria

Pruebas de MAC alterado, expiración, plazo excesivo, cambio de acción/pedido, rechazo de herramienta desconocida, autorización por propietario y reintentos sin duplicación. Después del despliegue, verificar además IAM del caller, modo ENFORCE de Policy, acceso KMS real y evidencia correlacionada. No afirmar validación AWS solo porque pasan las pruebas con adaptadores locales.
