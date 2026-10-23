variable "auth_domain_name" {
  type        = string
  default     = ""
  description = "Dominio personalizado opcional para el ingreso y recuperación en Cognito."
  validation {
    condition     = var.auth_domain_name == "" || can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.auth_domain_name))
    error_message = "Indica un hostname sin protocolo ni rutas."
  }
}
variable "auth_certificate_arn" {
  type        = string
  default     = ""
  description = "Certificado ACM existente en us-east-1 que cubre el dominio Cognito."
}
variable "use_custom_auth_domain" {
  type        = bool
  default     = false
  description = "Activa el dominio personalizado en los outputs una vez verificado su DNS."
  validation {
    condition     = !var.use_custom_auth_domain || var.auth_domain_name != ""
    error_message = "Configura auth_domain_name antes de activar el dominio personalizado."
  }
}
resource "aws_cognito_user_pool_domain" "custom" {
  count                 = var.auth_domain_name != "" ? 1 : 0
  domain                = var.auth_domain_name
  user_pool_id          = aws_cognito_user_pool.users.id
  certificate_arn       = var.auth_certificate_arn
  managed_login_version = 1
  lifecycle {
    precondition {
      condition     = can(regex("^arn:${data.aws_partition.current.partition}:acm:us-east-1:${var.expected_account_id}:certificate/[a-f0-9-]+$", var.auth_certificate_arn))
      error_message = "Cognito requiere un certificado ACM en us-east-1 y en la cuenta esperada."
    }
  }
}
output "auth_dns_record" {
  value = var.auth_domain_name != "" ? {
    name    = var.auth_domain_name
    type    = "A"
    alias   = true
    target  = aws_cognito_user_pool_domain.custom[0].cloudfront_distribution
    zone_id = aws_cognito_user_pool_domain.custom[0].cloudfront_distribution_zone_id
  } : null
}
