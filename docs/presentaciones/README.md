# Presentación de Student Community Day Chile 2026

[Descargar presentación con arquitectura completa y servicios de IA](Danny_Friz_SCD_2026_arquitectura_IA.pptx)

La versión final incluye oratoria explícita para estudiantes de nivel 200 en cada diapositiva. Define los servicios, las siglas y su función en la demo, con ejemplos de Camila y Sofía. Las notas y el [guion](../demo-35-minutos.md) se generan desde una [fuente común](oratoria-nivel-200.json); las notas contienen únicamente el discurso para decir en voz alta, con tono natural y transiciones integradas. Los conceptos de apoyo, tiempos e instrucciones de demo quedan en el guion separado.

Las diapositivas presentan esas aclaraciones en pantalla: herramienta como función programada, servicios AWS con su función, identidad de la persona separada de la aplicación y cuatro escenas que muestran cuándo se invoca el modelo. Los diagramas, íconos y tablas conservan su edición en PowerPoint.

Para actualizar las notas y generar una copia revisable sin modificar las diapositivas: `python scripts/sync_presentation_notes.py --output .build/presentacion-revisada.pptx`. Abrirla y revisar sus notas antes de reemplazar la presentación final.

Versión final de 30 diapositivas para la charla de Danny Friz del 24 de octubre de 2026. Conserva la identidad visual del evento. Las notas incluyen solo la oratoria, sincronizada con el [guion de 35 minutos](../demo-35-minutos.md). Los tiempos, las acciones de demo y las referencias se consultan en ese guion. Esta entrega incluye únicamente esa versión.

Las diapositivas 6–10 indican cuándo mostrar la web con Camila; 19–20 cubren la revisión y confirmación con Sofía; 28 demuestra el rechazo de una consulta ajena como Camila. Cada pausa define acción, resultado esperado y regreso a la PPT. El avance es manual. Iniciar cada sesión cerca de su bloque: el token dura 15 minutos y no se renueva automáticamente. No proyectar contraseñas.

La diapositiva 13 muestra el despliegue completo con dos recorridos: chat con IA y API directa para botones/revisión humana. Incluye frontend, identidad, dos Lambdas, Bedrock, AgentCore, DynamoDB y servicios de apoyo. Las diapositivas 14–15 explican Bedrock Converse, Gateway y Policy; la 16 identifica qué escenas invocan realmente el modelo. La 17 conserva el detalle del contexto HMAC de 30 segundos. La 25 trata operación y atribución de consumo del modelo.

Bedrock interpreta el lenguaje y propone una herramienta. El backend valida la propuesta y construye el texto final desde resultados autorizados. Gateway publica las herramientas y autentica al workload; Policy evalúa Cedar en ENFORCE para el rol backend y las dos acciones permitidas. La Lambda target verifica a la persona, el propietario y las reglas. La preparación explícita de revisión de Sofía y los botones no invocan el modelo. No se presentan RAG, Knowledge Bases, AgentCore Runtime ni Bedrock Agents Classic como desplegados.

El contenido refleja la demo AWS desplegada: Cognito, API Gateway, Bedrock Converse, dos Lambdas, AgentCore Gateway y Policy ENFORCE, contexto KMS HMAC, DynamoDB y controles operativos. Distingue la preparación de una revisión desde el chat de la aprobación humana con confirmación y versión. Incluye acceso a la demo y guion de supervisión, sin credenciales ni identificadores personales de sesión.

La presentación combina diagramas de arquitectura con pausas para mostrar el comportamiento en vivo. Como respaldo del recorrido se pueden preparar capturas de la sesión de Camila con P-104, la solicitud pendiente, el rechazo al pedir aprobación como cliente, la bandeja de Sofía y el diálogo de revisión. Mantener cerrado el identificador de identidad y excluir contraseñas, tokens y parámetros OAuth; describir siempre el estado que efectivamente muestra cada imagen.
