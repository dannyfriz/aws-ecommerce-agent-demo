mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
}
mock_provider "aws" {
  alias = "us_east_1"
}

variables {
  expected_account_id  = "123456789012"
  environment          = "dev"
  frontend_domain_name = "tienda-dev.example.com"
  api_domain_name      = "api-dev.example.com"
  acm_certificate_arn  = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-1111-1111-1111-111111111111"
}

run "custom_domain_uses_certificate_and_callback" {
  command = plan
  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.web.security_headers_config[0].content_security_policy[0].content_security_policy, " https://${var.api_domain_name};")
    error_message = "La CSP debe autorizar explícitamente el origen personalizado de la API."
  }
  assert {
    condition     = aws_cloudfront_distribution.web.aliases == toset([var.frontend_domain_name]) && aws_cloudfront_distribution.web.viewer_certificate[0].acm_certificate_arn == var.acm_certificate_arn
    error_message = "CloudFront debe usar el hostname y el certificado configurados."
  }
  assert {
    condition     = aws_cognito_user_pool_client.web.callback_urls == toset(["https://${var.frontend_domain_name}/"])
    error_message = "El callback de Cognito debe coincidir con el dominio HTTPS."
  }
}

run "reject_certificate_from_another_account" {
  command = plan
  variables {
    acm_certificate_arn = "arn:aws:acm:us-east-1:999999999999:certificate/11111111-1111-1111-1111-111111111111"
  }
  expect_failures = [aws_cloudfront_distribution.web]
}

run "custom_auth_preserves_prefix_and_uses_existing_certificate" {
  command = plan
  variables {
    auth_domain_name       = "auth.example.com"
    auth_certificate_arn   = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-1111-1111-1111-111111111111"
    use_custom_auth_domain = true
  }
  assert {
    condition     = aws_cognito_user_pool_domain.custom[0].domain == "auth.example.com" && aws_cognito_user_pool_domain.custom[0].managed_login_version == 1 && aws_cognito_user_pool_domain.users.domain == "ecommerce-agent-dev-123456789012" && output.cognito_domain == "https://auth.example.com"
    error_message = "El dominio personalizado debe conservar el prefijo y activar únicamente la URL elegida."
  }
  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.web.security_headers_config[0].content_security_policy[0].content_security_policy, " https://auth.example.com")
    error_message = "La CSP debe permitir el endpoint OAuth personalizado."
  }
}

run "reject_certificate_from_another_region" {
  command = plan
  variables {
    acm_certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/11111111-1111-1111-1111-111111111111"
  }
  expect_failures = [aws_cloudfront_distribution.web]
}
