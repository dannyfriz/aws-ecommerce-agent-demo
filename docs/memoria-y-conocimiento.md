# Memoria, conocimiento y evaluación del asistente

Estas seis mejoras ayudan al asistente a seguir una conversación y explicar sus respuestas. La identidad sigue viniendo de Cognito; los permisos AWS, de IAM y AgentCore Gateway; la propiedad y el estado del pedido, de las reglas del servidor y DynamoDB. Ninguna memoria, política recuperada o puntuación del modelo concede acceso ni aprueba reembolsos.

| Mejora | Ejemplo para la actividad | Componente |
|---|---|---|
| Contexto durante la conversación | «Consulta P-104» → «Quiero devolverlo» | AgentCore Memory de corto plazo |
| Preguntas de aclaración | «Quiero una devolución» → «¿De qué pedido?» | Contrato del planificador y validación del servidor |
| Evaluaciones reproducibles | Comprobar selección de acciones, aclaraciones y aislamiento | Suite local, Bedrock real y AgentCore Evaluations |
| Consulta de políticas | «¿Quién puede aprobar un reembolso?» con fuente visible | Knowledge Bases, Titan Text Embeddings V2 y S3 Vectors |
| Filtro de contenido | Bloquear ciertos datos sensibles o ataques al prompt | Bedrock Guardrails mediante `ApplyGuardrail` |
| Preferencias entre sesiones | Elegir respuestas breves o detalladas | Registros tipados de largo plazo en otra AgentCore Memory |

## Contexto mínimo de sesión

El navegador mantiene un UUIDv4 de conversación en memoria. El backend combina ese UUID con un identificador derivado del ambiente y del hash SHA-256 del `sub` autenticado. No acepta el usuario o perfil declarado en el mensaje como identidad. Dos usuarios que envíen el mismo UUID conservan contextos separados; otra conversación del mismo usuario también queda separada.

Solo se guarda el identificador de un pedido al que el servidor ya permitió acceder y, cuando corresponde, una intención pendiente normalizada: `read_order` o `request_return`. También se conserva la vigencia técnica del registro. No se almacenan prompts, respuestas libres, contraseñas, tokens, roles, permisos, propietarios, montos ni estados del pedido. `CreateEvent` usa `extractionMode=SKIP`: estos eventos no alimentan extracción automática de largo plazo.

El contexto vence lógicamente a los **900 segundos**. Los eventos tienen una retención física de **7 días**, mínimo admitido por el provider usado. Vencer a los 15 minutos significa que la aplicación deja de utilizar el contexto; no significa que AWS haya eliminado el evento. Una referencia recordada solo ayuda a interpretar el mensaje: cada consulta o cambio vuelve a comprobar la sesión, la propiedad y el estado vigente en DynamoDB. [Memoria de corto plazo](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/short-term-create-event.html) y [retención del recurso Terraform](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_memory).

«Nueva conversación» cambia el UUID y limpia el chat visible. No elimina eventos remotos, preferencias, auditoría ni pedidos. Cerrar sesión también abandona la conversación del navegador. Estas opciones no deben presentarse como una eliminación de datos en AWS.

Si falla la lectura del contexto, se rechaza la solicitud antes de ejecutar una acción. Si una acción ya terminó y luego falla el guardado del contexto, se conserva su resultado confirmado, se devuelve `memory_warning` y se cambia el UUID. La interfaz avisa que se debe indicar nuevamente el pedido; no informa que la devolución falló ni la ejecuta de nuevo automáticamente. Un error de autorización deja una marca de contexto vacío para evitar reutilizar una referencia anterior.

## Preferencias explícitas entre sesiones

El selector guarda únicamente `preferred_detail=brief|detailed` y `language=es`, con versión y fechas técnicas. La preferencia se escribe directamente con `BatchCreateMemoryRecords` o se reemplaza con `BatchUpdateMemoryRecords`; no se infiere analizando conversaciones. Se usa una memoria distinta y un namespace exacto derivado del usuario autenticado. Las rutas `GET /api/preferences` y `POST /api/preferences` requieren la sesión y el perfil admitido.

Los registros reciben un TTL físico de **31 días**, mínimo del servicio para largo plazo; la aplicación también ignora preferencias vencidas aunque AWS todavía las esté eliminando. No hay una eliminación inmediata al cambiar de conversación. El estilo predeterminado es breve cuando no existe una preferencia vigente. Elegir «detalladas» cambia la explicación y la cantidad de extractos de políticas, sin cambiar los permisos ni los datos disponibles. [Retención de largo plazo](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-record-ttl.html).

El índice de `ListMemoryRecords` puede devolver contenido anterior después de una actualización. Por eso se usa únicamente para descubrir identificadores dentro del namespace exacto; el contenido vigente se lee con `GetMemoryRecord`, enviando también ese namespace y comprobando el identificador devuelto. No se interpreta el contenido del resumen eventual ni se usa como fallback si falla la lectura por ID.

La primera escritura también puede tardar en aparecer en el índice de descubrimiento. Después del acuse, el backend intenta confirmar el ID y valor exactos mediante `GetMemoryRecord` y que ese ID sea descubrible mediante `ListMemoryRecords`, con un presupuesto de espera de dos segundos. No usa un caché ni repite la escritura. Si todavía no puede confirmar ambas condiciones, devuelve `PREFERENCES_PENDING`: la escritura fue aceptada, pero el nuevo valor aún no está confirmado como disponible para otra sesión. Este resultado no promete que el estilo ya cambió. Esperar unos segundos y repetir `GET /api/preferences` permite verificarlo; no hace falta volver a enviar el cambio automáticamente.

## Aclarar antes de actuar

El planificador puede proponer una aclaración en lugar de una herramienta de negocio. El servidor valida su estructura y registra `decision=CLARIFY`, `action=chat:clarify` y `executed=false`. Esta decisión indica que falta información; no es un `DENY` ni un error de Bedrock.

| Motivo | Comportamiento |
|---|---|
| `MISSING_ORDER` | Preguntar por un único número de pedido y conservar una intención permitida pendiente. |
| `AMBIGUOUS_ORDER` | Pedir elegir un pedido cuando se mencionaron varios. |
| `UNKNOWN_INTENT` | Preguntar si se quiere consultar o solicitar una devolución. |

Una aclaración no ejecuta Gateway ni modifica el pedido. La supervisión conserva mensajes propios: puede consultar pedidos de clientes y preparar una revisión, pero no solicitar la devolución por el propietario ni aprobar desde el chat. `MODEL_INVALID_RESPONSE` queda reservado para una respuesta del modelo cuyo contrato no puede validarse.

## Políticas con una fuente verificable

La fuente versionada es [politicas-posventa-demo.md](politicas-posventa-demo.md), una política ficticia y compartible. Terraform la publica en un bucket S3 privado cifrado con KMS. Knowledge Bases divide el documento en fragmentos y usa **Amazon Titan Text Embeddings V2**, con vectores de **1.024 dimensiones**, para representarlos numéricamente. **S3 Vectors** guarda esos vectores y permite encontrar fragmentos relacionados con una pregunta. Esta técnica de recuperación de contexto es parte de RAG.

Cuando la intención corresponde a políticas, el backend llama a `Retrieve`, admite hasta tres resultados y verifica que su URI corresponda exactamente al documento configurado. Devuelve extractos literales y una cita; no llama a `RetrieveAndGenerate` ni genera condiciones comerciales nuevas. La API entrega el título y URI de la fuente; la interfaz muestra su título. La opción breve usa un extracto completo y la detallada permite hasta tres, sin cortar una regla a la mitad.

La base no contiene pedidos, correos ni datos privados. Una política explica el funcionamiento del laboratorio; no acredita la propiedad, la elegibilidad individual, una aprobación ni una fecha de pago. Si no se encuentra información, se informa que no hay una condición documentada. Actualizar el archivo requiere además ejecutar y comprobar la ingestión de Knowledge Bases antes de probar su contenido. [Funcionamiento de Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html).

## Guardrails y sus límites

La ruta de interpretación aplica `ApplyGuardrail` al mensaje antes de enviarlo al modelo. La respuesta con extractos de políticas también se revisa con `source=OUTPUT` antes de devolverla. Se usa una versión publicada del guardrail y controles de información sensible y ataques al prompt. Las solicitudes explícitas de aprobación conservan primero su ruta determinista de rechazo o preparación de revisión.

El filtro de ataques usa el nivel `STANDARD`, que exige inferencia entre regiones. Desde `us-east-1` se configura el perfil administrado `us.guardrail.v1:0`; AWS puede evaluar el contenido en `us-east-1`, `us-east-2` o `us-west-2`. La configuración permanece en la región de origen, con la CMK del laboratorio. El rol del backend puede ejecutar únicamente `ApplyGuardrail` sobre este guardrail y los tres ARN explícitos del perfil. No recibe permisos para crear o cambiar filtros. El SDK fijado expone `crossRegionConfig.guardrailProfileIdentifier` y no incluye operaciones `ListGuardrailProfiles` o `GetGuardrailProfile`; el identificador y los destinos se contrastaron con la documentación oficial. [Regiones y perfil US](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html), [permisos de inferencia](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrail-profiles-permissions.html).

El filtro de contenido no valida los argumentos de las herramientas, el propietario ni el rol. Tampoco cubre las llamadas directas a los endpoints de negocio: estos conservan sus controles de autorización. Una cadena que pase Guardrails puede seguir siendo rechazada por la aplicación. El contexto HMAC y la aprobación humana permanecen separados. [ApplyGuardrail](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html).

`CONTENT_BLOCKED` identifica una intervención del filtro; `MEMORY_UNAVAILABLE` y `PREFERENCES_UNAVAILABLE`, fallas explícitas de persistencia; `KNOWLEDGE_INVALID_RESPONSE`, una fuente o respuesta recuperada que no pudo validarse. Estos resultados se distinguen de `ACCESS_DENIED` y de una aclaración para explicar a los estudiantes qué control intervino.

## Evaluaciones sin conversaciones de producción

La [guía de evaluaciones](evaluaciones-agente.md) distingue tres modos. La regresión local usa datos y adaptadores en RAM; `-Live` sustituye el planificador por Bedrock real; `-Managed` envía al servicio AgentCore Evaluations spans de las llamadas realizadas sobre el mismo dataset ficticio. Los dos últimos generan consumo AWS. Ninguno utiliza las tablas desplegadas para sus pedidos de prueba.

Los spans del modo administrado permanecen en RAM y se envían con `Evaluate`: no se habilitan logs conversacionales de producción ni CloudWatch Transaction Search. Los reportes contienen verificaciones y puntuaciones sanitizadas. Una puntuación del evaluador es una señal de calidad; las reglas de identidad y autorización se comprueban con aserciones deterministas. Una ejecución local no acredita que la integración AWS completa funcione.

## Activación y verificación

Las cuatro capacidades de infraestructura son opcionales y tienen valor `false` por defecto: `enable_conversation_memory`, `enable_preference_memory`, `enable_content_guardrails` y `enable_policy_knowledge`. Se activan explícitamente en el archivo privado de variables del ambiente. Ese archivo, los IDs obtenidos y los outputs de despliegue no se versionan. Las aclaraciones y las evaluaciones forman parte del código y no requieren otro flag Terraform.

Revisar el plan, ejecutar las pruebas y el gate de seguridad, desplegar las capas afectadas y completar la ingestión de políticas. Después comprobar autenticadamente: continuación de pedido, aclaración sin efectos, aislamiento entre usuarios, cambio de UUID, preferencia persistente, bloqueo de contenido, fuente de políticas y rechazo de operaciones no autorizadas. La evidencia de un despliegue concreto corresponde a [despliegue-demo.md](operacion.md), no a la sola existencia de estos recursos en el código.

La atribución de consumo y sus excepciones se describen en [costos.md](costos.md); las fronteras de confianza, en [seguridad.md](seguridad.md).
