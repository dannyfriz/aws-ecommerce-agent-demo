# Contribuir

Usar español latinoamericano en documentación, comentarios de código, commits y Pull Requests. Los identificadores y términos técnicos conservan el estilo del código. Los commits siguen el formato convencional, por ejemplo `fix: bloquear aprobaciones con una versión desactualizada`.

## Flujo

1. Crear una rama con un cambio acotado y explicar el problema con datos ficticios.
2. Mantener casos de uso independientes de SDK y de HTTP. No duplicar autorización en el chat y la API.
3. Añadir pruebas cuando cambien permisos, contratos, estados o concurrencia; incluir al menos un rechazo relevante.
4. Ejecutar `scripts/Test.ps1` y validación de Terraform. Revisar el plan antes de cualquier aplicación en una cuenta autorizada.
5. Abrir un PR con problema, comportamiento resultante, validación y limitaciones. No incluir estados, planes privados, secretos ni capturas de sesiones.

## Criterios de revisión

- La identidad proviene de claims validados; ninguna entrada del cliente eleva roles.
- El modelo no toma decisiones de autorización ni aprueba reembolsos.
- Los permisos IAM son mínimos y acotados a los recursos necesarios.
- Las decisiones bloqueadas no ejecutan efectos; los reintentos no los duplican.
- La UI usa texto seguro y conserva accesibilidad con teclado.
- Los logs no contienen bearer tokens ni prompts completos.
- La documentación refleja lo que realmente está implementado y probado.

Los cambios de arquitectura o nuevos servicios requieren justificar el problema y sus costos operacionales. Evitar abstracciones sin una necesidad real. No publicar una licencia asumida: su elección corresponde al titular.
