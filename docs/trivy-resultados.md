## Análisis de seguridad

Trivy 0.76.1 · 2026-10-23T14:07:12.839903+00:00

Paquetes verificados: 9. Vulnerabilidades conocidas: 0. Secretos detectados: 0.

**Gate aprobado.** 0 hallazgos HIGH/CRITICAL; se incluyen vulnerabilidades sin corrección publicada.

| Severidad | Cantidad |
|---|---:|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 4 |
| UNKNOWN | 0 |

| Severidad | Tipo | ID | Archivo | Paquete | Versión | Corrección |
|---|---|---|---|---|---|---|
| LOW | Misconfigurations | AWS-0089 | infra/bootstrap/main.tf |  |  | Revisar configuración |
| MEDIUM | Misconfigurations | AWS-0065 | infra/compute/agentcore.tf |  |  | Revisar configuración |
| LOW | Misconfigurations | AWS-0066 | infra/compute/agentcore.tf |  |  | Revisar configuración |
| LOW | Misconfigurations | AWS-0066 | infra/compute/backend.tf |  |  | Revisar configuración |
| MEDIUM | Misconfigurations | AWS-0010 | infra/foundation/frontend.tf |  |  | Revisar configuración |
| LOW | Misconfigurations | AWS-0089 | infra/foundation/storage.tf |  |  | Revisar configuración |
