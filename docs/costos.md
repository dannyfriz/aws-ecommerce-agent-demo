# Centro de costo y seguimiento diario

El centro acordado para la demo es `CostCenter=ecommerce-agent-demo`. Todos los providers AWS, incluido el alias de WAF en us-east-1, lo declaran en `default_tags`, junto con `Project=ecommerce-agent`, `Environment=demo` y `ManagedBy=Terraform`. La variable `cost_center` permite otro código; por defecto deriva de proyecto y ambiente. No duplicar tags globales en los recursos ni módulos.

El perfil de inferencia de aplicación `ecommerce-agent-demo-costs` permite atribuir el consumo de Bedrock Converse por tags, copiando el perfil geográfico US del mismo modelo. El backend invoca su ARN y mantiene permisos explícitos para el perfil fuente y los modelos regionales. Etiquetar solo Lambda no atribuye automáticamente el consumo del modelo. [Atribución en Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/cost-mgmt-application-inference-profiles.html).

## Activación de facturación

En AWS Organizations, usar un perfil autorizado de la cuenta administradora de facturación. Abrir Billing and Cost Management → Cost allocation tags → User-defined tags y activar `CostCenter`, `Project` y `Environment`. Los tags deben aparecer primero y la activación/datos pueden tardar hasta 24 horas por etapa. No son costos en tiempo real. [Tags de asignación de costos](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/custom-tags.html).

Con un perfil autorizado de esa cuenta se puede usar el script, que activa únicamente esas tres claves y valida que sea la cuenta administradora:

```powershell
& ".\scripts\Activate-CostTags.ps1" -Profile PERFIL_FACTURACION
```

El script exige pertenecer a una organización y valida la cuenta administradora antes de modificar las claves. En una cuenta independiente, revisar la activación desde Billing con los permisos correspondientes. El etiquetado técnico no acredita que la asignación de costos esté activa.

## Reporte diario

```powershell
& ".\scripts\Report-DailyCosts.ps1" -Profile TU_PERFIL -CostCenter ecommerce-agent-demo
```

El reporte usa los últimos siete días completos UTC; `-Start` y `-End` admiten fechas ISO, con fecha final exclusiva. Filtra simultáneamente por `CostCenter` y la cuenta de la demo, usa `UnblendedCost`, granularidad `DAILY` y desglose `SERVICE`. Guarda `.build/costs/daily-costs.json`, excluido de Git. Marca resultados estimados y no interpreta tags o datos faltantes como costo cero. Las consultas de Cost Explorer tienen cargo por API según su [tarifa vigente](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/); el script es manual y no crea una tarea periódica.

No se atribuyen automáticamente consumos anteriores al etiquetado/activación. Revisar créditos, impuestos, descuentos y cargos no etiquetados por separado antes de comparar con la factura total. El costo no etiquetado de toda la cuenta no representa el costo exclusivo de la demo.

## Cobertura y excepciones

Para comprobar la cobertura, contrastar los recursos administrados con el schema del provider y los tags efectivos del state. Mantener cualquier reporte operativo fuera de Git. Resource Groups Tagging API por sí sola no demuestra cobertura total.

- Recursos principales etiquetables: buckets S3, claves KMS, tablas DynamoDB, funciones Lambda, roles IAM, grupos de logs, pool Cognito, distribución CloudFront propia, WAF, API Gateway API/stage/domain, perfiles Bedrock y recursos AgentCore que lo admiten.
- Configuraciones subordinadas sin tags propios: aliases/policies KMS, políticas y cifrado de buckets, políticas IAM inline, permisos Lambda, rutas/integraciones/mappings API, grupos/clientes/dominios Cognito y políticas auxiliares CloudFront. Su consumo debe revisarse en las líneas del servicio correspondiente, sin inventar tags donde AWS no los admite.
- La distribución de autenticación es administrada por Cognito, no por este Terraform. No se modifica directamente para etiquetarla.
- Un certificado ACM existente queda fuera de la administración de este Terraform; si es compartido, evaluar sus usos antes de asignarlo exclusivamente al proyecto.
- La zona Route 53 se administra fuera de estas capas y puede ser compartida. Los registros DNS individuales no admiten tags de costo; no atribuir el costo completo de una zona compartida al laboratorio. Su parte debe imputarse por separado según el criterio acordado. [Tags de Route 53](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/tagging-resources.html).

Un reporte filtrado por tags es el costo atribuible disponible, no una garantía de capturar todos los gastos compartidos o cargos que el servicio no etiqueta.

## Consumo de las seis mejoras del asistente

Las cuatro capacidades de infraestructura son opcionales y parten deshabilitadas: `enable_conversation_memory`, `enable_preference_memory`, `enable_content_guardrails` y `enable_policy_knowledge`. Activarlas en variables privadas del ambiente agrega consumo. Las aclaraciones no crean otro servicio; las evaluaciones se ejecutan manualmente y no configuran evaluación continua del tráfico de la demo.

| Componente | Consumo que debe observarse | Límite aplicado |
|---|---|---|
| Contexto de sesión | Escrituras y lecturas de eventos de AgentCore Memory; llamadas KMS y paginación | Datos mínimos, uso lógico durante 900 segundos, retención física de eventos de 7 días |
| Preferencias entre sesiones | Lectura y escritura directa de registros de largo plazo y almacenamiento | Solo idioma/detalle, actualización del registro existente y TTL de 31 días |
| Guardrails | Unidades de texto y políticas evaluadas por `ApplyGuardrail` | Entrada del flujo de interpretación y salida de extractos de políticas; no se ejecuta sobre todo el tráfico HTTP |
| Knowledge Bases | Embeddings Titan V2 para ingestión y búsquedas; solicitudes y almacenamiento S3/S3 Vectors; KMS | Un documento ficticio, vectores de 1.024 dimensiones y hasta tres fragmentos por consulta |
| Evaluación `-Live` | Tokens del modelo real mediante el perfil de aplicación | Dataset ficticio explícito; pedidos y memoria de prueba locales |
| Evaluación `-Managed` | Inferencia del agente y cargo de AgentCore Evaluations | Casos ficticios seleccionados, spans en RAM; sin captura continua de sesiones desplegadas |

No hay una inferencia adicional para extraer recuerdos o preferencias: el contexto usa `extractionMode=SKIP` y las preferencias se escriben como registros tipados. La respuesta de políticas usa `Retrieve` y extractos literales; no agrega una llamada a un modelo generativo para redactarlos. Esto no elimina los cargos de embeddings, recuperación, almacenamiento o filtro de contenido.

El perfil de aplicación actual atribuye la inferencia conversacional que lo invoca. No asumir que sus tags cubren automáticamente embeddings Titan, Guardrails, almacenamiento vectorial, memoria o evaluadores incorporados. Comparar las líneas por servicio, los tags disponibles y los cargos sin atribuir del mismo período; documentar por separado lo que Billing no permita asignar. El etiquetado técnico de los recursos nuevos tampoco activa por sí solo sus claves en Billing.

Guardrails usa `STANDARD` con el perfil administrado `us.guardrail.v1:0`. AWS indica que la inferencia entre regiones no agrega un cargo adicional; siguen aplicándose las tarifas de las políticas evaluadas. El perfil US distribuye solicitudes de `us-east-1` entre `us-east-1`, `us-east-2` y `us-west-2`; revisar esas regiones al conciliar consumo. Este perfil administrado es distinto del perfil de aplicación que atribuye la inferencia conversacional y no se crea como un recurso propio con tags del proyecto. [Inferencia entre regiones de Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region.html).

Revisar las tarifas vigentes de [AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/), [Bedrock y Guardrails](https://aws.amazon.com/bedrock/pricing/) y [S3/S3 Vectors](https://aws.amazon.com/s3/pricing/). Eliminar del contexto una referencia vencida o comenzar otra conversación no elimina su almacenamiento físico de inmediato; no debe contabilizarse como costo cero. Diseño y retenciones en [memoria-y-conocimiento.md](memoria-y-conocimiento.md).
