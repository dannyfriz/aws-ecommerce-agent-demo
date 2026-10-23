# El proveedor simulado no llama a AWS ni crea tablas reales.
mock_provider "aws" {}
override_data {
  target = data.terraform_remote_state.foundation
  values = { outputs = { kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111" } }
}
variables {
  expected_account_id = "123456789012"
  state_bucket        = "test-state"
  environment         = "dev"
}
run "state_y_auditoria_se_aislan_por_ambiente" {
  command = plan
  assert {
    condition     = one(aws_dynamodb_table.orders.global_secondary_index).name == "return_status-order_id" && one([for key in one(aws_dynamodb_table.orders.global_secondary_index).key_schema : key.attribute_name if key.key_type == "HASH"]) == "return_status" && one(aws_dynamodb_table.orders.global_secondary_index).projection_type == "KEYS_ONLY"
    error_message = "La bandeja debe consultar un índice por estado, sin proyectar los datos privados del pedido."
  }
  assert {
    condition     = data.terraform_remote_state.foundation.config.key == "dev/foundation/terraform.tfstate"
    error_message = "La capa data debe consumir foundation del mismo ambiente."
  }
  assert {
    condition     = aws_dynamodb_table.audit.hash_key == "stream" && aws_dynamodb_table.audit.range_key == "event_id"
    error_message = "La auditoría debe permitir Query ordenada sobre el stream de decisiones."
  }
}
run "rechaza_foundation_de_otro_ambiente" {
  command = plan
  variables { foundation_state_key = "demo/foundation/terraform.tfstate" }
  expect_failures = [data.terraform_remote_state.foundation]
}
