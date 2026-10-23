# Estas pruebas usan proveedores simulados: no crean recursos ni llaman a AWS.
mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012", arn = "arn:aws:iam::123456789012:root", user_id = "test" }
}
override_data {
  target = data.aws_partition.current
  values = { partition = "aws", dns_suffix = "amazonaws.com" }
}
override_data {
  target = data.terraform_remote_state.foundation
  values = {
    outputs = {
      kms_key_arn                = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
      frontend_bucket_name       = "ecommerce-agent-demo-web-123456789012"
      frontend_url               = "https://example.cloudfront.net"
      user_pool_id               = "us-east-1_example"
      user_pool_client_id        = "exampleclient"
      cognito_issuer             = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
      cognito_domain             = "https://example.auth.us-east-1.amazoncognito.com"
      oauth_scope                = "ecommerce-agent/access"
      cloudfront_distribution_id = "EXAMPLE"
    }
  }
}
override_data {
  target = data.terraform_remote_state.data
  values = {
    outputs = {
      orders_table_name = "orders"
      orders_table_arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/orders"
      audit_table_name  = "audit"
      audit_table_arn   = "arn:aws:dynamodb:us-east-1:123456789012:table/audit"
    }
  }
}

variables {
  expected_account_id = "123456789012"
  state_bucket        = "test-state"
  # Solo se calcula un hash de contenido; el mock nunca despliega esta entrada.
  backend_zip_path = "backend.tf"
}

run "autorizacion_y_gateway_obligatorios" {
  command = plan
  assert {
    condition     = aws_apigatewayv2_route.health.route_key == "GET /api/health" && aws_apigatewayv2_route.health.authorization_type == "NONE" && length(aws_apigatewayv2_route.routes) == 8
    error_message = "Solo el estado mínimo es público; las ocho rutas de negocio conservan JWT."
  }
  assert {
    condition     = aws_bedrockagentcore_gateway.tools[0].authorizer_type == "AWS_IAM" && aws_bedrockagentcore_gateway.tools[0].policy_engine_configuration[0].mode == "ENFORCE"
    error_message = "Gateway debe autenticar con IAM y aplicar las decisiones de Policy."
  }
  assert {
    condition     = alltrue([for route in aws_apigatewayv2_route.routes : route.authorization_type == "JWT" && contains(route.authorization_scopes, "ecommerce-agent/access")])
    error_message = "Todas las rutas deben exigir JWT y scope de acceso."
  }
  assert {
    condition     = aws_lambda_function.backend.reserved_concurrent_executions == 3 && aws_lambda_function.tools[0].reserved_concurrent_executions == 3
    error_message = "La concurrencia debe estar limitada para el laboratorio."
  }
  assert {
    condition     = aws_bedrockagentcore_policy.tools[0].validation_mode == "FAIL_ON_ANY_FINDINGS"
    error_message = "No se permite ignorar hallazgos de validación Cedar."
  }
  assert {
    condition     = contains(aws_bedrockagentcore_gateway.tools[0].protocol_configuration[0].mcp[0].supported_versions, "2026-07-28")
    error_message = "La versión MCP del Gateway debe coincidir con el cliente stateless."
  }
  assert {
    condition     = aws_lambda_function.backend.runtime == "python3.14" && aws_lambda_function.tools[0].runtime == "python3.14"
    error_message = "Ambas funciones deben usar el runtime estable verificado."
  }
  assert {
    condition     = var.bedrock_model_id == "us.amazon.nova-2-lite-v1:0" && length(local.model_arns) == 4 && contains(local.model_arns, "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.amazon.nova-2-lite-v1:0") && alltrue([for arn in local.model_arns : !strcontains(arn, "*")])
    error_message = "Nova 2 Lite necesita el perfil explícito y los tres modelos de destino, sin comodines."
  }
}

run "cuota_compartida_es_explicita_para_laboratorio" {
  command = plan
  variables { lambda_reserved_concurrent_executions = -1 }
  assert {
    condition     = aws_lambda_function.backend.reserved_concurrent_executions == -1 && aws_lambda_function.tools[0].reserved_concurrent_executions == -1 && aws_apigatewayv2_stage.default.default_route_settings[0].throttling_rate_limit == 2
    error_message = "El modo compartido debe aplicarse a ambas funciones y conservar el throttle de la API."
  }
}

run "modo_sin_gateway_es_explicito" {
  command = plan
  variables { enable_agentcore = false }
  assert {
    condition     = length(aws_bedrockagentcore_gateway.tools) == 0 && !contains(keys(aws_lambda_function.backend.environment[0].variables), "AGENTCORE_GATEWAY_URL")
    error_message = "Deshabilitar AgentCore debe retirar la configuración del backend."
  }
}

run "dominio_api_regional_y_migracion_explicita" {
  command = plan
  variables {
    api_domain_name       = "api-dev.example.com"
    api_certificate_arn   = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-1111-1111-1111-111111111111"
    use_custom_api_domain = true
  }
  assert {
    condition     = aws_apigatewayv2_domain_name.api[0].domain_name_configuration[0].security_policy == "TLS_1_2" && aws_apigatewayv2_api_mapping.api[0].domain_name == var.api_domain_name && jsondecode(trimprefix(trimsuffix(aws_s3_object.config.content, ";"), "window.APP_CONFIG = ")).apiBaseUrl == "https://api-dev.example.com"
    error_message = "La API personalizada debe mapearse al stage y publicarse en config.js con TLS regional."
  }
}

run "dev_consume_ambas_capas_dev" {
  command = plan
  variables { environment = "dev" }
  assert {
    condition     = data.terraform_remote_state.foundation.config.key == "dev/foundation/terraform.tfstate" && data.terraform_remote_state.data.config.key == "dev/data/terraform.tfstate"
    error_message = "Compute debe consumir ambos states de su propio ambiente."
  }
}

run "rechaza_foundation_de_otro_ambiente" {
  command = plan
  variables {
    environment          = "dev"
    foundation_state_key = "demo/foundation/terraform.tfstate"
  }
  expect_failures = [data.terraform_remote_state.foundation]
}

run "rechaza_data_de_otro_ambiente" {
  command = plan
  variables {
    environment    = "dev"
    data_state_key = "demo/data/terraform.tfstate"
  }
  expect_failures = [data.terraform_remote_state.data]
}

run "bandeja_permisos_minimos" {
  command = plan
  override_resource {
    target          = aws_cloudwatch_log_group.lambda
    values          = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:backend" }
    override_during = plan
  }
  override_resource {
    target          = aws_cloudwatch_log_group.tools[0]
    values          = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:tools" }
    override_during = plan
  }
  override_resource {
    target          = aws_kms_key.identity_mac[0]
    values          = { arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111" }
    override_during = plan
  }
  override_resource {
    target          = aws_bedrock_inference_profile.project
    values          = { arn = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/test" }
    override_during = plan
  }
  assert {
    condition     = one([for statement in jsondecode(aws_iam_role_policy.backend.policy).Statement : statement if statement.Sid == "BandejaSolicitudes"]).Resource == "arn:aws:dynamodb:us-east-1:123456789012:table/orders/index/return_status-order_id" && !strcontains(aws_iam_role_policy.tools[0].policy, "dynamodb:Query")
    error_message = "Solo el backend consulta el indice de pendientes; las herramientas no reciben ese permiso."
  }
}
