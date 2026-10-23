resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/${local.name}/api"
  retention_in_days = 7
  kms_key_id        = local.foundation.kms_key_arn
}
resource "aws_apigatewayv2_api" "api" {
  name          = local.name
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = [local.foundation.frontend_url]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}
resource "aws_apigatewayv2_authorizer" "users" {
  api_id           = aws_apigatewayv2_api.api.id
  authorizer_type  = "JWT"
  name             = "CognitoAccessToken"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [local.foundation.user_pool_client_id]
    issuer   = local.foundation.cognito_issuer
  }
}
resource "aws_apigatewayv2_integration" "backend" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.backend.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}
resource "aws_apigatewayv2_route" "routes" {
  for_each             = toset(["GET /api/me", "GET /api/preferences", "POST /api/preferences", "GET /api/orders/{order_id}", "GET /api/refunds/pending", "POST /api/chat", "POST /api/tools", "POST /api/refunds/approve", "POST /api/orders/reset", "GET /api/audit"])
  api_id               = aws_apigatewayv2_api.api.id
  route_key            = each.value
  target               = "integrations/${aws_apigatewayv2_integration.backend.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.users.id
  authorization_scopes = [local.foundation.oauth_scope]
}
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format          = jsonencode({ requestId = "$context.requestId", routeKey = "$context.routeKey", status = "$context.status", responseLength = "$context.responseLength", integrationError = "$context.integrationErrorMessage" })
  }
}
resource "aws_apigatewayv2_route" "health" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "GET /api/health"
  target             = "integrations/${aws_apigatewayv2_integration.backend.id}"
  authorization_type = "NONE"
}
resource "aws_lambda_permission" "api" {
  statement_id  = "ApiAutenticada"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backend.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*/api/*"
}
output "api_url" {
  value = local.api_url
  precondition {
    condition     = !var.use_custom_api_domain || var.api_domain_name != ""
    error_message = "Configura el dominio antes de activar su URL."
  }
}
output "frontend_url" { value = local.foundation.frontend_url }
output "user_pool_id" { value = local.foundation.user_pool_id }
output "user_pool_client_id" { value = local.foundation.user_pool_client_id }
