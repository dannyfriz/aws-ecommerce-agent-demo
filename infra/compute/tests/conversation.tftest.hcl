# Estas pruebas verifican los controles sin crear memorias, índices ni filtros en AWS.
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
  values = { outputs = {
    kms_key_arn                = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
    frontend_bucket_name       = "example-web"
    frontend_url               = "https://example.cloudfront.net"
    user_pool_id               = "us-east-1_example"
    user_pool_client_id        = "exampleclient"
    cognito_issuer             = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
    cognito_domain             = "https://example.auth.us-east-1.amazoncognito.com"
    oauth_scope                = "ecommerce-agent/access"
    cloudfront_distribution_id = "EXAMPLE"
  } }
}
override_data {
  target = data.terraform_remote_state.data
  values = { outputs = {
    orders_table_name = "orders"
    orders_table_arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/orders"
    audit_table_name  = "audit"
    audit_table_arn   = "arn:aws:dynamodb:us-east-1:123456789012:table/audit"
  } }
}

variables {
  expected_account_id        = "123456789012"
  state_bucket               = "test-state"
  backend_zip_path           = "backend.tf"
  enable_conversation_memory = true
  enable_preference_memory   = true
  enable_policy_knowledge    = true
  enable_content_guardrails  = true
}

run "memoria_y_conocimiento_cifrados_y_acotados" {
  command = plan
  assert {
    condition     = aws_bedrockagentcore_memory.conversation[0].encryption_key_arn == local.foundation.kms_key_arn && aws_bedrockagentcore_memory.preferences[0].encryption_key_arn == local.foundation.kms_key_arn && aws_bedrockagentcore_memory.conversation[0].event_expiry_duration == 7 && var.memory_context_ttl_seconds == 900
    error_message = "La memoria debe usar CMK y separar retención física de vigencia conversacional."
  }
  assert {
    condition     = aws_bedrock_guardrail.chat[0].kms_key_arn == local.foundation.kms_key_arn && aws_bedrock_guardrail_version.chat[0].skip_destroy && aws_s3vectors_index.policies[0].dimension == 1024 && aws_s3vectors_index.policies[0].encryption_configuration[0].kms_key_arn == local.foundation.kms_key_arn
    error_message = "Guardrails y el índice de conocimiento deben usar el cifrado configurado."
  }
  assert {
    condition     = aws_bedrockagent_knowledge_base.policies[0].storage_configuration[0].type == "S3_VECTORS" && aws_s3_bucket_public_access_block.policies[0].block_public_policy && aws_s3_bucket_public_access_block.policies[0].restrict_public_buckets
    error_message = "El conocimiento usa solo la fuente privada y el índice explícito."
  }
  assert {
    condition     = alltrue([for name in ["AGENTCORE_MEMORY_ID", "AGENTCORE_PREFERENCES_MEMORY_ID", "CONTENT_GUARDRAIL_VERSION", "POLICY_KNOWLEDGE_BASE_ID"] : contains(keys(aws_lambda_function.backend.environment[0].variables), name)]) && !contains(keys(aws_lambda_function.tools[0].environment[0].variables), "AGENTCORE_MEMORY_ID")
    error_message = "Solo el backend debe recibir las nuevas capacidades; las herramientas no consultan memoria."
  }
}

run "ttl_de_contexto_excesivo_rechazado" {
  command = plan
  variables { memory_context_ttl_seconds = 86400 }
  expect_failures = [var.memory_context_ttl_seconds]
}

run "preferencias_usan_lectura_por_id_y_namespace_acotado" {
  command = plan
  override_resource {
    target          = aws_bedrockagentcore_memory.preferences[0]
    override_during = plan
    values          = { arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/ecommerce_agent_demo_preferences-abcdefghij" }
  }
  assert {
    condition     = contains(one([for statement in jsondecode(aws_iam_role_policy.backend_preferences[0].policy).Statement : statement if statement.Sid == "PreferenciasDeEsteAmbiente"]).Action, "bedrock-agentcore:GetMemoryRecord") && one([for statement in jsondecode(aws_iam_role_policy.backend_preferences[0].policy).Statement : statement if statement.Sid == "PreferenciasDeEsteAmbiente"]).Resource == "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/ecommerce_agent_demo_preferences-abcdefghij"
    error_message = "La lectura vigente de preferencias debe usar GetMemoryRecord sobre la memoria explícita."
  }
  assert {
    condition     = one([for statement in jsondecode(aws_iam_role_policy.backend_preferences[0].policy).Statement : statement if statement.Sid == "PreferenciasDeEsteAmbiente"]).Condition.StringLike["bedrock-agentcore:namespace"] == "/preferences/demo-*/" && one([for statement in jsondecode(aws_iam_role_policy.backend_preferences[0].policy).Statement : statement if statement.Sid == "PreferenciasDeEsteAmbiente"]).Condition.Null["bedrock-agentcore:namespace"] == "false"
    error_message = "Toda lectura de preferencias debe conservar un namespace presente y acotado al ambiente."
  }
}
