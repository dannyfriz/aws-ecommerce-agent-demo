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
