output "kms_key_arn" { value = aws_kms_key.app.arn }
output "frontend_bucket_name" { value = aws_s3_bucket.web.id }
output "frontend_url" { value = local.frontend_url }
output "cloudfront_distribution_id" { value = aws_cloudfront_distribution.web.id }
output "cloudfront_domain_name" { value = aws_cloudfront_distribution.web.domain_name }
output "frontend_dns_record" {
  description = "Registro que debe configurarse en el proveedor DNS después del despliegue."
  value = var.frontend_domain_name != "" ? {
    name   = var.frontend_domain_name
    type   = "CNAME"
    target = aws_cloudfront_distribution.web.domain_name
  } : null
}
output "user_pool_id" { value = aws_cognito_user_pool.users.id }
output "user_pool_client_id" { value = aws_cognito_user_pool_client.web.id }
output "cognito_issuer" { value = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.users.id}" }
output "cognito_domain" {
  value = var.use_custom_auth_domain ? "https://${var.auth_domain_name}" : "https://${aws_cognito_user_pool_domain.users.domain}.auth.${var.region}.amazoncognito.com"
}
output "oauth_scope" { value = "${aws_cognito_resource_server.api.identifier}/access" }
