variable "enable_policy_knowledge" {
  type        = bool
  default     = false
  description = "Habilita la consulta de políticas ficticias con Knowledge Bases y S3 Vectors."
}

locals {
  policy_document_path = "${path.module}/../../docs/politicas-posventa-demo.md"
  policy_document_key  = "policies/politicas-posventa-demo.txt"
  policy_embedding_arn = "arn:${data.aws_partition.current.partition}:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
}

resource "aws_s3_bucket" "policies" {
  count  = var.enable_policy_knowledge ? 1 : 0
  bucket = "${local.name}-policies-${var.expected_account_id}"
}

resource "aws_s3_bucket_public_access_block" "policies" {
  count                   = var.enable_policy_knowledge ? 1 : 0
  bucket                  = aws_s3_bucket.policies[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "policies" {
  count  = var.enable_policy_knowledge ? 1 : 0
  bucket = aws_s3_bucket.policies[0].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "policies" {
  count  = var.enable_policy_knowledge ? 1 : 0
  bucket = aws_s3_bucket.policies[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = local.foundation.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "policies" {
  count  = var.enable_policy_knowledge ? 1 : 0
  bucket = aws_s3_bucket.policies[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "ExigirTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.policies[0].arn, "${aws_s3_bucket.policies[0].arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}

resource "aws_s3_object" "policy_document" {
  count                  = var.enable_policy_knowledge ? 1 : 0
  bucket                 = aws_s3_bucket.policies[0].id
  key                    = local.policy_document_key
  source                 = local.policy_document_path
  source_hash            = filesha256(local.policy_document_path)
  content_type           = "text/plain; charset=utf-8"
  server_side_encryption = "aws:kms"
  kms_key_id             = local.foundation.kms_key_arn
  depends_on             = [aws_s3_bucket_public_access_block.policies, aws_s3_bucket_server_side_encryption_configuration.policies]
}

resource "aws_s3vectors_vector_bucket" "policies" {
  count              = var.enable_policy_knowledge ? 1 : 0
  vector_bucket_name = "${local.name}-policy-vectors-${var.expected_account_id}"
  encryption_configuration {
    sse_type    = "aws:kms"
    kms_key_arn = local.foundation.kms_key_arn
  }
}

resource "aws_s3vectors_index" "policies" {
  count              = var.enable_policy_knowledge ? 1 : 0
  index_name         = "policies"
  vector_bucket_name = aws_s3vectors_vector_bucket.policies[0].vector_bucket_name
  data_type          = "float32"
  dimension          = 1024
  distance_metric    = "cosine"
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
  encryption_configuration {
    sse_type    = "aws:kms"
    kms_key_arn = local.foundation.kms_key_arn
  }
}

resource "aws_iam_role" "policy_knowledge" {
  count = var.enable_policy_knowledge ? 1 : 0
  name  = "${local.name}-policy-knowledge"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "bedrock.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = var.expected_account_id },
    ArnLike = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:bedrock:${var.region}:${var.expected_account_id}:knowledge-base/*" } }
  }] })
}

resource "aws_iam_role_policy" "policy_knowledge" {
  count = var.enable_policy_knowledge ? 1 : 0
  name  = "SoloPoliticasDemo"
  role  = aws_iam_role.policy_knowledge[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "EmbeddingExplicito", Effect = "Allow", Action = "bedrock:InvokeModel", Resource = local.policy_embedding_arn },
    { Sid = "ListarFuentePropia", Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.policies[0].arn,
    Condition = { StringEquals = { "aws:ResourceAccount" = var.expected_account_id }, StringLike = { "s3:prefix" = ["policies/", local.policy_document_key] } } },
    { Sid = "LeerDocumentoExplicito", Effect = "Allow", Action = "s3:GetObject", Resource = "${aws_s3_bucket.policies[0].arn}/${local.policy_document_key}",
    Condition = { StringEquals = { "aws:ResourceAccount" = var.expected_account_id } } },
    { Sid = "IndiceExplicito", Effect = "Allow", Action = ["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors", "s3vectors:QueryVectors", "s3vectors:GetIndex"], Resource = aws_s3vectors_index.policies[0].index_arn },
    { Sid = "CifrarFuenteIndiceEIngesta", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = local.foundation.kms_key_arn }
  ] })
}

resource "aws_bedrockagent_knowledge_base" "policies" {
  count       = var.enable_policy_knowledge ? 1 : 0
  name        = "${local.name}-policies"
  description = "Politicas ficticias compartibles; no contiene pedidos ni datos privados."
  role_arn    = aws_iam_role.policy_knowledge[0].arn
  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.policy_embedding_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = 1024
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }
  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration { index_arn = aws_s3vectors_index.policies[0].index_arn }
  }
  depends_on = [aws_iam_role_policy.policy_knowledge]
}

resource "aws_bedrockagent_data_source" "policies" {
  count                = var.enable_policy_knowledge ? 1 : 0
  name                 = "${local.name}-policy-document"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.policies[0].id
  data_deletion_policy = "RETAIN"
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn              = aws_s3_bucket.policies[0].arn
      bucket_owner_account_id = var.expected_account_id
      inclusion_prefixes      = [local.policy_document_key]
    }
  }
  server_side_encryption_configuration { kms_key_arn = local.foundation.kms_key_arn }
  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = 200
        overlap_percentage = 10
      }
    }
  }
  depends_on = [aws_s3_object.policy_document]
}

resource "aws_iam_role_policy" "backend_knowledge" {
  count = var.enable_policy_knowledge ? 1 : 0
  name  = "ConsultarPoliticasDemo"
  role  = aws_iam_role.backend.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid      = "RecuperarSoloPoliticas", Effect = "Allow", Action = "bedrock:Retrieve",
    Resource = aws_bedrockagent_knowledge_base.policies[0].arn
  }] })
}

output "policy_knowledge_base_id" {
  value = var.enable_policy_knowledge ? aws_bedrockagent_knowledge_base.policies[0].id : null
}
output "policy_knowledge_data_source_id" {
  value = var.enable_policy_knowledge ? aws_bedrockagent_data_source.policies[0].data_source_id : null
}
output "policy_knowledge_source_uri" {
  value = var.enable_policy_knowledge ? "s3://${aws_s3_bucket.policies[0].bucket}/${local.policy_document_key}" : null
}
output "policy_knowledge_document_hash" {
  value = filesha256(local.policy_document_path)
}
