# Versiones estables y procedencia

Consulta de fuentes oficiales realizada el **22 de octubre de 2026**. La intención es usar la última versión estable disponible al preparar esta entrega, con referencias reproducibles. No usar etiquetas flotantes para seleccionar una versión durante CI ni confundir estabilidad con pertenencia a una rama LTS.

| Componente | Versión seleccionada | Fuente oficial |
|---|---|---|
| Python estable upstream | 3.15.1 | [Publicación de Python](https://www.python.org/downloads/release/python-3151/) |
| Python base de desarrollo/empaquetado | 3.14.9 | [Publicación del parche](https://www.python.org/downloads/release/python-3149/) |
| Runtime Lambda Python GA | python3.14 | [Runtimes administrados de AWS](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) |
| Node.js | 26.12.1 Current | [Índice de releases](https://nodejs.org/download/release/index.json) y [distribución](https://nodejs.org/en/download/archive/v26.12.1) |
| Terraform | 1.17.0 | [Release de HashiCorp](https://github.com/hashicorp/terraform/releases/tag/v1.17.0) |
| AWS provider | 6.70.0 | [Release del provider](https://github.com/hashicorp/terraform-provider-aws/releases/tag/v6.70.0) |
| PowerShell | 7.6.8 | [Release de PowerShell](https://github.com/PowerShell/PowerShell/releases/tag/v7.6.8) |
| Trivy | 0.76.1 | [Release oficial](https://github.com/aquasecurity/trivy/releases/tag/v0.76.1) |
| npm | 12.2.1 | [Registro oficial](https://registry.npmjs.org/npm/latest) |
| pip | 26.2.2 | [PyPI](https://pypi.org/project/pip/26.2.2/) |
| Git for Windows | 2.56.0.windows.3 | [Release oficial](https://github.com/git-for-windows/git/releases/latest) |
| AWS CLI v2 | 2.38.5 | [CHANGELOG oficial](https://github.com/aws/aws-cli/blob/v2/CHANGELOG.rst) |
| Runner de CI | ubuntu-26.04 | [Disponibilidad general anunciada por GitHub](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/) |

Node 26.12.1 es estable en la rama Current. Se eligió Current porque el requisito es la última estable.

Node incluye npm 11.20.0, anterior a npm 12.2.1. `package.json` fija npm 12.2.1 y CI lo instala explícitamente. El frontend usa JavaScript sin framework y no incorpora dependencias npm de ejecución.

Dependencias PyPI verificadas: boto3 y botocore 1.43.118, jmespath 1.1.0, s3transfer 0.19.3, python-dateutil 2.9.0.post0, six 1.17.0 y urllib3 2.8.0. `requirements.lock` fija cada versión y su hash; `build-requirements.lock` fija setuptools 84.2.1, también por hash. python-dateutil 3.0.0 es la última upstream, pero botocore 1.43.118 exige `python-dateutil<3.0.0,>=2.1`. Se mantiene 2.9.0.post0 como última estable compatible. El auditor verifica la restricción en la metadata oficial de botocore, calcula la última release compatible no retirada de PyPI y reporta ambas versiones; si cambia la restricción, exige revisar la excepción.

El modelo predeterminado es Nova 2 Lite mediante el inference profile `us.amazon.nova-2-lite-v1:0`; [AWS documenta su soporte](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html). Su identificador es una versión de modelo y no una dependencia de PyPI. IAM incluye los destinos explícitos del perfil. CloudFront con dominio propio usa `TLSv1.3_2025`; el certificado predeterminado mantiene la limitación del servicio documentada en la infraestructura.

## Verificación continua

Ejecutar `& ".\scripts\Check-Versions.ps1"` desde la raíz antes de modificar dependencias o desplegar. El auditor consulta fuentes primarias en vivo, comprueba las últimas estables y contrasta los pins reales del repositorio, los hashes de wheels y los SHA de las actions. Si falla una fuente, no declara la verificación aprobada. Si aparece una nueva estable, falla hasta completar actualización, revisión de compatibilidad y pruebas. No modifica archivos ni instala paquetes automáticamente.

CI exige este control en la entrada Python 3.14.9. La matriz adicional 3.15.1 ejecuta las pruebas de compatibilidad. Cada consulta nueva se guarda en `.build/version-audit.json`, fuera del repositorio. Las versiones operativas de AWS CLI y Git se verifican por sus publicaciones; la consulta de versiones no demuestra un despliegue ni una publicación con ellas.

**Lenguaje estable y runtime administrado son estados distintos:** Python 3.15.1 es estable, pero el runtime `python3.15` de Lambda todavía figura como public preview en la [tabla oficial de AWS](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html). Lo mismo ocurre con Node.js 26 en Lambda; aquí Node solo ejecuta pruebas del frontend. La última rama Python generalmente disponible en Lambda es `python3.14`: es la elegida para desplegar. `.python-version` fija 3.14.9 y CI ejecuta una matriz 3.14.9/3.15.1 para comprobar compatibilidad con la base y con la última estable upstream. No se afirma soporte GA de Lambda 3.15. AWS administra los parches internos de `python3.14`; la selección del runtime no permite fijar exactamente su parche a 3.14.9.

Ubuntu 26.04 dejó la vista previa el 17 de septiembre de 2026. Se fija su etiqueta en lugar de `ubuntu-latest`, cuya migración es gradual. La etiqueta de sistema operativo no fija el contenido completo de la imagen: GitHub sigue actualizándola. Consultar el log «Set up job» para conocer la imagen concreta de cada ejecución.

## Actions fijadas por commit

Se consultó `GET /repos/{owner}/{repo}/releases/latest`, se verificó que la release no fuera preliminar y se resolvió su tag hasta el commit, siguiendo los tags anotados cuando correspondía.

| Action | Release estable | Commit usado en CI |
|---|---|---|
| actions/checkout | [v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| actions/setup-python | [v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0) | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| actions/setup-node | [v7.1.0](https://github.com/actions/setup-node/releases/tag/v7.1.0) | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| hashicorp/setup-terraform | [v4.0.1](https://github.com/hashicorp/setup-terraform/releases/tag/v4.0.1) | `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |

La actualización conserva `permissions: contents: read`; no agrega credenciales ni permisos de despliegue a CI. Los archivos `.python-version`, `.node-version` y `.terraform-version` expresan la selección local. CI fija esas versiones y añade Python 3.15.1 como segunda entrada de compatibilidad.

## Actualización y validación

Dependabot revisa semanalmente actions, dependencias Python y las cuatro raíces Terraform. Las actualizaciones de Python deben regenerar el lock con hashes de forma coherente con los manifiestos; no se presume que Dependabot sepa mantener un archivo de lock personalizado. No se habilita merge automático.

Al actualizar: consultar la release estable oficial, resolver su commit cuando aplique, renovar locks, revisar deprecaciones y volver a ejecutar pruebas de backend, frontend, empaquetado y validación Terraform. La consulta de versiones y actualización de CI **no demuestra por sí sola** una ejecución local exitosa con los nuevos runtimes ni un job ejecutado en GitHub. El despliegue real AWS continúa siendo una verificación distinta.
