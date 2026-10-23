resource "aws_kms_key" "app" {
  description             = "Cifrado de datos y logs de ${local.name}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_kms_alias" "app" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.app.key_id
}
resource "aws_kms_key_policy" "app" {
  key_id = aws_kms_key.app.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Sid = "AdministracionCuenta", Effect = "Allow", Principal = { AWS = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root" }, Action = "kms:*", Resource = "*" },
      { Sid = "CloudWatchLogs", Effect = "Allow", Principal = { Service = "logs.${var.region}.amazonaws.com" }, Action = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"], Resource = "*", Condition = { ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:${data.aws_partition.current.partition}:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/${local.name}/*" } } },
      { Sid = "IndexacionVectorialDeEsteProyecto", Effect = "Allow", Principal = { Service = "indexing.s3vectors.amazonaws.com" }, Action = "kms:Decrypt", Resource = "*",
        Condition = {
          StringEquals               = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id },
          ArnLike                    = { "aws:SourceArn" = ["arn:${data.aws_partition.current.partition}:s3vectors:${var.region}:${data.aws_caller_identity.current.account_id}:bucket/${local.name}-policy-vectors-${data.aws_caller_identity.current.account_id}", "arn:${data.aws_partition.current.partition}:s3vectors:${var.region}:${data.aws_caller_identity.current.account_id}:bucket/${local.name}-policy-vectors-${data.aws_caller_identity.current.account_id}/*"] },
          "ForAnyValue:StringEquals" = { "kms:EncryptionContextKeys" = ["aws:s3vectors:arn", "aws:s3vectors:resource-id"] }
        }
      },
      { Sid = "CloudFrontSoloEstaDistribucion", Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }, Action = "kms:Decrypt", Resource = "*", Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } } }
  ] })
}
resource "aws_s3_bucket" "web" {
  bucket = "${local.name}-web-${data.aws_caller_identity.current.account_id}"
}
resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.app.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Sid = "ExigirTLS", Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } },
      { Sid = "LecturaCloudFront", Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }, Action = "s3:GetObject", Resource = "${aws_s3_bucket.web.arn}/*", Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } } }
  ] })
}
