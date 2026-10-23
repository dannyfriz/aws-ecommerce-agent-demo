# Las pruebas usan proveedores simulados; no crean filtros ni llaman a AWS.
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
  expected_account_id       = "123456789012"
  state_bucket              = "test-state"
  backend_zip_path          = "backend.tf"
  enable_content_guardrails = true
}

run "standard_exige_perfil_us_y_cifrado" {
  command = plan
  assert {
    condition     = aws_bedrock_guardrail.chat[0].cross_region_config[0].guardrail_profile_identifier == "arn:aws:bedrock:us-east-1:123456789012:guardrail-profile/us.guardrail.v1:0" && aws_bedrock_guardrail.chat[0].content_policy_config[0].tier_config[0].tier_name == "STANDARD"
    error_message = "El nivel Standard requiere el perfil entre regiones US explícito."
  }
  assert {
    condition     = aws_bedrock_guardrail.chat[0].kms_key_arn == data.terraform_remote_state.foundation.outputs.kms_key_arn
    error_message = "La configuración del guardrail debe conservar la CMK del laboratorio."
  }
}

run "backend_solo_invoca_guardrail_y_tres_perfiles" {
  command = plan
  override_resource {
    target          = aws_bedrock_guardrail.chat[0]
    override_during = plan
    values          = { guardrail_arn = "arn:aws:bedrock:us-east-1:123456789012:guardrail/testguardrail" }
  }
  assert {
    condition = toset(jsondecode(aws_iam_role_policy.backend_guardrail[0].policy).Statement[0].Resource) == toset([
      "arn:aws:bedrock:us-east-1:123456789012:guardrail/testguardrail",
      "arn:aws:bedrock:us-east-1:123456789012:guardrail-profile/us.guardrail.v1:0",
      "arn:aws:bedrock:us-east-2:123456789012:guardrail-profile/us.guardrail.v1:0",
      "arn:aws:bedrock:us-west-2:123456789012:guardrail-profile/us.guardrail.v1:0"
    ]) && jsondecode(aws_iam_role_policy.backend_guardrail[0].policy).Statement[0].Action == "bedrock:ApplyGuardrail"
    error_message = "El backend solo necesita ApplyGuardrail sobre el filtro y sus destinos explícitos, sin comodines ni permisos de administración."
  }
}

run "otra_region_exige_verificar_su_perfil" {
  command = plan
  variables { region = "eu-west-1" }
  expect_failures = [aws_bedrock_guardrail.chat]
}
