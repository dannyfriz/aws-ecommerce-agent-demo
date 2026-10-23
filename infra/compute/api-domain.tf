variable "api_domain_name" {
  type        = string
  default     = ""
  description = "Hostname opcional de la API regional."
  validation {
    condition     = var.api_domain_name == "" || can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.api_domain_name))
    error_message = "Indica un hostname sin protocolo ni rutas."
  }
}
variable "api_certificate_arn" {
  type        = string
  default     = ""
  description = "Certificado ACM existente en la misma cuenta y región que la API."
}
variable "use_custom_api_domain" {
  type        = bool
  default     = false
  description = "Activa la URL personalizada en el frontend después de verificar su DNS."
}
locals {
  api_url = var.use_custom_api_domain ? "https://${var.api_domain_name}" : aws_apigatewayv2_api.api.api_endpoint
}
resource "aws_apigatewayv2_domain_name" "api" {
  count       = var.api_domain_name != "" ? 1 : 0
  domain_name = var.api_domain_name
  domain_name_configuration {
    certificate_arn = var.api_certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
  lifecycle {
    precondition {
      condition     = can(regex("^arn:${data.aws_partition.current.partition}:acm:${var.region}:${var.expected_account_id}:certificate/[a-f0-9-]+$", var.api_certificate_arn))
      error_message = "El certificado de la API debe pertenecer a la misma cuenta y región."
    }
  }
}
resource "aws_apigatewayv2_api_mapping" "api" {
  count       = var.api_domain_name != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.api[0].domain_name
  stage       = aws_apigatewayv2_stage.default.id
}
output "api_dns_record" {
  value = var.api_domain_name != "" ? {
    name    = var.api_domain_name
    type    = "A"
    target  = aws_apigatewayv2_domain_name.api[0].domain_name_configuration[0].target_domain_name
    zone_id = aws_apigatewayv2_domain_name.api[0].domain_name_configuration[0].hosted_zone_id
  } : null
}
