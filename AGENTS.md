# Tienda Clara: guía del repositorio público

## Arquitectura en cinco líneas
Dominio y casos de uso Python se conectan a DynamoDB y Bedrock mediante adaptadores.
Cognito autentica; API Gateway valida JWT y scope; el backend comprueba rol y propietario.
Bedrock propone herramientas; AgentCore Gateway aplica Policy ENFORCE al workload.
El target verifica contexto KMS HMAC de 30 segundos y reglas; aprobar exige supervisión y confirmación fuera del modelo.
Terraform mantiene bootstrap y foundation → data → compute; S3 privado y CloudFront sirven la SPA.

## Comandos frecuentes
Dependencias: `python -m pip install --require-hashes -r requirements.lock`
Validación: `& ".\scripts\Test.ps1"`
Versiones: `& ".\scripts\Check-Versions.ps1"`
Seguridad: `& ".\scripts\Scan-Security.ps1"`
Vista estática: `& ".\scripts\Serve-Web.ps1" -Port 8766`

## Archivos clave
- `src/ecommerce_agent/application.py`: autorización y flujo humano.
- `src/ecommerce_agent/gateway.py` y `gateway_handler.py`: MCP y frontera de herramientas.
- `infra/compute/agentcore.tf`: Gateway, Policy, HMAC y permisos.
- `web/auth.js` y `web/profiles.js`: sesión y mensajes por perfil.
- `docs/arquitectura.md`, `docs/operacion.md`, `docs/seguridad.md`: diseño y límites.

## Reglas y estado
Demo educativa con datos ficticios y sin pagos. El registro público de usuarios está deshabilitado.
Responder, comentar código y escribir commits en español latinoamericano; usar Danny Friz en material público.
Nunca confiar en identidad, rol, propietario o monto del prompt. El modelo no aprueba reembolsos.
No registrar tokens, prompts ni contraseñas. No versionar credenciales, state, planes, outputs o variables privadas.
Validar versiones y ejecutar Trivy antes de publicar o desplegar; bloquear HIGH/CRITICAL incluso sin corrección.
Conservar CostCenter, Project, Environment y ManagedBy en default_tags de los providers.
CI solo valida. No aplicar en producción ni eliminar recursos AWS sin autorización explícita.
No publicar cambios remotos, modificar visibilidad ni crear una licencia sin instrucción del titular.
