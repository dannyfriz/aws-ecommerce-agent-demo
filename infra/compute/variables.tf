variable "lambda_reserved_concurrent_executions" {
  type        = number
  default     = 3
  description = "Reserva por función; -1 usa el cupo compartido en cuentas de laboratorio con cuota reducida, sin aislamiento por función."
  validation {
    condition     = var.lambda_reserved_concurrent_executions == -1 || (var.lambda_reserved_concurrent_executions >= 1 && var.lambda_reserved_concurrent_executions <= 3 && floor(var.lambda_reserved_concurrent_executions) == var.lambda_reserved_concurrent_executions)
    error_message = "Usa -1 para el cupo compartido o un entero de 1 a 3 para limitar cada función."
  }
}

variable "data_state_key" {
  type    = string
  default = null
}
data "terraform_remote_state" "data" {
  backend = "s3"
  config  = { bucket = var.state_bucket, key = coalesce(var.data_state_key, "${var.environment}/data/terraform.tfstate"), region = var.state_region, encrypt = true }
  lifecycle {
    precondition {
      condition     = startswith(coalesce(var.data_state_key, "${var.environment}/data/terraform.tfstate"), "${var.environment}/")
      error_message = "El state de data debe pertenecer al mismo ambiente."
    }
  }
}
variable "backend_zip_path" {
  type    = string
  default = "../../.build/backend.zip"
}
variable "bedrock_model_id" {
  type    = string
  default = "us.amazon.nova-2-lite-v1:0"
}
variable "model_region" {
  type    = string
  default = "us-east-1"
}
variable "bedrock_model_arns" {
  type    = list(string)
  default = []
  validation {
    condition     = alltrue([for arn in var.bedrock_model_arns : startswith(arn, "arn:") && !strcontains(arn, "*")])
    error_message = "Lista únicamente ARN explícitos de modelos/perfiles, sin comodines."
  }
}
variable "audit_ttl_days" {
  type    = number
  default = 30
}
locals {
  foundation = data.terraform_remote_state.foundation.outputs
  tables     = data.terraform_remote_state.data.outputs
  # El perfil geográfico US desde Virginia solo usa estos tres destinos documentados.
  default_model_arns = concat(
    ["arn:${data.aws_partition.current.partition}:bedrock:us-east-1:${var.expected_account_id}:inference-profile/us.amazon.nova-2-lite-v1:0"],
    [for region in ["us-east-1", "us-east-2", "us-west-2"] : "arn:${data.aws_partition.current.partition}:bedrock:${region}::foundation-model/amazon.nova-2-lite-v1:0"]
  )
  model_arns = length(var.bedrock_model_arns) > 0 ? var.bedrock_model_arns : local.default_model_arns
}
