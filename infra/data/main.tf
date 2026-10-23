variable "deletion_protection" {
  type    = bool
  default = true
}
resource "aws_dynamodb_table" "orders" {
  name                        = "${local.name}-orders"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "order_id"
  deletion_protection_enabled = var.deletion_protection
  attribute {
    name = "order_id"
    type = "S"
  }
  attribute {
    name = "return_status"
    type = "S"
  }
  global_secondary_index {
    name            = "return_status-order_id"
    projection_type = "KEYS_ONLY"
    key_schema {
      attribute_name = "return_status"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "order_id"
      key_type       = "RANGE"
    }
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = data.terraform_remote_state.foundation.outputs.kms_key_arn
  }
}
resource "aws_dynamodb_table" "audit" {
  name                        = "${local.name}-audit"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "stream"
  range_key                   = "event_id"
  deletion_protection_enabled = var.deletion_protection
  attribute {
    name = "event_id"
    type = "S"
  }
  attribute {
    name = "stream"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = data.terraform_remote_state.foundation.outputs.kms_key_arn
  }
}
output "orders_table_name" { value = aws_dynamodb_table.orders.name }
output "orders_table_arn" { value = aws_dynamodb_table.orders.arn }
output "audit_table_name" { value = aws_dynamodb_table.audit.name }
output "audit_table_arn" { value = aws_dynamodb_table.audit.arn }
