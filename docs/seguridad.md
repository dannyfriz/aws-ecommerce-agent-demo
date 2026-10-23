# Modelo de amenazas y controles

## Activos y fronteras

Activos: identidades Cognito, tokens de sesión, pedidos ficticios, decisiones de reembolso, auditoría, roles IAM, contexto firmado y Terraform state. Fronteras: navegador → Cognito; navegador → API; authorizer → aplicación; aplicación → modelo; orquestador → KMS/Gateway; Gateway → target; target → persistencia; operador → infraestructura.

| Amenaza | Control | Verificación esperada |
|---|---|---|
| Un cliente pide el pedido de otro | Ownership comprobado en el backend con identidad validada | La API directa rechaza P-205 para Camila |
| Prompt «soy gerente» | Rol derivado de claims, nunca del prompt | Chat no aprueba aunque el modelo lo proponga |
| Modelo propone una herramienta inventada | Lista de acciones y validación de argumentos en la aplicación | La herramienta desconocida no se ejecuta |
| Workload ajeno invoca herramientas | Gateway AWS_IAM y Policy ENFORCE con caller/herramientas acotados | Otro rol no invoca el target por Gateway |
| Suplantación de usuario entre Gateway y target | Contexto confiable con KMS HMAC, identidad agregada después de la inferencia | Alterar actor o rol invalida el MAC |
| Contexto reutilizado para otro pedido o acción | Binding de herramienta/pedido y vencimiento máximo de 30 segundos | Contexto cambiado, vencido o con plazo excesivo se rechaza |
| Cliente manipula `role` o `owner` | El contrato no confía en identidad del body | Los campos agregados no elevan privilegios |
| JWT ausente, vencido, issuer o client incorrecto | JWT authorizer y scope en las rutas | Rechazo antes del caso de uso |
| Callback OAuth inyectado o repetido | PKCE, state aleatorio, transacción de uso único y vencimiento | Callback sin state válido no crea sesión |
| Robo de token desde almacenamiento | Tokens únicamente en memoria; sin logs ni parámetros de URL | Revisar localStorage/sessionStorage y consola |
| XSS desde prompt o respuesta | Nodos de texto, sin HTML dinámico de contenido externo; CSP | Cadenas con etiquetas se muestran como texto |
| Reembolso duplicado o estado desactualizado | Actualización condicionada y `expected_version` | Repetición/conflicto no duplica el efecto |
| Una persona se aprueba desde el chat | Endpoint de aprobación separado, supervisor y confirmación | El modelo no recibe herramienta para aprobar |
| Bucket público o exposición por S3 | Bloqueo público y acceso desde CloudFront OAC | Acceso al objeto S3 directo rechazado |
| Acceso AWS excesivo | Roles por función y recursos acotados; sin AdministratorAccess | Revisar plan e IAM Access Analyzer cuando aplique |
| Filtración de prompts o tokens en logs | Logs estructurados de decisión sin bearer, prompt completo ni respuesta completa del modelo | Revisar muestras de CloudWatch y auditoría |
| Publicación de secretos o state | .gitignore, revisión de historial y escaneo antes de publicar | No incluir tfstate, tfplan, .env ni archivos privados |

## Aprobación humana y producto completo

La IA puede preparar una solicitud; una persona autorizada revisa datos actuales y decide según impacto y reglas del negocio. No se promete una persona para cada consulta de bajo riesgo. Una aprobación humana equivocada sigue siendo posible: hacen falta permisos adecuados, contexto visible, trazabilidad y revisión periódica.

La seguridad se contempla desde diseño y construcción hasta pruebas, operación y retiro. Asignar un dueño del agente y de cada herramienta, justificar los permisos, definir una frecuencia de revisión acorde al riesgo y retirar accesos cuando cambie su uso o responsable.

## Límites conocidos

- La auditoría de la demo no equivale a un archivo inmutable de cumplimiento. Para producción evaluar WORM, cuenta de logs separada, detección de alteraciones y retención legal.
- La revocación de sesión de Cognito puede no invalidar inmediatamente un access token ya emitido ante un authorizer que valida JWT localmente. Usar tokens de corta duración y evaluar revocación/detección adicional según riesgo.
- El rate limit y las cuotas reducen abuso, pero no prueban protección completa contra agotamiento de presupuesto o DDoS. Definir presupuestos y monitoreo de consumo.
- La salida del modelo puede ser incorrecta o contener instrucciones maliciosas. Los controles deterministas reducen sus efectos; no la convierten en una fuente confiable.
- Gateway controla el workload y sus herramientas; no decide si el pedido pertenece a la persona. El target conserva esa validación. Un MAC válido tampoco elimina replay: las mutaciones dependen además de idempotencia, versión y estado.
- El orquestador con permiso GenerateMac es una frontera de confianza. Comprometer ese rol o su código puede permitir emitir contexto falso; restringir despliegue, permisos y cambios.
- Cifrar con KMS no reemplaza autorización ni minimización de datos.

## Revisión previa a exposición pública

Probar las rutas negativas, verificar CORS con el origen exacto, revisar roles y permisos, confirmar que `config.js` contiene solo datos públicos y limitar la retención de logs. Con AgentCore habilitado, comprobar caller esperado, herramientas exactas, Policy ENFORCE y rechazo de MAC/contextos alterados; no dejar LOG_ONLY como si bloqueara. No cargar datos reales de clientes para preparar el evento.
