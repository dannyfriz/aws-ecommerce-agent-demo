# Rendimiento del asistente

La respuesta espera a que el servidor valide los datos y confirme el resultado. Las preferencias, el contexto y el filtro de contenido se consultan en paralelo, con un máximo de tres tareas por solicitud. El modelo y Gateway comienzan después de completar esas comprobaciones. La auditoría y la escritura del contexto permanecen en el flujo confirmado de la solicitud.

Gateway reutiliza conexiones HTTPS verificadas. Cada solicitud obtiene las credenciales temporales vigentes y genera una firma SigV4 nueva; el pool solo conserva conexiones. No hay reintentos automáticos ni redirecciones que puedan repetir una acción. Las respuestas siguen limitadas a 64 KiB.

## Memoria de las funciones

El backend tiene 1024 MB y la función de herramientas 512 MB. AWS asigna CPU proporcional a la memoria; el ajuste busca reducir el trabajo de inicialización de Python y del SDK, además de acelerar la ejecución. No mantiene instancias aprovisionadas. La facturación depende de memoria y duración: revisar el consumo con `CostCenter=ecommerce-agent-demo` y el [procedimiento de costos](costos.md). Referencia: [configuración de memoria de AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html).

## Método de comparación

La medición del 23 de octubre de 2026 usa la API HTTPS y sesiones OAuth reales de Camila, Diego y Sofía. Cada cuenta consulta su pedido autorizado y después pregunta por el pedido anterior, conservando el mismo UUID de conversación. Se registra el tiempo hasta recibir la respuesta completa, no solo el tiempo de generación del modelo.

Cada serie tiene tres consultas iniciales de calentamiento y doce consultas comparables, intercaladas entre las tres cuentas. Las consultas iniciales se informan por separado. La auditoría confirma `read_order` para cada consulta y una lectura consistente de DynamoDB comprueba que P-104, P-205 y P-206 no cambian. No se guardan tokens, contraseñas, prompts ni respuestas en el reporte de tiempos.

El primer ajuste, que ejecuta las comprobaciones independientes en paralelo, redujo el promedio de 2,7025 a 2,1242 segundos: 21,4% menos latencia en las doce consultas comparables. La primera consulta posterior a esa actualización tardó 12,3943 segundos; es una observación separada, compatible con trabajo de inicialización, y no forma parte del promedio de consultas calientes.

## Resultado de la versión final

Con las conexiones reutilizadas y el ajuste de memoria, la misma serie de doce consultas dio estos resultados:

| Medida | Versión inicial | Versión final |
|---|---:|---:|
| Promedio | 2,7025 s | 2,0862 s |
| Mediana | 2,6785 s | 2,0490 s |
| Máximo observado | 3,0270 s | 2,2599 s |

El promedio bajó **22,81%**, superando la meta de reducir la latencia 20%. La primera consulta tras el último despliegue tardó **7,0124 s**, frente a los 12,3943 s observados tras el primer ajuste. Esta comparación de primeras consultas tiene una sola observación por actualización y no es una medición estadística del arranque.

Las comprobaciones autenticadas finales confirmaron los tres rechazos por perfil, la regla de los 90 días, el filtro de contenido sensible y la consulta de políticas con fuente verificada. La auditoría registró los rechazos sin ejecutar acciones y los tres pedidos conservaron su contenido y versión. Aprobaron 267 pruebas Python, siete suites frontend y 22 pruebas Terraform. Las tres capas desplegadas quedaron sin cambios pendientes.

## Preparación del evento

Antes de la charla, iniciar las tres sesiones y ensayar una consulta completa por chat. El indicador de API no comprueba todo el recorrido de Bedrock, Gateway y herramientas. Mantener una captura de respaldo y mostrar la respuesta real y su evidencia durante la actividad.

Una serie corta no garantiza un tiempo fijo para todas las preguntas. El arranque de una función, la red, la carga de AWS y las preguntas que consultan políticas pueden cambiar la latencia. No omitir filtros, permisos, auditoría ni confirmaciones humanas para acelerar la demo.
