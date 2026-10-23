variable "bedrock_cost_source_arn" {
  type        = string
  default     = null
  description = "ARN explícito del modelo o perfil fuente para atribuir costos de inferencia."
  validation {
    condition     = var.bedrock_cost_source_arn == null || can(regex("^arn:[^*]+$", var.bedrock_cost_source_arn))
    error_message = "Indica un ARN de modelo o perfil sin comodines."
  }
}
resource "aws_bedrock_inference_profile" "project" {
  name        = "${local.name}-costs"
  description = "Atribucion de inferencias al centro de costo del laboratorio"
  model_source {
    copy_from = coalesce(var.bedrock_cost_source_arn, startswith(var.bedrock_model_id, "arn:") ? var.bedrock_model_id : "arn:${data.aws_partition.current.partition}:bedrock:${var.model_region}:${var.expected_account_id}:inference-profile/${var.bedrock_model_id}")
  }
}
output "bedrock_application_profile_arn" {
  value = aws_bedrock_inference_profile.project.arn
}
