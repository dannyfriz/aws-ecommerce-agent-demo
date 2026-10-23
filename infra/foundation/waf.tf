# CloudFront requiere administrar su Web ACL desde us-east-1.
provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = var.project, Environment = var.environment, ManagedBy = "Terraform", CostCenter = coalesce(var.cost_center, "${var.project}-${var.environment}") }
  }
}

resource "aws_wafv2_web_acl" "web" {
  provider    = aws.us_east_1
  name        = "${local.name}-web"
  description = "Proteccion del frontend CloudFront con reglas administradas y limite por IP"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSCommonRules"
    priority = 10
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "LimitePorIP"
    priority = 20
    action {
      block {}
    }
    statement {
      rate_based_statement {
        # El umbral contempla varias personas detras del mismo NAT del evento.
        limit                 = 2000
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-web"
    sampled_requests_enabled   = false
  }
}

output "frontend_web_acl_arn" { value = aws_wafv2_web_acl.web.arn }
