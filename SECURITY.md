# Seguridad

Este proyecto es una demo educativa con datos ficticios y sin movimiento de fondos. No publicar datos de clientes, credenciales, access tokens, archivos de Terraform state ni planes reales.

## Reportar un problema

No incluir pruebas con secretos o información sensible en una issue pública. Contactar de forma privada al mantenedor mediante [LinkedIn de Danny Friz](https://www.linkedin.com/in/dannyfriz/) o usar Private vulnerability reporting si el repositorio lo habilita. Este enlace no implica que el canal esté monitoreado continuamente ni una garantía de tiempo de respuesta.

Describir la versión o commit, impacto, condiciones de reproducción con datos ficticios y un ejemplo mínimo. No ejecutar pruebas contra cuentas AWS ajenas ni infraestructura de un evento sin autorización.

Si se expuso una credencial, revocarla o rotarla antes de limpiar el historial. Borrar el archivo del último commit no elimina la exposición previa. Revisar CloudTrail, recursos y accesos de acuerdo con el procedimiento de respuesta de la cuenta.

## Mantenimiento

Ejecutar `& ".\scripts\Scan-Security.ps1"` antes de publicar o desplegar. Trivy revisa dependencias, configuración Terraform y secretos; CI bloquea HIGH/CRITICAL sin ignorar vulnerabilidades pendientes de corrección. No agregar supresiones para conseguir un resultado verde. Consultar [alcance y observaciones abiertas](docs/analisis-seguridad.md).

No se ofrece SLA ni una matriz de versiones productivas soportadas. Mantener runtimes, provider, dependencias y controles de acceso actualizados; ejecutar las pruebas negativas después de cambios. Ver [modelo de amenazas](docs/seguridad.md) y [operación](docs/operacion.md).
