# Decisiones de diseño

| Decisión | Motivo y consecuencia |
|---|---|
| Backend Python y SPA sin framework | KISS: pocas piezas para una demo de 35 minutos; no se requiere un servidor frontend ni dependencias de UI |
| Casos de uso independientes de AWS | Arquitectura limpia: el dominio no necesita importar boto3 ni conocer API Gateway; se prueba con adaptadores de memoria |
| Puertos para persistencia y modelo | Inversión de dependencias: la aplicación recibe capacidades concretas; no crea clientes AWS dispersos |
| Una política de negocio compartida | DRY: chat y herramientas directas ejecutan los mismos controles; esconder botones no constituye autorización |
| Herramientas pequeñas y explícitas | Responsabilidad única e interfaces acotadas: consultar y solicitar devolución tienen contratos distintos a aprobar |
| Sin herramienta de aprobación en el modelo | La decisión humana crítica no depende de prompt, temperatura o buena conducta del modelo |
| Comparación de versión y estado | Evita aprobar una pantalla desactualizada y duplicar efectos ante reintentos o concurrencia |
| Identity provider administrado | No implementar contraseñas ni JWT propios; Cognito emite y API Gateway valida |
| Sin tokens persistidos en navegador | Reduce exposición por almacenamiento; se acepta repetir ingreso al recargar |
| Terraform por tres capas | Separa ciclo de vida y dependencias; requiere orden de despliegue y protección adicional de estados |
| AgentCore Gateway + Policy ENFORCE | Separar autorización de la carga de trabajo del control de propiedad de la persona; exponer solo consulta y solicitud de devolución |
| Contexto con KMS HMAC y plazo de 30 segundos | Propagar identidad confiable sin entregar JWT o claves al modelo; target verifica firma y enlace de acción/pedido |
| Claves distintas para MAC y cifrado | Separar capacidades criptográficas y permisos GenerateMac/VerifyMac de la protección de almacenamiento |

SOLID no se interpreta como crear una clase por archivo: el código mantiene responsabilidades cohesionadas, contratos pequeños y adaptadores sustituibles. Nuevos servicios se incorporan cuando una necesidad real justifica la complejidad.

## Reglas de negocio que no debe decidir el modelo

- Un cliente consulta o solicita devolución solo de un pedido propio.
- Solo un supervisor autenticado aprueba una devolución pendiente.
- El texto de una conversación no asigna roles ni cambia ownership.
- La aprobación usa datos actuales y una versión esperada.
- Una decisión bloqueada no debe ejecutar la mutación.
- Una operación repetida no debe crear un segundo reembolso.

La autorización y la evidencia deben sobrevivir al reemplazo del modelo o del proveedor de inferencia.

El [ADR-001](adr-001-contexto-hmac.md) detalla la propagación de identidad entre orquestador, Gateway y target sin asumir que el JWT llega automáticamente.
