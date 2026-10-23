variable "enable_agentcore" {
  type        = bool
  default     = true
  description = "Habilita Gateway MCP con Policy ENFORCE y propagación firmada de identidad."
}

resource "aws_kms_key" "identity_mac" {
  count                    = var.enable_agentcore ? 1 : 0
  description              = "Integridad del contexto de identidad entre backend y herramientas"
  customer_master_key_spec = "HMAC_256"
  key_usage                = "GENERATE_VERIFY_MAC"
  deletion_window_in_days  = 30
  # KMS no admite rotación automática para claves HMAC; se rota mediante una clave nueva.
}

resource "aws_kms_alias" "identity_mac" {
  count         = var.enable_agentcore ? 1 : 0
  name          = "alias/${local.name}-identity-mac"
  target_key_id = aws_kms_key.identity_mac[0].key_id
}

resource "aws_cloudwatch_log_group" "tools" {
  count             = var.enable_agentcore ? 1 : 0
  name              = "/aws/${local.name}/tools"
  retention_in_days = 7
  kms_key_id        = local.foundation.kms_key_arn
}

resource "aws_iam_role" "tools" {
  count              = var.enable_agentcore ? 1 : 0
  name               = "${local.name}-tools"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "tools" {
  count = var.enable_agentcore ? 1 : 0
  name  = "HerramientasConIdentidadVerificada"
  role  = aws_iam_role.tools[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.tools[0].arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem"], Resource = local.tables.orders_table_arn },
    { Effect = "Allow", Action = "dynamodb:PutItem", Resource = local.tables.audit_table_arn },
    { Effect = "Allow", Action = "kms:VerifyMac", Resource = aws_kms_key.identity_mac[0].arn },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey", "kms:CreateGrant"], Resource = local.foundation.kms_key_arn, Condition = { StringEquals = { "kms:ViaService" = "dynamodb.${var.region}.amazonaws.com" } } },
    { Effect = "Allow", Action = "kms:Decrypt", Resource = local.foundation.kms_key_arn }
  ] })
}

resource "aws_lambda_function" "tools" {
  count                          = var.enable_agentcore ? 1 : 0
  function_name                  = "${local.name}-tools"
  role                           = aws_iam_role.tools[0].arn
  filename                       = var.backend_zip_path
  source_code_hash               = filebase64sha256(var.backend_zip_path)
  handler                        = "ecommerce_agent.gateway_handler.lambda_handler"
  runtime                        = "python3.14"
  architectures                  = ["arm64"]
  memory_size                    = 512
  timeout                        = 10
  reserved_concurrent_executions = var.lambda_reserved_concurrent_executions
  kms_key_arn                    = local.foundation.kms_key_arn
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.tools[0].name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }
  environment {
    variables = {
      MODE                 = "aws"
      ORDERS_TABLE         = local.tables.orders_table_name
      AUDIT_TABLE          = local.tables.audit_table_name
      AGENTCORE_MAC_KEY_ID = aws_kms_key.identity_mac[0].arn
      AUDIT_TTL_DAYS       = tostring(var.audit_ttl_days)
    }
  }
  depends_on = [aws_iam_role_policy.tools]
}

resource "aws_bedrockagentcore_policy_engine" "tools" {
  count              = var.enable_agentcore ? 1 : 0
  name               = "${replace(local.name, "-", "_")}_tools"
  description        = "Herramientas explícitas; la propiedad del pedido se verifica en el backend"
  encryption_key_arn = local.foundation.kms_key_arn
}

resource "aws_iam_role" "gateway" {
  count = var.enable_agentcore ? 1 : 0
  name  = "${local.name}-gateway"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = var.expected_account_id }, ArnLike = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.region}:${var.expected_account_id}:gateway/*" } }
  }] })
}

resource "aws_iam_role_policy" "gateway" {
  count = var.enable_agentcore ? 1 : 0
  name  = "InvocarSoloHerramientasYPolicy"
  role  = aws_iam_role.gateway[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.tools[0].arn },
    { Effect = "Allow", Action = "bedrock-agentcore:GetPolicyEngine", Resource = aws_bedrockagentcore_policy_engine.tools[0].policy_engine_arn },
    # El sufijo del Gateway se asigna al crear el recurso; nombre y tags limitan el bootstrap sin ciclos.
    { Effect = "Allow", Action = ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions"], Resource = [aws_bedrockagentcore_policy_engine.tools[0].policy_engine_arn, "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.region}:${var.expected_account_id}:gateway/${local.name}-tools-*"], Condition = { StringEquals = { "aws:ResourceTag/Project" = var.project, "aws:ResourceTag/Environment" = var.environment } } },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = local.foundation.kms_key_arn }
  ] })
}

resource "aws_bedrockagentcore_gateway" "tools" {
  count           = var.enable_agentcore ? 1 : 0
  name            = "${local.name}-tools"
  role_arn        = aws_iam_role.gateway[0].arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"
  kms_key_arn     = local.foundation.kms_key_arn
  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.tools[0].policy_engine_arn
    mode = "ENFORCE"
  }
  protocol_configuration {
    mcp { supported_versions = ["2026-07-28"] }
  }
  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "tools" {
  count              = var.enable_agentcore ? 1 : 0
  name               = "EcommerceTools"
  gateway_identifier = aws_bedrockagentcore_gateway.tools[0].gateway_id
  description        = "Consulta y solicitud de devolución; no incluye aprobación de reembolsos"
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.tools[0].arn
        tool_schema {
          dynamic "inline_payload" {
            for_each = {
              read_order     = "Consultar un pedido con identidad verificada"
              request_return = "Solicitar devolución de un pedido propio con identidad verificada"
            }
            content {
              name        = inline_payload.key
              description = inline_payload.value
              input_schema {
                type = "object"
                property {
                  name     = "order_id"
                  type     = "string"
                  required = true
                }
                property {
                  name     = "context"
                  type     = "object"
                  required = true
                  property {
                    name     = "mac"
                    type     = "string"
                    required = true
                  }
                  property {
                    name     = "payload"
                    type     = "object"
                    required = true
                    properties_json = jsonencode({
                      properties = {
                        sub        = { type = "string" }
                        role       = { type = "string" }
                        action     = { type = "string" }
                        order_id   = { type = "string" }
                        request_id = { type = "string" }
                        expires_at = { type = "integer" }
                        nonce      = { type = "string" }
                      }
                      required = ["sub", "role", "action", "order_id", "request_id", "expires_at", "nonce"]
                    })
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_bedrockagentcore_policy" "tools" {
  count            = var.enable_agentcore ? 1 : 0
  name             = "HerramientasDelBackend"
  policy_engine_id = aws_bedrockagentcore_policy_engine.tools[0].policy_engine_id
  validation_mode  = "FAIL_ON_ANY_FINDINGS"
  definition {
    cedar {
      statement = <<-CEDAR
        permit(
          principal is AgentCore::IamEntity,
          action in [AgentCore::Action::"EcommerceTools___read_order", AgentCore::Action::"EcommerceTools___request_return"],
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.tools[0].gateway_arn}"
        ) when {
          principal.id == "${aws_iam_role.backend.arn}" ||
          principal.id == "arn:${data.aws_partition.current.partition}:sts::${var.expected_account_id}:assumed-role/${aws_iam_role.backend.name}" ||
          principal.id like "arn:${data.aws_partition.current.partition}:sts::${var.expected_account_id}:assumed-role/${aws_iam_role.backend.name}/*"
        };
      CEDAR
    }
  }
  depends_on = [aws_bedrockagentcore_gateway_target.tools]
}

resource "aws_iam_role_policy" "backend_gateway" {
  count = var.enable_agentcore ? 1 : 0
  name  = "GatewayConContextoFirmado"
  role  = aws_iam_role.backend.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "bedrock-agentcore:InvokeGateway", Resource = aws_bedrockagentcore_gateway.tools[0].gateway_arn },
    { Effect = "Allow", Action = "kms:GenerateMac", Resource = aws_kms_key.identity_mac[0].arn }
  ] })
}

output "agentcore_gateway_url" {
  value = var.enable_agentcore ? aws_bedrockagentcore_gateway.tools[0].gateway_url : null
}
output "agentcore_policy_engine_id" {
  value = var.enable_agentcore ? aws_bedrockagentcore_policy_engine.tools[0].policy_engine_id : null
}
