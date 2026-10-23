# Dominio HTTPS de desarrollo

Los dominios personalizados son opcionales. Los ejemplos usan `example.com`; reemplazarlos por un dominio propio y mantener sus valores reales en archivos locales excluidos de Git. Terraform referencia certificados ACM existentes y no administra su renovación ni la zona DNS.

## Frontend

En `foundation.tfvars`, configurar juntos `frontend_domain_name` y `acm_certificate_arn`. El certificado debe estar emitido en ACM `us-east-1`, pertenecer a la cuenta del despliegue y cubrir el hostname. Un wildcard `*.example.com` cubre `demo.example.com`, pero no `example.com` ni `demo.dev.example.com`. [Requisitos de CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html).

Aplicar las capas siguiendo [Operación](operacion.md). El output `frontend_dns_record` de foundation entrega el nombre y destino del registro. Configurar en Route 53 un A con Alias hacia la distribución indicada; en otro proveedor DNS puede usarse un CNAME para el subdominio. No apuntar el dominio al bucket S3 ni modificar los registros de validación de ACM.

Los callbacks y logout de Cognito, CORS y la configuración web se derivan de la URL HTTPS del frontend. Verificar que CloudFront termine de desplegarse y que el DNS resuelva antes de probar el ingreso.

## Dominio personalizado de Cognito

Foundation admite `auth_domain_name`, `auth_certificate_arn` y `use_custom_auth_domain`. El certificado debe estar emitido en ACM `us-east-1`, en la misma cuenta, y cubrir el hostname elegido, por ejemplo `auth.example.com`. El origen personalizado se incluye en CSP.

Cognito exige un registro A resoluble del dominio padre antes de crear el subdominio. Para `auth.example.com`, el padre es `example.com`. La [documentación de AWS](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-add-custom-domain.html) describe el requisito y permite un registro temporal de ejemplo cuando el padre no tiene un sitio. No reemplazar un registro de un servicio existente para cumplirlo.

Crear el dominio conservando `use_custom_auth_domain = false`. Después, consultar `auth_dns_record` en los outputs privados de foundation: entrega nombre, tipo A, Alias, destino CloudFront y hosted zone ID exactos para ese despliegue. Usar esos valores en Route 53, sin evaluar la salud del destino. No copiar el destino de otro laboratorio ni usar una IP de ejemplo como destino de `auth`.

Verificar DNS, HTTPS y estado del dominio Cognito; luego activar `use_custom_auth_domain = true` y aplicar foundation y compute para actualizar `cognito_domain` y `config.js`. El dominio con prefijo se conserva y el issuer JWT sigue vinculado al pool, independientemente del dominio de ingreso.

## Dominio personalizado de la API

Compute admite `api_domain_name` y `api_certificate_arn` para crear un dominio regional HTTP API con mapping raíz al stage existente. El certificado debe estar emitido, cubrir el hostname y pertenecer a la misma cuenta y región que la API. Foundation recibe el mismo `api_domain_name` para autorizar su origen en CSP. El recurso utiliza la política `TLS_1_2` requerida para mappings HTTP API.

Crear el dominio y su mapping conservando `use_custom_api_domain = false`. El output privado `api_dns_record` de compute entrega nombre, tipo A, Alias, destino regional y hosted zone ID. Configurar esos valores en Route 53. Después de comprobar DNS y HTTPS, activar `use_custom_api_domain = true` y aplicar compute: `api_url` y `config.js` apuntarán al hostname personalizado.

El dominio cambia la URL de acceso; las rutas de negocio conservan el authorizer JWT y el scope. `GET /api/health` sigue siendo la excepción pública mínima.

## Verificación

Guardar variables y outputs en `.build/` o en otra ubicación privada, nunca en el repositorio. Usar el mismo `environment` (`demo`, `dev` o `test`) en las cuatro capas y en los scripts. En data y compute, `state_bucket` debe corresponder al bucket creado por bootstrap.

Antes del despliegue, ejecutar `scripts/Check-Versions.ps1`. `scripts/Test-CloudPrerequisites.ps1` recibe `-Profile`, `-AccountId`, `-CertificateArn` y `-FrontendDomain` para comprobar sesión y certificado mediante consultas de lectura; no solicita ni exporta su clave privada.

Después de publicar DNS, comprobar certificado, ingreso, consulta permitida, rechazo de pedido ajeno, devolución y aprobación humana. La presencia de un ARN en un archivo no acredita que el certificado esté emitido ni vigente.