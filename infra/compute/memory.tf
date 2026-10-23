variable "enable_conversation_memory" {
  type        = bool
  default     = false
  description = "Activa contexto mínimo de sesión en AgentCore Memory; no almacena conversaciones completas."
}

variable "memory_context_ttl_seconds" {
  type        = number
  default     = 900
  description = "Vigencia lógica del pedido recordado; no equivale a la retención física de eventos."
  validation {
    condition     = var.memory_context_ttl_seconds >= 60 && var.memory_context_ttl_seconds <= 1800 && floor(var.memory_context_ttl_seconds) == var.memory_context_ttl_seconds
    error_message = "Usa un entero entre 60 y 1800 segundos para el contexto de la conversación."
  }
}

# El provider exige al menos siete días físicos; la aplicación deja de usar el contexto al vencer su TTL.
# No se configuran estrategias de largo plazo ni un rol de inferencia para extraer información.
resource "aws_bedrockagentcore_memory" "conversation" {
  count                 = var.enable_conversation_memory ? 1 : 0
  name                  = "${replace(local.name, "-", "_")}_conversation"
  description           = "Referencia mínima de pedido por usuario y conversación; sin prompts ni decisiones de acceso"
  event_expiry_duration = 7
  encryption_key_arn    = local.foundation.kms_key_arn
}

resource "aws_iam_role_policy" "backend_memory" {
  count = var.enable_conversation_memory ? 1 : 0
  name  = "ContextoConversacionAcotado"
  role  = aws_iam_role.backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EventosDeEsteAmbiente"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents"]
        Resource = aws_bedrockagentcore_memory.conversation[0].arn
        Condition = {
          StringLike = { "bedrock-agentcore:actorId" = "${var.environment}-*" }
          Null       = { "bedrock-agentcore:sessionId" = "false" }
        }
      },
      {
        Sid       = "CifradoContextoAgentCore"
        Effect    = "Allow"
        Action    = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = local.foundation.kms_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "bedrock-agentcore.${var.region}.amazonaws.com" } }
      }
    ]
  })
}

output "conversation_memory_id" {
  value = var.enable_conversation_memory ? aws_bedrockagentcore_memory.conversation[0].id : null
}

variable "enable_preference_memory" {
  type        = bool
  default     = false
  description = "Conserva solo idioma y nivel de detalle elegidos explícitamente por el usuario."
}

# La retención de eventos no se usa: las preferencias son registros directos con TTL de 31 días por solicitud.
resource "aws_bedrockagentcore_memory" "preferences" {
  count                 = var.enable_preference_memory ? 1 : 0
  name                  = "${replace(local.name, "-", "_")}_preferences"
  description           = "Preferencias explícitas de idioma y detalle; sin pedidos, roles ni conversaciones"
  event_expiry_duration = 7
  encryption_key_arn    = local.foundation.kms_key_arn
}

resource "aws_iam_role_policy" "backend_preferences" {
  count = var.enable_preference_memory ? 1 : 0
  name  = "PreferenciasExplicitasAcotadas"
  role  = aws_iam_role.backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PreferenciasDeEsteAmbiente"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:BatchCreateMemoryRecords", "bedrock-agentcore:BatchUpdateMemoryRecords", "bedrock-agentcore:ListMemoryRecords", "bedrock-agentcore:GetMemoryRecord"]
        Resource = aws_bedrockagentcore_memory.preferences[0].arn
        Condition = {
          StringLike = { "bedrock-agentcore:namespace" = "/preferences/${var.environment}-*/" }
          Null       = { "bedrock-agentcore:namespace" = "false" }
        }
      },
      {
        Sid      = "RetencionDePreferencias"
        Effect   = "Allow"
        Action   = "bedrock-agentcore:UpdateMemoryRecordExpirySpecification"
        Resource = aws_bedrockagentcore_memory.preferences[0].arn
      },
      {
        Sid       = "CifradoPreferenciasAgentCore"
        Effect    = "Allow"
        Action    = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = local.foundation.kms_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "bedrock-agentcore.${var.region}.amazonaws.com" } }
      }
    ]
  })
}

output "preferences_memory_id" {
  value = var.enable_preference_memory ? aws_bedrockagentcore_memory.preferences[0].id : null
}
