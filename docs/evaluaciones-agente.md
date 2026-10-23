# Evaluaciones reproducibles del agente

El laboratorio incorpora escenarios ficticios para comprobar comprensión de la solicitud, selección de acción, preguntas de aclaración, uso del contexto y autorización. El dataset está en [agent-evaluation-cases.json](../scripts/fixtures/agent-evaluation-cases.json). Cada escenario usa pedidos y auditoría nuevos en memoria; nunca consulta ni modifica las tablas del ambiente desplegado.

## Ejecución local

`& ".\scripts\Evaluate-Agent.ps1"`

Este modo usa `LocalPlanner`, `MemoryRepository` y `LocalConversationMemory`, sin credenciales ni llamadas AWS. Es una regresión determinista del contrato y las reglas, apropiada para CI. Un resultado local aprobado no demuestra que un modelo real interprete correctamente todos los mensajes.

El reporte se guarda en `.build/agent-evaluation-results.json`. Cada métrica informa casos aprobados, total y tasa entre 0 y 1. Una métrica se aprueba por escenario completo, incluidos todos sus turnos y la prohibición de aprobar reembolsos por chat. El proceso devuelve 0 al aprobar, 1 ante expectativas incumplidas y 2 ante errores de configuración. Las comparaciones usan campos estructurados y estados, sin evaluar por coincidencias de frases.

## Evaluación con Bedrock real y datos aislados

`& ".\scripts\Evaluate-Agent.ps1" -Live -Profile default -Region us-east-1`

`-Live` sustituye únicamente el planificador por `BedrockPlanner`. Recupera el ARN del perfil de aplicación de `.build/outputs/compute.json`; `-ComputeOutputs` permite indicar otra ubicación y `-ModelId` acepta explícitamente otro ARN de perfil de aplicación en la región seleccionada. El perfil permite atribuir el costo de inferencia. Se necesitan permisos de invocación del modelo. Las inferencias generan costo y pueden variar entre ejecuciones, incluso con temperatura cero.

Los datos de pedido, auditoría y memoria conversacional permanecen en el proceso local. Este modo comprueba interpretación con el modelo y reglas locales; **no demuestra** el funcionamiento de Cognito, API Gateway, AgentCore Memory administrado, Gateway, Policy ni DynamoDB. El ejecutor es local por diseño y solo pertenece a este script de evaluación; no cambia el modo de ejecución de la aplicación desplegada.

## Escenarios y límites

- Consulta y solicitud de devolución de un pedido propio.
- Pregunta por el identificador faltante y continuación de la acción pendiente.
- Referencia a un pedido mencionado en el turno anterior.
- Separación de usuarios que reutilizan el mismo identificador de sesión y separación entre sesiones.
- Rechazo de pedidos ajenos e inexistentes con la misma categoría pública.
- Rechazo de elevar el perfil mediante texto y de aprobar un reembolso como cliente.
- Preparación de revisión para supervisión sin aprobar ni modificar el pedido.
- Rechazo de solicitudes de devolución realizadas por supervisión sobre pedidos de clientes.
- Aclaración ante dos pedidos o una intención no reconocida.

Los mensajes y las respuestas libres no se imprimen ni se guardan en el reporte. Se exportan identificadores ficticios de caso, expectativas estructuradas, acción normalizada, estado, verificaciones y un identificador de solicitud sintético. El modo real envía a Bedrock los mensajes ficticios del dataset y el contexto mínimo requerido; no carga conversaciones de usuarios reales. Los errores de dependencias se convierten en una categoría controlada para evitar registrar contenido arbitrario del proveedor.

Esta suite complementa las pruebas de autorización existentes. No reemplaza las verificaciones autenticadas del ambiente, una revisión de permisos IAM, las pruebas del adaptador AgentCore Memory ni una medición estadística representativa: un dataset pequeño aprobado no garantiza ausencia de errores.

## Evaluación administrada con AgentCore Evaluations

Los modos anteriores son evaluaciones reproducibles propias. El modo opcional `-Managed` incorpora además el servicio administrado mediante `scripts/evaluate_agent_managed.py`:

`& ".\scripts\Evaluate-Agent.ps1" -Managed -Profile default -CaseId customer_reads_own_order,customer_requests_return`

Este modo siempre invoca Bedrock real y acepta exclusivamente casos del dataset ficticio versionado. Una instrumentación manual observa las llamadas que realmente ocurren: `Service.chat`, la ejecución local de herramientas y `Converse`. Registra sus tiempos, vínculos y contenido ficticio en spans OpenTelemetry bajo el scope propio `opentelemetry.instrumentation.tienda_clara`. No inventa ejecuciones ni declara utilizar Strands. El esquema sigue el [soporte genérico de frameworks](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-generic.html).

Los spans permanecen en RAM y se envían directamente a la API oficial `Evaluate` como `evaluationInput.sessionSpans`; `inlineSpans` no es el nombre del campo. No se escriben archivos con prompts, trazas ni respuestas completas, ni se habilitan logs conversacionales o CloudWatch Transaction Search. Esta invocación directa no configura evaluación continua del ambiente desplegado. [Referencia de Evaluate](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_Evaluate.html) y [tipo EvaluationInput](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_EvaluationInput.html).

Se requiere el permiso adicional `bedrock-agentcore:Evaluate` y disponibilidad regional del servicio. Boto3 ya proporciona la API; no se incorpora otro SDK. Se generan costos de inferencia y del evaluador. El evaluador predeterminado es `Builtin.ToolSelectionAccuracy`, con umbral 0,8. Los turnos que no ejecutaron herramientas no son evaluables para selección y se marcan como `NO_TOOL_CALLS`; sus reglas siguen siendo verificadas por la regresión determinista. Una respuesta vacía, parcial con errores, no numérica o sin puntuaciones falla el proceso. `-Evaluator Builtin.Helpfulness` y `-Evaluator Builtin.Correctness` permiten evaluar otras dimensiones; no constituyen pruebas deterministas de permisos ni una referencia de verdad independiente.

El reporte `.build/agent-managed-evaluation-results.json` contiene la regresión y puntuaciones sanitizadas. No exporta explicaciones libres del juez ni detalles de errores del proveedor. Los mensajes ficticios sí se envían al servicio evaluador para que pueda calificarlos; nunca se cargan conversaciones de producción. La puntuación del juez puede variar y no sustituye el gate de autorización implementado mediante código. La disponibilidad y el formato deben verificarse con una ejecución real antes de presentar esta integración como operativa en una cuenta. [Inicio de evaluación bajo demanda](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html).

## Seis mejoras verificadas el 23 de octubre de 2026

La regresión aislada con Bedrock real aprobó los 15 escenarios. El evaluador administrado `Builtin.ToolSelectionAccuracy` devolvió 1,0 para la consulta de un pedido propio y para ambos turnos de consulta seguida de devolución. No se habilitó evaluación continua ni exportación de conversaciones de usuarios.

Además, una prueba independiente del ambiente desplegado aprobó 25 verificaciones con OAuth real de cliente y supervisión: memoria, aclaraciones, aislamiento, Guardrails, políticas con fuente y preferencias entre sesiones. Los datos de los pedidos de la actividad permanecieron iguales. La suite local aprobó 211 pruebas Python, siete suites de navegador y 22 pruebas Terraform simuladas. Estos resultados documentan casos concretos y no prueban exactitud general ni sustituyen las reglas de autorización.
