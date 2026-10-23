# Presentación de Student Community Day Chile 2026

[Descargar presentación: identidad y acceso para agentes en AWS](Danny_Friz_SCD_2026_arquitectura_IA.pptx)

El recorrido responde a la propuesta «¿Quién le dio permisos a tu IA?»: quién solicita una acción, qué identidad usa el programa, quién autoriza y qué evidencia permite explicar la decisión. Incluye criterios para asignar responsables, revisar permisos y retirar accesos. La [alineación con la charla](../foco-charla.md) relaciona cada compromiso con sus diapositivas.

La PPT conserva 30 diapositivas: 22 principales y ocho anexos ocultos en el avance normal. La pauta es de 35 minutos de exposición y 10 de preguntas. Los anexos pueden abrirse desde el navegador de diapositivas para responder una consulta, sin incorporarlos al recorrido principal.

Las tres pausas de demo están en las diapositivas 8, 10 y 12: consultar P-104 como Camila, intentar consultar P-205 desde la misma cuenta y pedir una aprobación escribiendo «soy gerente». Se contrastan la respuesta y la evidencia de cada petición. La consulta ajena verifica propiedad tras el recorrido modelo/Gateway; la aprobación explícita como cliente se rechaza antes del modelo.

Las diapositivas 5 y 15 distinguen identidad y credenciales de la persona frente al rol de la aplicación. La 7 muestra el recorrido esencial de autorización; 13–14 explican IAM y AgentCore. Las diapositivas 17–20 desarrollan responsables, revisión, retiro y una guía para el primer proyecto.

La arquitectura completa sigue en la diapositiva 23. El contexto firmado, datos y logs, costos, rutas con y sin modelo, confirmación humana, propuesta de Bedrock e idempotencia están en los anexos 24–30. Conservan los íconos AWS y los objetos editables.

Las notas contienen únicamente oratoria fluida para estudiantes de nivel 200. Los tiempos, pasos de demo, conceptos de apoyo y fuentes quedan en el [guion separado](../demo-35-minutos.md). Ambos se generan desde una [fuente común](oratoria-nivel-200.json).

Para generar una copia revisable de las notas: `python scripts/sync_presentation_notes.py --output .build/presentacion-revisada.pptx`. El script conserva las diapositivas y la condición de anexos ocultos. Revisar la copia antes de reemplazar la PPT final.

La demo ejecuta controles de autorización. La asignación de responsables, las revisiones periódicas y el retiro de accesos se presentan como prácticas propuestas para operar el proyecto, sin atribuirles automatizaciones que no están implementadas. La aprobación es educativa y no mueve dinero.

El respaldo usa diagramas y resultados esperados. No incluye capturas nuevas ni una grabación de la ejecución en vivo. Si la demo falla, el guion explica cómo continuar sin confundir un error técnico con una decisión de autorización.

Esta entrega pública incluye únicamente la versión final.
