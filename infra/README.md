# Infraestructura del laboratorio

Orden: `bootstrap` → `foundation` → `data` → `compute`.

Cada capa de aplicación mantiene un state independiente en S3. `data` consume outputs de `foundation`; `compute` consume ambos mediante `terraform_remote_state`. Los accesos a estos states deben limitarse al operador de despliegue. Los outputs no incluyen contraseñas ni tokens, pero el state sigue siendo información sensible.

Las claves de states dependientes se derivan de `environment`; por ejemplo, `dev` consume `dev/foundation/terraform.tfstate` y `dev/data/terraform.tfstate`. Si se proporciona una clave explícita, una precondición exige que comience con el mismo ambiente. No se admite conectar `dev` a los states de `demo` por accidente.

## Contrato de despliegue

- Terraform `>= 1.17.0, < 2` y AWS provider `>= 6.70.0, < 7`. Se verificaron como versiones estables vigentes el 22 de octubre de 2026; los cuatro lockfiles fijan AWS `6.70.0` con checksums oficiales para Windows y Linux.
- Ambas Lambdas usan Python `3.14` sobre Amazon Linux 2023 y ARM64: es el último runtime Python con disponibilidad general en Lambda al preparar esta entrega. Python `3.15.1` es estable como lenguaje, pero el runtime Lambda `python3.15` sigue en public preview y se excluye del despliegue estable. La toolchain de referencia es Python `3.14.9`; AWS administra el parche concreto del runtime `python3.14`, que no se fija desde Terraform. CI comprueba también Python `3.15.1` como prueba adicional de compatibilidad.
- Autenticación con credenciales temporales del operador, preferentemente AWS IAM Identity Center. No se crean usuarios IAM ni access keys.
- `expected_account_id` impide ejecutar el provider en otra cuenta por error. Solo se admiten `demo`, `dev` y `test` como ambientes.
- Copiar los archivos `.example` a archivos locales sin publicar sus valores. El backend se configura con `backend.hcl`, separado de `terraform.tfvars`.
- Ejecutar el empaquetado antes de planificar `compute`: debe existir `.build/backend.zip` en la raíz del repositorio.
- Los scripts del repositorio coordinan los comandos; no se aplica infraestructura automáticamente desde GitHub Actions.

## Bootstrap

El primer state de `bootstrap` es local. Protegerlo fuera de Git y conservarlo en almacenamiento seguro. Después de crear el bucket, puede migrarse a una clave independiente dentro del mismo bucket agregando un backend S3 y ejecutando una migración explícita. No mezclarlo con las claves de las otras capas. El bucket usa versionado, KMS, bloqueo público y `prevent_destroy`; no se elimina con el laboratorio.

S3 utiliza `use_lockfile = true`. No se crea una tabla DynamoDB para locks, mecanismo que está deprecado para este backend.

## Decisiones de seguridad

- CloudFront accede al bucket privado mediante OAC y firma SigV4. Los objetos usan SSE-KMS; las políticas KMS y S3 permiten únicamente la distribución de este proyecto.
- CloudFront tiene un Web ACL obligatorio de AWS WAFv2 en `us-east-1`, con `AWSManagedRulesCommonRuleSet` y bloqueo al superar aproximadamente 2.000 solicitudes por IP en cinco minutos. El umbral contempla asistentes que comparten NAT; los límites de WAF son estimados. Se publican métricas, sin muestras de solicitudes ni logging de cuerpos. Este WAF protege el frontend, no el endpoint independiente de HTTP API. WAF tiene cargos adicionales y sus reglas administradas requieren revisar posibles falsos positivos.
- El frontend utiliza HTTPS, CSP, HSTS y respuestas sin caché para evitar una configuración pública desactualizada durante la demo.
- **Limitación del dominio predeterminado:** AWS impone la política TLSv1 al certificado `*.cloudfront.net`, aunque los navegadores modernos negocien TLS 1.2/1.3. Con dominio propio se usa la política estable actual `TLSv1.3_2025`, que exige TLS 1.3: configurar juntos `frontend_domain_name` y `acm_certificate_arn` (certificado validado en `us-east-1`) y crear el alias DNS hacia la distribución. Clientes antiguos sin TLS 1.3 no podrán conectarse a esa variante. No se afirma que el modo predeterminado cumpla un estándar de producción.
- Cognito no permite autorregistro. Los grupos son `customer` y `supervisor`. La SPA usa Authorization Code y PKCE implementado en el navegador; no existe client secret. Access e ID tokens duran 15 minutos; el refresh token dura 60 minutos y puede revocarse. Los tokens emitidos pueden seguir válidos hasta expirar: deshabilitar un usuario no equivale a invalidación instantánea de todos los JWT en API Gateway.
- MFA está desactivado para facilitar el laboratorio con usuarios ficticios. Para datos reales, aplicar MFA y políticas de autenticación de la organización antes de habilitar el servicio.
- Las rutas de negocio requieren JWT y el scope del recurso. `GET /api/health` es público y devuelve únicamente `status: ok`; no consulta pedidos ni invoca Bedrock o AgentCore. Los grupos, la propiedad de cada pedido y la separación de funciones se comprueban en el backend, no en IAM ni en el prompt.
- La Lambda tiene credenciales temporales de su execution role. Su política limita DynamoDB a dos tablas, Bedrock a ARN explícitos y la invocación de AgentCore a un único Gateway. No existe `AdministratorAccess` ni function URL.
- Logs de API y Lambda usan CMK y retención de siete días. El access log excluye tokens, cabeceras, cuerpos y query strings. La auditoría de decisiones vive en DynamoDB con TTL y PITR.
- La auditoría usa partición `stream` y ordenación `event_id`: permite consultar las 50 decisiones más recientes mediante `Query` descendente con lectura consistente, sin depender del orden de un `Scan`. El valor del stream de esta demo es `DECISIONS`.
- Throttling de API y concurrencia reservada limitan la velocidad; no son un límite monetario. Configurar AWS Budgets y retirar el laboratorio cuando termine el evento.

## AgentCore y propagación explícita de identidad

`compute` habilita `enable_agentcore = true` por defecto. Crea Gateway MCP con `AWS_IAM`, Policy Engine cifrado con CMK y modo `ENFORCE`. Cedar permite únicamente al execution role del backend llamar `EcommerceTools___read_order` y `EcommerceTools___request_return` en ese Gateway. No se publica una herramienta para aprobar reembolsos. La aprobación humana usa la ruta de API autenticada, con comprobaciones del caso de uso.

El cliente y Gateway usan MCP `2026-07-28` en modo stateless. La versión se configura explícitamente y una prueba verifica su coherencia. No se habilita logging detallado de cuerpos de Gateway: el contexto firmado y su MAC no deben copiarse a logs de diagnóstico.

Gateway autentica la carga de trabajo. La identidad del cliente no se transmite automáticamente por esa configuración: el backend toma los claims JWT ya verificados, crea un contexto con acción, pedido y vencimiento breve, y obtiene un MAC mediante KMS. La Lambda de herramientas verifica ese MAC antes de aplicar propiedad y reglas de negocio. El backend tiene `GenerateMac`; la herramienta tiene `VerifyMac`. Ninguno obtiene el material de la clave HMAC. La clave HMAC no admite rotación automática: una rotación consiste en crear una clave nueva y actualizar ambas funciones de forma controlada.

La política del rol de Gateway debe autorizar tanto el Policy Engine como el propio Gateway. Como AWS asigna el sufijo del Gateway durante su creación y necesita permisos antes de asociar el motor, el permiso de autorización usa un prefijo de ARN limitado al nombre de este proyecto, además de condiciones de tags `Project` y `Environment`. Esta decisión evita una dependencia circular y no concede acceso genérico a los gateways de la cuenta. El permiso de invocación del backend y la política Cedar usan el ARN final exacto.

`enable_agentcore = false` es una variante explícita para practicar solo Cognito, Bedrock y autorización del backend; no es un fallback automático ante errores de Gateway. Las pruebas de Terraform cubren ambas variantes con proveedores simulados y planes locales, sin credenciales de AWS.

El operador requiere permisos de despliegue y `kms:CreateGrant` sobre la CMK para el cifrado de Policy Engine mediante Forward Access Session; Terraform no otorga permisos administrativos al rol de ejecución del producto.

## Modelo Bedrock

Se usa **Amazon Nova 2 Lite**, la generación estable actual de Nova Lite verificada en la documentación oficial, con ID de inferencia geográfica `us.amazon.nova-2-lite-v1:0` y origen `us-east-1`. Soporta Converse y herramientas del cliente; el contrato `toolConfig` del laboratorio se conserva. El extended thinking está desactivado por defecto y no se solicita el modo `high`, incompatible con algunos parámetros de inferencia actuales.

El permiso `bedrock:InvokeModel` se limita al ARN del perfil en la cuenta de laboratorio y a tres ARN de foundation model `amazon.nova-2-lite-v1:0`, en `us-east-1`, `us-east-2` y `us-west-2`. Son los destinos publicados para ese perfil desde Virginia. No se habilita enrutamiento global ni se usan comodines regionales. Es una selección geográfica de Estados Unidos, no inferencia en una sola región.

Confirmar acceso del modelo y que los SCP de la cuenta admitan esos destinos antes de ejecutar la demo. Otro modelo o región exige proporcionar `bedrock_model_arns` explícitos y verificados; una precondición bloquea cambios que reutilizarían por error la lista predeterminada. La revisión documental no sustituye una invocación real en la cuenta.

## Retiro controlado

No se incluye un script que elimine recursos automáticamente. Revisar los planes de destrucción en orden inverso: `compute`, `data`, `foundation`. Para eliminar tablas, desactivar previamente `deletion_protection` con un cambio aplicado y revisado. Cognito exige cambiar su protección de `ACTIVE` a `INACTIVE`; esto puede borrar identidades y requiere decisión explícita. Los buckets versionados conservan versiones anteriores y deben tratarse de forma explícita; `force_destroy` permanece deshabilitado. KMS usa una ventana de eliminación de 30 días. Conservar auditorías requeridas antes de retirar el servicio.

## Referencias verificadas

- [CloudFront: certificado predeterminado y política TLS](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesGeneral.html).
- [Modelos de Bedrock disponibles](https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html).
- [Backend S3 de Terraform](https://developer.hashicorp.com/terraform/language/backend/s3).
- [Permisos IAM de Gateway y Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html).
- [Identidades, acciones y recursos de Cedar](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-scope.html).
- [Cifrado del Policy Engine](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-encryption.html).
- [Versiones estables del provider AWS](https://registry.terraform.io/providers/hashicorp/aws/latest).
- [Releases estables de Terraform](https://releases.hashicorp.com/terraform/).
- [Runtimes admitidos en Lambda](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html).
- [Nova 2 Lite: perfil y destinos regionales](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html).
- [Nova 2: herramientas y Converse](https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-tools.html).
- [Permisos de perfiles de inferencia](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).
- [Políticas TLS actuales de CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/secure-connections-supported-viewer-protocols-ciphers.html).
