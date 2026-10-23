# Validación de la copia pública

Revisión del 23 de octubre de 2026, antes de publicar este repositorio con historial nuevo.

| Comprobación | Resultado |
|---|---|
| Python | 79 pruebas aprobadas |
| Frontend | Seis suites aprobadas: autenticación, evidencia, sincronización, perfiles, pendientes y revisión |
| Terraform | Formato y validación de las cuatro raíces aprobados; 15 pruebas con provider simulado |
| Empaquetado | ZIP Lambda ARM64 construido con dependencias fijadas y hashes |
| Versiones | Pins contrastados con las fuentes oficiales por `Check-Versions.ps1` |
| Seguridad | Trivy 0.76.1: nueve paquetes verificados, 0 CVE conocidas, 0 secretos y 0 HIGH/CRITICAL |
| Publicación | Enlaces locales y XML de PowerPoint revisados; ejemplos sin identificadores del despliegue |

Se conservan dos observaciones MEDIUM y cuatro LOW en [el resumen Trivy](trivy-resultados.md), con su alcance en [análisis de seguridad](analisis-seguridad.md). No se ocultan para aprobar la validación.

Estas pruebas locales no desplegaron recursos ni consultaron pedidos en AWS. Terraform utilizó un mirror local del provider contrastado con los checksums de los locks; CI vuelve a inicializar desde el registro con `-lockfile=readonly`. El workflow [Validación sin despliegue](https://github.com/dannyfriz/aws-ecommerce-agent-demo/actions) también comprueba Python 3.14.9 y 3.15.1 en runners Linux. Sus resultados se consultan por commit.
