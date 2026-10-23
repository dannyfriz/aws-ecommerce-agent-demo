resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/${local.name}/lambda"
  retention_in_days = 7
  kms_key_id        = local.foundation.kms_key_arn
}
resource "aws_iam_role" "backend" {
  name               = "${local.name}-backend"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "backend" {
  name = "AccesosMinimos"
  role = aws_iam_role.backend.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Sid = "EscribirLogsPropios", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda.arn}:*" },
      { Sid = "Pedidos", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"], Resource = local.tables.orders_table_arn },
      { Sid = "BandejaSolicitudes", Effect = "Allow", Action = ["dynamodb:Query"], Resource = "${local.tables.orders_table_arn}/index/return_status-order_id" },
      { Sid = "Evidencias", Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:Query"], Resource = local.tables.audit_table_arn },
      { Sid = "ModeloExplicito", Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = concat(local.model_arns, [aws_bedrock_inference_profile.project.arn]) },
      { Sid = "CifradoDynamoDB", Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey", "kms:CreateGrant"], Resource = local.foundation.kms_key_arn, Condition = { StringEquals = { "kms:ViaService" = "dynamodb.${var.region}.amazonaws.com" } } },
      { Sid = "VariablesLambdaCifradas", Effect = "Allow", Action = "kms:Decrypt", Resource = local.foundation.kms_key_arn }
  ] })
}
resource "aws_lambda_function" "backend" {
  function_name                  = "${local.name}-backend"
  role                           = aws_iam_role.backend.arn
  filename                       = var.backend_zip_path
  source_code_hash               = filebase64sha256(var.backend_zip_path)
  handler                        = "ecommerce_agent.handler.lambda_handler"
  runtime                        = "python3.14"
  architectures                  = ["arm64"]
  memory_size                    = 1024
  timeout                        = 29
  reserved_concurrent_executions = var.lambda_reserved_concurrent_executions
  kms_key_arn                    = local.foundation.kms_key_arn
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.lambda.name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }
  environment { variables = merge({
    MODE             = "aws", ORDERS_TABLE = local.tables.orders_table_name, AUDIT_TABLE = local.tables.audit_table_name,
    BEDROCK_MODEL_ID = aws_bedrock_inference_profile.project.arn, MODEL_REGION = var.model_region,
    AUDIT_TTL_DAYS   = tostring(var.audit_ttl_days), APP_NAME = local.name
    }, var.enable_agentcore ? { AGENTCORE_GATEWAY_URL = aws_bedrockagentcore_gateway.tools[0].gateway_url, AGENTCORE_MAC_KEY_ID = aws_kms_key.identity_mac[0].arn } : {},
    var.enable_conversation_memory ? { AGENTCORE_MEMORY_ID = aws_bedrockagentcore_memory.conversation[0].id,
    MEMORY_CONTEXT_TTL_SECONDS = tostring(var.memory_context_ttl_seconds) } : {},
    var.enable_conversation_memory || var.enable_preference_memory ? { MEMORY_ENVIRONMENT = var.environment } : {},
    var.enable_preference_memory ? { AGENTCORE_PREFERENCES_MEMORY_ID = aws_bedrockagentcore_memory.preferences[0].id } : {},
    var.enable_content_guardrails ? { CONTENT_GUARDRAIL_ID = aws_bedrock_guardrail.chat[0].guardrail_id,
    CONTENT_GUARDRAIL_VERSION = aws_bedrock_guardrail_version.chat[0].version } : {},
    var.enable_policy_knowledge ? { POLICY_KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.policies[0].id,
  POLICY_KNOWLEDGE_SOURCE_URI = "s3://${aws_s3_bucket.policies[0].bucket}/${local.policy_document_key}" } : {}) }
  depends_on = [aws_iam_role_policy.backend, aws_iam_role_policy.backend_gateway, aws_bedrockagentcore_policy.tools,
  aws_iam_role_policy.backend_memory, aws_iam_role_policy.backend_preferences, aws_iam_role_policy.backend_guardrail, aws_iam_role_policy.backend_knowledge]
  lifecycle {
    precondition {
      condition     = length(var.bedrock_model_arns) > 0 || (var.bedrock_model_id == "us.amazon.nova-2-lite-v1:0" && var.model_region == "us-east-1")
      error_message = "Otro modelo o región requiere bedrock_model_arns explícitos y verificados para evitar permisos incompletos."
    }
  }
}
