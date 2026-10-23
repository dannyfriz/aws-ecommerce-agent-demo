# Recursos desplegados de la demo

Estos nombres corresponden al laboratorio mostrado en la charla. El 23 de octubre de 2026 se verificaron mediante consultas de solo lectura a AWS dos funciones Lambda en estado `Active` y dos tablas DynamoDB en estado `ACTIVE`, todas en `us-east-1`. La consulta no modificó recursos.

Los diagramas usan el prefijo común `ecommerce-agent-demo-` y muestran las terminaciones para facilitar su lectura. En la consola se busca el nombre completo.

| Nombre completo | Tipo | Función en la demo |
|---|---|---|
| `ecommerce-agent-demo-backend` | Función Lambda | Coordina la API, consulta Bedrock y prepara el contexto confiable para Gateway. Las operaciones directas y la confirmación humana también se procesan aquí. |
| `ecommerce-agent-demo-tools` | Función Lambda | Recibe las llamadas de herramientas desde Gateway, verifica el contexto y aplica los permisos de la persona antes de consultar o modificar un pedido. |
| `ecommerce-agent-demo-orders` | Tabla DynamoDB | Guarda los pedidos, su propietario, estado y versión. |
| `ecommerce-agent-demo-audit` | Tabla DynamoDB | Guarda la evidencia de las decisiones, incluidos los rechazos. Su retención tiene vencimiento; no es un registro permanente ni inmutable. |

La consulta por chat puede recorrer backend → Bedrock → Gateway/Policy → tools. Los botones de la API y la aprobación humana usan la ruta directa del backend. Ninguna herramienta del modelo aprueba reembolsos.

## ARN de cada recurso

Un ARN identifica un recurso concreto en AWS. Los siguientes conservan el servicio, la región y el nombre verificados; `CUENTA_AWS` reemplaza el identificador de la cuenta en el material compartido. Es un marcador explicativo: para usar estos ARN en una política hay que sustituirlo por el número de la cuenta correspondiente.

**Lambda que coordina la aplicación:**

```text
arn:aws:lambda:us-east-1:CUENTA_AWS:function:ecommerce-agent-demo-backend
```

**Lambda de herramientas:**

```text
arn:aws:lambda:us-east-1:CUENTA_AWS:function:ecommerce-agent-demo-tools
```

**Tabla de pedidos:**

```text
arn:aws:dynamodb:us-east-1:CUENTA_AWS:table/ecommerce-agent-demo-orders
```

**Tabla de decisiones:**

```text
arn:aws:dynamodb:us-east-1:CUENTA_AWS:table/ecommerce-agent-demo-audit
```

En el ARN de la tabla, `dynamodb` indica el servicio; `us-east-1`, la región; `CUENTA_AWS`, la cuenta; y `table/ecommerce-agent-demo-orders`, el recurso. Reconocer estas partes permite comprobar a qué destino llega un permiso sin memorizar la cadena completa.

## Una función y su rol son recursos distintos

La función `ecommerce-agent-demo-tools` ejecuta código. Su rol IAM, que en este proyecto comparte el mismo nombre, es la identidad que Lambda asume para obtener permisos técnicos. Se identifican con ARN diferentes:

```text
arn:aws:lambda:us-east-1:CUENTA_AWS:function:ecommerce-agent-demo-tools
arn:aws:iam::CUENTA_AWS:role/ecommerce-agent-demo-tools
```

El ARN de la función pertenece al servicio `lambda` y contiene la región. El ARN del rol pertenece a `iam` y su campo de región está vacío. Coincidir en el nombre final no los convierte en el mismo recurso.

El ejemplo de la diapositiva 13 representa una parte del permiso de ese rol:

```json
{
  "Effect": "Allow",
  "Action": "dynamodb:GetItem",
  "Resource": "arn:aws:dynamodb:us-east-1:CUENTA_AWS:table/ecommerce-agent-demo-orders"
}
```

`GetItem` permite leer un registro de esa tabla. Este fragmento es explicativo y no reemplaza la política completa. El permiso de IAM no demuestra que Camila sea propietaria del pedido: esa comprobación la realiza el código con la identidad de la sesión verificada.

## Relación con Terraform y la presentación

Los nombres se construyen como `${var.project}-${var.environment}` más el sufijo del recurso. Este laboratorio usa `project=ecommerce-agent` y `environment=demo`; otros valores producen nombres diferentes. Los ARN publicados aquí permiten seguir esta demo, no describen recursos que necesariamente existan en la cuenta de quien copie el proyecto.

| Fuente | Qué define |
|---|---|
| [compute/versions.tf](../infra/compute/versions.tf) y [data/versions.tf](../infra/data/versions.tf) | Proyecto, ambiente, región y prefijo de nombres. |
| [backend.tf](../infra/compute/backend.tf) | Función backend, rol y acceso técnico a los servicios. |
| [agentcore.tf](../infra/compute/agentcore.tf) | Función tools, su rol y el permiso sobre la tabla de pedidos. |
| [data/main.tf](../infra/data/main.tf) | Tablas de pedidos y auditoría, claves, cifrado y retención. |
| [application.py](../src/ecommerce_agent/application.py) | Autorización por persona, propietario, rol y estado del pedido. |

La diapositiva 7 ubica los nombres en el recorrido; la 13 relaciona acción y ARN con mínimo privilegio. Los anexos 23 y 24 conservan la misma nomenclatura en los diagramas. El anexo 25 reúne los cuatro nombres con su función. Esta guía añade los ARN de referencia para consultar durante las preguntas.
