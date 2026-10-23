# Análisis automatizado con Trivy

Se utiliza **Trivy 0.76.1**, fijado en `toolchain.versions.json` junto con los SHA256 oficiales de Windows y Linux. El instalador descarga únicamente el binario de su [publicación oficial](https://github.com/aquasecurity/trivy/releases/tag/v0.76.1) y verifica el archivo antes de extraerlo. No se ejecutan scripts descargados ni se incorpora una action adicional de terceros.

Desde la raíz del proyecto, con las versiones de Python y PowerShell indicadas en [Versiones](versiones.md):

```powershell
& ".\scripts\Scan-Security.ps1"
```

El script descarga la herramienta fijada y ejecuta dos análisis. El primero revisa fuentes públicas, Terraform y posibles secretos. El segundo transforma temporalmente los locks en un `requirements.txt` reconocido por Trivy; confirma en el inventario los nueve nombres y versiones esperados, incluidos build tools. Si falta un paquete, falla. El frontend no tiene dependencias npm de ejecución. `trivy.yaml` excluye entornos locales, dependencias instaladas, cachés y archivos privados ubicados en `.build`; no contiene exclusiones por vulnerabilidad ni por regla.

Los reportes quedan en `.build/security/source.json`, `dependencies.json`, `summary.json` y `summary.md`. Los JSON completos pueden contener evidencia sensible si se detecta un secreto: no publicarlos sin revisión. El resumen omite coincidencias y fragmentos de secretos. El job `seguridad` de CI muestra el resumen en GitHub Actions y devuelve error con cualquier HIGH o CRITICAL, tenga corrección disponible o no. MEDIUM y LOW permanecen visibles. Un error al descargar la base o ejecutar el analizador también detiene el job.

## Resultados y observaciones abiertas

El [resumen de la ejecución](trivy-resultados.md) conserva la fecha, las versiones analizadas y el resultado observado. Un resultado anterior no reemplaza un escaneo nuevo: ejecutar el gate antes de publicar o desplegar. Las observaciones MEDIUM y LOW permanecen visibles aunque no bloqueen el umbral configurado.

CloudFront incorpora una Web ACL obligatoria con AWS Managed Rules y límite por IP. La protección alcanza al frontend CloudFront. La API conserva JWT, scopes, reglas del backend y throttling; esta Web ACL no protege el endpoint directo de API Gateway. WAF agrega costos al desplegarlo; revisar el plan y el presupuesto de la cuenta.

| Regla | Severidad | Observación y tratamiento |
|---|---|---|
| AWS-0065 | MEDIUM | KMS HMAC no admite rotación automática. Mantener el hallazgo visible y realizar rotación manual según el procedimiento de claves. No habilitar una opción incompatible solo para satisfacer el scanner. |
| AWS-0010 | MEDIUM | Faltan access logs de CloudFront. Pendiente incorporar entrega de logs con cifrado, retención y control de acceso antes de ampliar el uso. |
| AWS-0089, dos recursos | LOW | Faltan server access logs de los buckets de frontend y state. Pendiente definir destino y retención de logs. |
| AWS-0066, dos funciones | LOW | X-Ray no está habilitado. Los logs de aplicación y API siguen cifrados; el tracing distribuido queda pendiente. |

AWS documenta que las [claves HMAC requieren rotación manual](https://docs.aws.amazon.com/kms/latest/developerguide/rotate-keys.html). La rotación debe coordinar nueva clave, permisos y actualización de ambas Lambdas; validar antes el cambio y permitir que expire el contexto HMAC de 30 segundos antes de retirar el acceso a la clave anterior. No eliminar una clave como parte de una ejecución rutinaria del scanner.

El análisis es estático y usa las fuentes Terraform sin valores privados ni plan real; no resuelve completamente dependencias entre states. No acredita un despliegue, ausencia de vulnerabilidades lógicas, seguridad de una cuenta AWS ni pruebas de penetración. El gate aprobado describe únicamente las reglas, paquetes, severidades y base consultados en esa ejecución.

Las ejecuciones remotas del gate se consultan en [GitHub Actions](https://github.com/dannyfriz/aws-ecommerce-agent-demo/actions). El resumen publicado describe su propia ejecución; la validación de una copia nueva debe generar evidencia nueva en `.build/security/`.
