# Contrato de la API

Salvo `GET /api/health`, las rutas requieren un access token de Cognito con el scope configurado. El navegador envía `Authorization: Bearer …`; no usar tokens en query strings. La identidad se obtiene del authorizer, no del cuerpo.

## Respuestas

```json
{"ok":true,"data":{},"request_id":"identificador-de-correlacion"}
```

```json
{"ok":false,"error":{"code":"CODIGO","message":"Descripción segura"},"request_id":"identificador-de-correlacion"}
```

Las respuestas de rechazo previas a Lambda pueden tener el formato propio de API Gateway. La UI contempla errores sin el wrapper de la aplicación. No interpretar una respuesta textual del modelo como prueba de autorización: comprobar el resultado de herramienta y la evidencia.

## Rutas

| Método y ruta | Entrada | Resultado y control |
|---|---|---|
| `GET /api/health` | Sin body | Estado público mínimo `{status:"ok"}` |
| `GET /api/me` | Sin body | `{sub,username,role}` derivados de sesión; `customer` o `supervisor` |
| `GET /api/orders/{id}` | ID en path | `{order,decision}`; propiedad para cliente, acceso de supervisión según política |
| `GET /api/refunds/pending` | `after` opcional en query string | `{orders,next_after}`; solo supervisión, hasta 25 solicitudes vigentes por página |
| `POST /api/chat` | `{message}` | `{message,results,review_order_id?}`; cada herramienta propuesta pasa por la política; sin herramienta de aprobación |
| `POST /api/tools` | `{action,order_id}` | Acción `read_order` o `request_return`; `{order,decision,executed?}` |
| `POST /api/refunds/approve` | `{order_id,expected_version,confirm:true}` | Supervisor, devolución pendiente y versión vigente; `{order,decision,executed}` |
| `POST /api/orders/reset` | `{order_id,expected_version,confirm:true}` | Supervisor; reinicia devolución demo, aumenta versión y conserva auditoría |
| `GET /api/audit` | Sin body | `{events}` solo para supervisión; paginación/alcance según implementación del adaptador |

## Pedido público

```json
{
  "order_id":"P-104",
  "customer_name":"Camila",
  "product":"Producto ficticio",
  "amount":49990,
  "currency":"CLP",
  "status":"entregado",
  "return_status":"NONE",
  "version":1
}
```

Los valores de producto y monto son ilustrativos. `return_status` puede ser `NONE`, `REQUESTED` o `REFUNDED`. No se devuelve el identificador interno del propietario para que el cliente intente reutilizarlo como autoridad.

## Revisión humana

La bandeja de supervisión consulta el índice `return_status-order_id` de DynamoDB con `return_status=REQUESTED`; no realiza Scan. El índice tiene consistencia eventual, por lo que una solicitud nueva puede tardar brevemente en aparecer. Cada candidato se vuelve a leer de forma consistente con BatchGetItem; pedidos ya aprobados o reiniciados se omiten. `next_after` es el identificador del último candidato de la página, no un total; enviarlo como `after` para continuar, incluso si una página queda vacía tras descartar estados obsoletos. No se devuelve `owner_sub`. Abrir una solicitud vuelve a consultar el pedido y no aprueba automáticamente.

La UI vuelve a consultar el pedido antes de abrir la confirmación. La persona ve pedido, producto, monto y versión. Al confirmar, el backend compara `expected_version` y estado, de manera que una lectura antigua no autorice una decisión nueva. El botón no es el control de seguridad: la misma comprobación se exige a clientes que llamen directamente a la API.

`executed:false` indica que no hubo una nueva mutación, por ejemplo en una repetición idempotente. Una aprobación registrada no equivale a una transferencia de dinero.

Si supervisión pide aprobar un reembolso e indica un único pedido (por ejemplo «Ayúdame a aprobar el reembolso P-104»), el servidor consulta el pedido autorizado y ofrece `review_order_id` únicamente cuando está `REQUESTED`. El asistente prepara la revisión sin modificar el pedido ni invocar una herramienta de aprobación. El botón del chat vuelve a consultar el estado y abre el diálogo existente; la persona confirma el pedido y su versión antes del POST de aprobación. Clientes reciben un rechazo según su perfil.

## Evidencia

Los eventos pueden incluir `event_id`, `created_at`, `actor_sub`, `role`, `action`, `order_id`, `decision`, `reason`, `executed`, `request_id`, `policy_version` y `expires_at`. Los identificadores de usuario son datos del laboratorio; limitar su acceso y retención. No registrar el access token, el prompt completo ni información de pago.
