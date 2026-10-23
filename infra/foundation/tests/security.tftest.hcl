# Ambos providers son simulados: CloudFront y WAF no se crean en AWS.
mock_provider "aws" {
  override_during = plan
}
mock_provider "aws" {
  alias           = "us_east_1"
  override_during = plan
}
override_resource {
  target          = aws_wafv2_web_acl.web
  override_during = plan
  values          = { arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/ecommerce-agent-demo-web/11111111-1111-1111-1111-111111111111" }
}
override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012", arn = "arn:aws:iam::123456789012:root", user_id = "test" }
}
override_data {
  target = data.aws_partition.current
  values = { partition = "aws", dns_suffix = "amazonaws.com" }
}
variables { expected_account_id = "123456789012" }

run "cloudfront_exige_waf_y_no_muestrea_solicitudes" {
  command = plan
  assert {
    condition     = aws_cloudfront_distribution.web.web_acl_id == aws_wafv2_web_acl.web.arn && aws_wafv2_web_acl.web.scope == "CLOUDFRONT"
    error_message = "La distribucion debe estar asociada al Web ACL de alcance global."
  }
  assert {
    condition     = aws_wafv2_web_acl.web.visibility_config[0].cloudwatch_metrics_enabled && !aws_wafv2_web_acl.web.visibility_config[0].sampled_requests_enabled && alltrue([for rule in aws_wafv2_web_acl.web.rule : !rule.visibility_config[0].sampled_requests_enabled])
    error_message = "WAF debe ofrecer metricas sin conservar muestras de solicitudes."
  }
  assert {
    condition     = length(aws_wafv2_web_acl.web.rule) == 2 && alltrue([for rule in aws_wafv2_web_acl.web.rule : contains(["AWSCommonRules", "LimitePorIP"], rule.name)])
    error_message = "La proteccion debe incluir reglas administradas y limite por IP."
  }
}

run "indexador_vectorial_solo_descifra_el_bucket_del_proyecto" {
  command = plan
  override_resource {
    target          = aws_cloudfront_distribution.web
    override_during = plan
    values          = { arn = "arn:aws:cloudfront::123456789012:distribution/EXAMPLE" }
  }
  assert {
    condition = length([for statement in jsondecode(aws_kms_key_policy.app.policy).Statement : statement if statement.Sid == "IndexacionVectorialDeEsteProyecto"]) == 1 && alltrue([for statement in jsondecode(aws_kms_key_policy.app.policy).Statement : (
      statement.Principal.Service == "indexing.s3vectors.amazonaws.com" && statement.Action == "kms:Decrypt" &&
      statement.Condition.StringEquals["aws:SourceAccount"] == "123456789012" &&
      statement.Condition.ArnLike["aws:SourceArn"] == ["arn:aws:s3vectors:us-east-1:123456789012:bucket/ecommerce-agent-demo-policy-vectors-123456789012", "arn:aws:s3vectors:us-east-1:123456789012:bucket/ecommerce-agent-demo-policy-vectors-123456789012/*"]
      ) if statement.Sid == "IndexacionVectorialDeEsteProyecto"
    ])
    error_message = "El indexador solo puede descifrar para este bucket, cuenta y contexto de cifrado."
  }
}
