# Operación del laboratorio

## Antes de desplegar

Usar una cuenta de laboratorio y un perfil SSO con permisos de despliegue separados del rol de ejecución. Revisar las versiones de Terraform y provider requeridas, acceso regional al modelo Bedrock y presupuesto. El estado remoto contiene datos sensibles: mantenerlo privado, cifrado, versionado y con permisos mínimos. El bucket de backend se crea antes de inicializar las otras capas.

Aplicar `foundation`, después `data` y finalmente `compute`. Un cambio en las salidas de una capa requiere revisar planes de las dependientes. No ejecutar capas en paralelo. El backend S3 y las claves KMS deben ser accesibles por el operador, no por el navegador ni por el modelo.

`scripts/Init-State.ps1` recibe `-Profile`, `-VarFile`, `-Environment demo` y `-Action plan|apply` para el bootstrap. Tras aplicar genera `.build/outputs/bootstrap.json` y `.build/backend/{foundation,data,compute}.hcl`. Completar las variables `state_bucket` y región de las capas con las salidas reales. `scripts/Deploy.ps1` recibe `-Layer foundation|data|compute`, `-Action plan|apply`, `-Profile`, `-BackendConfig`, `-VarFile` y `-Environment demo|dev|test`. Cada archivo backend tiene una clave de state distinta; cada apply exporta `.build/outputs/{capa}.json`. Un plan no genera outputs. El script bloquea apply de producción; no alterar ese control para la demo.

AgentCore está habilitado de forma predeterminada con `enable_agentcore=true`. Confirmar disponibilidad regional y revisar Gateway AWS_IAM, Policy ENFORCE, target Lambda y clave HMAC. La clave HMAC no reemplaza las claves de cifrado. KMS no admite rotación automática para esta clave HMAC: una rotación requiere crear otra clave y coordinar orquestador y target, contemplando los contextos en tránsito. Si se deshabilita AgentCore para diagnóstico, el chat usa el camino directo y debe indicarse expresamente al demostrarlo.

## Configuración web

Para habilitar las seis mejoras en `compute`, configura `enable_conversation_memory`, `enable_preference_memory`, `enable_content_guardrails` y `enable_policy_knowledge` en `true` dentro del archivo de variables privado. Sus valores predeterminados son `false`. Después del `apply`, ejecuta `Sync-Knowledge.ps1` con `-ExpectedAccountId` y el perfil de laboratorio: comprueba la cuenta y sincroniza el documento hasta `COMPLETE`. Una base creada todavía necesita esta ingesta para responder. Repetirla tras cambiar las políticas. El procedimiento y las retenciones están en [memoria y conocimiento](memoria-y-conocimiento.md).

Verifica «Consulta P-104» → «Quiero devolverlo», una conversación nueva sin contexto, aislamiento entre usuarios, preferencias tras volver a ingresar, preguntas de políticas con fuente y bloqueos de contenido. Usa un pedido técnico para las pruebas con mutaciones. Ejecuta `Evaluate-Agent.ps1` sin parámetros para la regresión local; `-Live` usa Bedrock con pedidos ficticios y `-Managed` incorpora AgentCore Evaluations. Las evaluaciones no ejecutan operaciones sobre pedidos AWS.

En cuentas de laboratorio con cuota regional Lambda de 10, AWS puede impedir toda reserva porque exige mantener 10 ejecuciones sin reservar. El valor predeterminado reserva 3 por función; únicamente para ese caso se puede indicar `lambda_reserved_concurrent_executions = -1` en las variables privadas de compute. Esto usa el cupo compartido de la cuenta y pierde el aislamiento por función; no aumenta la cuota ni sustituye la reserva. Se mantiene el throttle de API Gateway de 2 solicitudes por segundo y burst 5. Escanear también las variables efectivas con Trivy y restaurar la reserva cuando AWS aumente la cuota.

Terraform en `compute` publica automáticamente el frontend y genera `config.js`; `foundation` configura callbacks y logout de Cognito según la URL del frontend. No se requiere publicar la web manualmente. `config.js` es configuración pública, no un contenedor de secretos:

```javascript
window.APP_CONFIG = {
  apiBaseUrl: 'https://ID.execute-api.REGION.amazonaws.com',
  cognitoDomain: 'https://DOMINIO.auth.REGION.amazoncognito.com',
  clientId: 'CLIENT_ID_PUBLICO',
  redirectUri: 'https://DISTRIBUCION.cloudfront.net/',
  scope: 'openid email profile PROYECTO/access',
  region: 'REGION'
};
```

Los valores anteriores son ilustrativos; el archivo desplegado usa las salidas reales. `redirectUri` coincide exactamente con la URL de la SPA, incluida su barra final, y con los callbacks permitidos de Cognito. La URL de salida también queda autorizada en Cognito. API y dominio Cognito usan únicamente el origen, sin path/query. API Gateway permite CORS solo para los orígenes aprobados y el encabezado Authorization; no usar `*` como sustituto de una configuración correcta.

Para una vista estática, `scripts/Serve-Web.ps1 -Port 8766` sirve `web/config.example.js` como `/config.js` cuando no existe un config local. Abrir `http://127.0.0.1:8766/`. Los endpoints `example.invalid` son deliberadamente ficticios: no se puede ingresar a AWS con ellos. `web/config.js` está excluido de Git. No confundir la vista estática con una prueba de autenticación o de herramientas.

Los tokens no se guardan. Al recargar se vuelve a ingresar; Cognito puede resolverlo con su sesión existente. El navegador debe admitir JavaScript, Web Crypto y `<dialog>`.

## Usuarios y pedidos

La tarjeta «Tu sesión» muestra el nombre autenticado, el perfil técnico (`customer` o `supervisor`) y sus permisos para apoyar la actividad. El nombre procede del claim `username` validado por API Gateway; la autorización sigue usando el `sub` y los grupos de Cognito, nunca el texto del chat. El `sub` se puede consultar al desplegar el identificador de identidad. Cliente consulta pedidos propios y solicita devoluciones; supervisión consulta pedidos y auditoría, y aprueba únicamente con confirmación humana.

Los nombres Camila, Diego y Sofía son personajes. Vincular los pedidos a los `sub` reales emitidos por el pool de laboratorio mediante el script de seed. El grupo supervisor se asigna administrativamente, nunca desde el formulario o el chat. No habilitar registro público para facilitar la demo.

`scripts/Seed-Demo.ps1 -Profile TU_PERFIL` usa `.build/outputs/foundation.json` y `.build/outputs/data.json`. `-FoundationOutputs` y `-DataOutputs` son opcionales para rutas alternativas. Solicita las contraseñas mediante entrada protegida; no proporcionarlas en argumentos ni variables publicadas. Para ingresar se usa `sofia`, sin tilde; Sofía es el nombre para mostrar. Los archivos con outputs son información de operación y no se incluyen en el repositorio público. `-ResetOrders` reinicia explícitamente solo P-104 y P-205 con condiciones de propietario y versión; revisar su estado antes de utilizarlo.

No ejecutar seed sobre datos ajenos al laboratorio. Antes de reiniciar el estado ficticio, revisar las protecciones e interacción del script. No conceder permisos de administración a Lambda para que cree usuarios o cambie grupos.

## Verificación de salida

La interfaz muestra el estado de conexión de la API antes de iniciar sesión. Consulta `GET /api/health` al abrir la página, cada 60 segundos mientras esté visible y al presionar «Actualizar estado», con timeout de 8 segundos. Los estados son «Disponible», «Sin respuesta» y «Sin conexión». El endpoint público devuelve únicamente `status: ok`, sin consultar datos ni invocar Bedrock o AgentCore; no acredita la salud de esas dependencias. Las rutas de negocio siguen exigiendo JWT y scope.

`scripts/Smoke-Test.ps1` verifica HTTPS del frontend y rechazo 401/403 de `/api/me` sin JWT. No recibe credenciales ni muta AWS. Las comprobaciones autenticadas del recorrido se realizan con las sesiones del laboratorio; el smoke test por sí solo no las demuestra.

1. CloudFront abre por HTTPS y S3 directo no expone el sitio.
2. Sin sesión, la API rechaza solicitudes.
3. Camila consulta P-104 y no accede a P-205.
4. La devolución deja el pedido pendiente de revisión.
5. Camila no aprueba, aunque el prompt diga que es gerente.
6. Sofía consulta datos actuales, revisa monto y confirma con una versión vigente.
7. Reintentos no duplican efectos y las decisiones tienen request ID.
8. Logs y capturas no contienen bearer tokens ni prompts completos.
9. Con AgentCore activado, el chat invoca Gateway y su Policy está en ENFORCE; comprobar rechazos de caller/herramienta y de contexto HMAC inválido en pruebas controladas.

## Diagnóstico

Los errores de autorización conservan el código `ACCESS_DENIED` y agregan un motivo público controlado y una explicación con el siguiente paso. `RESOURCE_NOT_AUTHORIZED` indica que el pedido no es accesible desde la cuenta; se usa exactamente la misma respuesta para pedidos ajenos e inexistentes. `HUMAN_SUPERVISOR_REQUIRED` explica que la aprobación requiere supervisión; `SUPERVISOR_REQUIRED` identifica la restricción de auditoría. El chat conserva estos motivos mediante Gateway, sin mostrar textos arbitrarios del target ni propietarios de pedidos. El frontend resalta el error y mantiene el motivo y request ID en la evidencia. También orienta ante sesión vencida, exceso de solicitudes y fallas del servicio.

| Síntoma | Revisar |
|---|---|
| Cognito rechaza callback | Coincidencia exacta de scheme, host, path y barra final |
| State vencido | Iniciar otra vez en la misma pestaña; no copiar callbacks entre ventanas |
| API devuelve 401/403 antes de Lambda | Issuer, client ID, scope, expiración y rutas del authorizer |
| Bedrock deniega acceso | Región, model ID/ARN, permisos del rol, disponibilidad y cuota |
| Pedido propio aparece denegado | `sub` del usuario frente al ownership creado por el seed |
| Cambio de rol no aparece | Cerrar sesión e ingresar para obtener claims nuevos |
| Conflicto de aprobación | Volver a consultar el pedido y revisar el estado actualizado |
| Cambio frontend no aparece | Caché de CloudFront y publicación de config.js/archivos |
| Gateway deniega una herramienta | Caller IAM, nombre exacto de herramienta, attachment de Policy y modo ENFORCE |
| Target rechaza contexto | MAC, clave HMAC correcta, herramienta/pedido vinculados y plazo de 30 segundos; no registrar el envelope completo |

Correlacionar por `request_id`; no habilitar logs completos de Authorization ni copiar tokens a tickets.

Para demoras del asistente, separar la primera consulta de las siguientes y medir la respuesta completa. El [procedimiento de rendimiento](rendimiento.md) documenta las comprobaciones concurrentes, las conexiones reutilizadas, la memoria de las funciones y la comparación de tiempos.

## Costos y retiro manual

Los consumos dependen de región, tokens, llamadas, retención y tráfico. Revisar los precios oficiales y presupuestos de la cuenta; no asumir free tier. Evitar loops de invocación y mantener límites de salida del modelo y de API. No garantizar cifras sin una estimación real.

Después del evento, el responsable decide si conservar evidencia y recursos. Para retirar, revisar dependencias y el plan de destrucción en orden inverso `compute` → `data` → `foundation`; el bootstrap se trata por separado al final y solo cuando ya no contenga estados necesarios. No automatizar borrado de recursos, vaciado de buckets, eliminación de usuarios ni claves. Las protecciones de tablas/buckets pueden exigir pasos manuales deliberados. Las claves KMS tienen ventanas de eliminación: no cancelarlas o programarlas sin revisar qué datos dependen de ellas.
