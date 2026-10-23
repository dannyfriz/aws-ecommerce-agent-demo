variable "api_domain_name" {
  type        = string
  default     = ""
  description = "Hostname opcional de la API, autorizado explícitamente en la política CSP."
  validation {
    condition     = var.api_domain_name == "" || can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.api_domain_name))
    error_message = "Indica un hostname sin protocolo ni rutas."
  }
}

variable "frontend_domain_name" {
  type        = string
  default     = ""
  description = "Dominio opcional ya validado por ACM; su DNS debe apuntar a CloudFront."
}
variable "acm_certificate_arn" {
  type        = string
  default     = ""
  description = "Certificado ACM de us-east-1, obligatorio con dominio propio para exigir TLS 1.3."
}
locals {
  frontend_url = "https://${var.frontend_domain_name != "" ? var.frontend_domain_name : aws_cloudfront_distribution.web.domain_name}"
}
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = local.name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
resource "aws_cloudfront_response_headers_policy" "web" {
  name = "${local.name}-security"
  security_headers_config {
    content_type_options { override = true }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' https://*.execute-api.${var.region}.amazonaws.com https://*.auth.${var.region}.amazoncognito.com${var.auth_domain_name != "" ? " https://${var.auth_domain_name}" : ""}${var.api_domain_name != "" ? " https://${var.api_domain_name}" : ""}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
      override                = true
    }
  }
}
resource "aws_cloudfront_distribution" "web" {
  web_acl_id          = aws_wafv2_web_acl.web.arn
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  aliases             = var.frontend_domain_name != "" ? [var.frontend_domain_name] : []
  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }
  default_cache_behavior {
    target_origin_id           = "web"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    min_ttl                    = 0
    default_ttl                = 0
    max_ttl                    = 0
    response_headers_policy_id = aws_cloudfront_response_headers_policy.web.id
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    cloudfront_default_certificate = var.frontend_domain_name == ""
    acm_certificate_arn            = var.frontend_domain_name != "" ? var.acm_certificate_arn : null
    ssl_support_method             = var.frontend_domain_name != "" ? "sni-only" : null
    # AWS impone TLSv1 al certificado predeterminado; TLS 1.3 requiere certificado propio.
    minimum_protocol_version = var.frontend_domain_name != "" ? "TLSv1.3_2025" : "TLSv1"
  }
  lifecycle {
    precondition {
      condition     = (var.frontend_domain_name == "" && var.acm_certificate_arn == "") || (var.frontend_domain_name != "" && can(regex("^arn:${data.aws_partition.current.partition}:acm:us-east-1:${var.expected_account_id}:certificate/[a-f0-9-]+$", var.acm_certificate_arn)))
      error_message = "Dominio y certificado deben configurarse juntos; CloudFront requiere ACM en us-east-1 y en la cuenta esperada."
    }
  }
}
