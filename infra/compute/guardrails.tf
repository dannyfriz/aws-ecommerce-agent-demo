variable "enable_content_guardrails" {
  type        = bool
  default     = false
  description = "Filtra el contenido del chat; no reemplaza la autorización sobre pedidos."
}

locals {
  # El perfil US está documentado para estos destinos desde las tres regiones verificadas.
  guardrail_profile_id      = "us.guardrail.v1:0"
  guardrail_profile_regions = ["us-east-1", "us-east-2", "us-west-2"]
  guardrail_profile_arn     = "arn:${data.aws_partition.current.partition}:bedrock:${var.region}:${var.expected_account_id}:guardrail-profile/${local.guardrail_profile_id}"
  guardrail_profile_arns    = [for region in local.guardrail_profile_regions : "arn:${data.aws_partition.current.partition}:bedrock:${region}:${var.expected_account_id}:guardrail-profile/${local.guardrail_profile_id}"]
}

resource "aws_bedrock_guardrail" "chat" {
  count                     = var.enable_content_guardrails ? 1 : 0
  name                      = "${local.name}-content"
  description               = "Contenido sensible y ataques al prompt; permisos externos al modelo"
  kms_key_arn               = local.foundation.kms_key_arn
  blocked_input_messaging   = "Reformula la consulta sin información sensible ni instrucciones para evadir controles."
  blocked_outputs_messaging = "La respuesta fue bloqueada por el filtro de contenido."
  cross_region_config {
    guardrail_profile_identifier = local.guardrail_profile_arn
  }
  content_policy_config {
    tier_config = [{ tier_name = "STANDARD" }]
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }
  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = toset(["EMAIL", "PHONE", "PASSWORD", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "CREDIT_DEBIT_CARD_NUMBER"])
      content {
        type   = pii_entities_config.value
        action = "BLOCK"
      }
    }
  }
  lifecycle {
    precondition {
      condition     = contains(local.guardrail_profile_regions, var.region) && data.aws_partition.current.partition == "aws"
      error_message = "El perfil Standard de esta demo se verificó en us-east-1, us-east-2 y us-west-2 de la partición AWS comercial. Verifica otro perfil y sus destinos antes de cambiar la región."
    }
  }
}

resource "aws_bedrock_guardrail_version" "chat" {
  count         = var.enable_content_guardrails ? 1 : 0
  guardrail_arn = aws_bedrock_guardrail.chat[0].guardrail_arn
  description   = "Configuración ${sha256(jsonencode({ content = aws_bedrock_guardrail.chat[0].content_policy_config, sensitive = aws_bedrock_guardrail.chat[0].sensitive_information_policy_config, cross_region = aws_bedrock_guardrail.chat[0].cross_region_config }))}"
  skip_destroy  = true
}

resource "aws_iam_role_policy" "backend_guardrail" {
  count = var.enable_content_guardrails ? 1 : 0
  name  = "FiltrarContenidoConVersionPublicada"
  role  = aws_iam_role.backend.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = "bedrock:ApplyGuardrail",
    Resource = concat([aws_bedrock_guardrail.chat[0].guardrail_arn], local.guardrail_profile_arns)
  }] })
}

output "content_guardrail_id" {
  value = var.enable_content_guardrails ? aws_bedrock_guardrail.chat[0].guardrail_id : null
}

output "content_guardrail_version" {
  value = var.enable_content_guardrails ? aws_bedrock_guardrail_version.chat[0].version : null
}
