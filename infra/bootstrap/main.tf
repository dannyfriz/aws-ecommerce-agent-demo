terraform {
  backend "local" {
    path = "../../.build/state/bootstrap.tfstate"
  }
  required_version = ">= 1.17.0, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.70.0, < 7.0" }
  }

}
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = var.project, Environment = var.environment, ManagedBy = "Terraform", CostCenter = coalesce(var.cost_center, "${var.project}-${var.environment}") }
  }
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Indica el ID de 12 dígitos de la cuenta de laboratorio."
  }
}
variable "project" {
  type    = string
  default = "ecommerce-agent"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project))
    error_message = "Usa entre 3 y 25 caracteres en minúsculas, números o guiones."
  }
}
variable "environment" {
  type    = string
  default = "demo"
  validation {
    condition     = contains(["demo", "dev", "test"], var.environment)
    error_message = "Este proyecto admite demo, dev y test; no producción."
  }
}
locals { name = "${var.project}-${var.environment}" }
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "aws_kms_key" "state" {
  description             = "Cifrado del state Terraform de ${local.name}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_kms_alias" "state" {
  name          = "alias/${local.name}-state"
  target_key_id = aws_kms_key.state.key_id
}
resource "aws_s3_bucket" "state" {
  bucket = "${local.name}-state-${data.aws_caller_identity.current.account_id}"
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "ExigirTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
output "state_bucket" { value = aws_s3_bucket.state.id }
output "state_region" { value = var.region }
output "state_kms_key_arn" { value = aws_kms_key.state.arn }
