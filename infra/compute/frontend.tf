locals {
  web_path   = "${path.module}/../../web"
  web_files  = setsubtract(fileset(local.web_path, "**"), toset(["config.js", "config.example.js"]))
  mime_types = { html = "text/html; charset=utf-8", css = "text/css; charset=utf-8", js = "text/javascript; charset=utf-8", json = "application/json", png = "image/png", svg = "image/svg+xml", ico = "image/x-icon" }
}
resource "aws_s3_object" "web" {
  for_each               = local.web_files
  bucket                 = local.foundation.frontend_bucket_name
  key                    = each.value
  source                 = "${local.web_path}/${each.value}"
  source_hash            = filemd5("${local.web_path}/${each.value}")
  content_type           = lookup(local.mime_types, element(reverse(split(".", each.value)), 0), "application/octet-stream")
  cache_control          = "no-store"
  server_side_encryption = "aws:kms"
  kms_key_id             = local.foundation.kms_key_arn
}
resource "aws_s3_object" "config" {
  bucket                 = local.foundation.frontend_bucket_name
  key                    = "config.js"
  content_type           = "text/javascript; charset=utf-8"
  cache_control          = "no-store"
  server_side_encryption = "aws:kms"
  kms_key_id             = local.foundation.kms_key_arn
  content                = "window.APP_CONFIG = ${jsonencode({ apiBaseUrl = local.api_url, region = var.region, userPoolId = local.foundation.user_pool_id, clientId = local.foundation.user_pool_client_id, cognitoDomain = local.foundation.cognito_domain, redirectUri = "${local.foundation.frontend_url}/", scope = "openid email profile ${local.foundation.oauth_scope}" })};"
}
