# Pruebas según el impacto de los cambios

`scripts/Test.ps1` ejecuta por defecto las suites relacionadas con los archivos modificados y sus dependencias. El plan queda en `.build/test-impact.json` e incluye los archivos detectados, las suites elegidas, las capas Terraform y los motivos de selección. No cambia ni elimina pruebas existentes.

## Uso local

Validar cambios locales, incluyendo archivos preparados en Git, modificaciones sin preparar y archivos nuevos:

```powershell
& ".\scripts\Test.ps1"
```

Revisar la selección sin ejecutar las suites:

```powershell
& ".\scripts\Test.ps1" -PlanOnly
```

Comparar contra un commit o rama base, además de revisar sus dependencias:

```powershell
& ".\scripts\Test.ps1" -BaseRef HEAD~1
```

Inspeccionar el impacto de un archivo concreto:

```powershell
& ".\scripts\Test.ps1" -ChangedFiles "web/conversation.js" -PlanOnly
```

Solicitar la validación completa, por ejemplo al comprobar una copia recién clonada:

```powershell
& ".\scripts\Test.ps1" -Full
```

Sin cambios locales no se ejecutan suites de ejecución; se conserva la revisión de artefactos privados y sintaxis. Usar `-BaseRef` para validar cambios ya confirmados. La opción `-SkipTerraform` sigue disponible como exclusión explícita y se informa en la salida; no equivale a aprobar esas capas.

## Criterios

| Cambio | Selección |
|---|---|
| Documentación, imágenes o presentaciones | Revisión del repositorio; sin suites Python, frontend o Terraform |
| JavaScript del frontend | Suites que importan o inspeccionan ese archivo y sus dependientes; sintaxis de los JavaScript afectados |
| Código Python | Suites que importan el módulo directa o indirectamente y las comprobaciones de contratos relacionadas |
| Una prueba o fixture | La prueba modificada y las suites que consumen su helper o fixture |
| Terraform de compute | Compute |
| Terraform de data | Data y compute |
| Terraform de foundation | Foundation, data y compute |
| Terraform de bootstrap | Todas las capas |
| Solo una prueba Terraform | Su capa |
| Dependencias, configuración transversal, selector o CI | Validación completa |
| Impacto que no se puede determinar | Validación completa con el motivo indicado |

El selector analiza imports de Python y JavaScript y referencias a los archivos que leen las pruebas. También contempla contratos compartidos: cambiar la respuesta del backend puede afectar al frontend aunque este no importe Python. Un archivo ejecutable nuevo, eliminado o renombrado no debe quedar excluido por no tener una coincidencia simple de nombre.

Las pruebas Python seleccionadas se ejecutan en un único proceso. Node y Terraform se resuelven solo si hacen falta. Una modificación de texto o estilo de la web no requiere crear de nuevo el paquete Lambda.

## GitHub Actions

El job `impacto` calcula el plan. En un push compara el commit anterior con el nuevo; en una PR usa su base y head. Si no hay una base utilizable, el selector amplía la validación y explica el motivo. Se puede ejecutar manualmente el workflow con `full=true` para comprobar todo.

Python mantiene sus dos versiones compatibles cuando hay suites Python afectadas. Las suites frontend se ejecutan una sola vez y Terraform solo inicia las capas seleccionadas. El paquete Lambda y la consulta de versiones oficiales se ejecutan cuando el plan los requiere. El gate de Trivy completo se conserva para cada publicación, con bloqueo de HIGH/CRITICAL.

Las evaluaciones con Bedrock real, las sesiones autenticadas y los controles de recursos AWS se reservan para cambios que afecten esos recorridos. Cambiar documentación o el selector de CI no requiere desplegar la aplicación ni consultar las cuentas de la demo.

## Comprobación de la selección

Se verificaron 35 casos del selector y nueve del workflow, incluyendo imports transitivos, fixtures, renombres, eliminaciones, cambios preparados, archivos nuevos e historial insuficiente. También se comprobaron estos planes de selección en el repositorio real:

| Archivo indicado | Python | Frontend | Terraform |
|---|---:|---:|---|
| `docs/pruebas-diferenciales.md` | 0 suites | 0 suites | Ninguna capa |
| `web/conversation.js` | 0 suites | 3 suites | Ninguna capa |
| `tests/test_conversation_memory.py` | 1 suite | 0 suites | Ninguna capa |
| `infra/compute/backend.tf` | 0 suites | 0 suites | Compute |
| `infra/data/main.tf` | 0 suites | 0 suites | Data y compute |
| `infra/foundation/tests/security.tftest.hcl` | 0 suites | 0 suites | Foundation |

La ejecución de documentación aprobó incluso indicando rutas inexistentes para Node y Terraform, confirmando que no intenta resolverlos. La ejecución de `web/conversation.js` aprobó las tres suites seleccionadas sin ejecutar suites Python ni iniciar Terraform. El plan de los cambios de este selector activa la validación completa de pruebas por ser transversal, pero no requiere reconstruir Lambda si su contenido permanece igual.
