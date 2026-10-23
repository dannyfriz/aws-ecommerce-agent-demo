terraform {
  required_version = ">= 1.17.0, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.70.0, < 7.0" }
  }
  backend "s3" {}
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

variable "state_bucket" { type = string }
variable "state_region" {
  type    = string
  default = "us-east-1"
}
variable "foundation_state_key" {
  type    = string
  default = null
}
data "terraform_remote_state" "foundation" {
  backend = "s3"
  config  = { bucket = var.state_bucket, key = coalesce(var.foundation_state_key, "${var.environment}/foundation/terraform.tfstate"), region = var.state_region, encrypt = true }
  lifecycle {
    precondition {
      condition     = startswith(coalesce(var.foundation_state_key, "${var.environment}/foundation/terraform.tfstate"), "${var.environment}/")
      error_message = "El state de foundation debe pertenecer al mismo ambiente."
    }
  }
}
