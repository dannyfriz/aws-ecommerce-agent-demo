resource "aws_cognito_user_pool" "users" {
  name                = local.name
  deletion_protection = "ACTIVE"
  admin_create_user_config { allow_admin_create_user_only = true }
  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }
  # En la demo no se exige teléfono ni se administra un segundo factor por Terraform.
  mfa_configuration = "OFF"

}
resource "aws_cognito_user_group" "customers" {
  name         = "customer"
  user_pool_id = aws_cognito_user_pool.users.id
  description  = "Clientes: consultar y solicitar devoluciones propias"
}
resource "aws_cognito_user_group" "supervisors" {
  name         = "supervisor"
  user_pool_id = aws_cognito_user_pool.users.id
  description  = "Supervisión humana: aprobar devoluciones solicitadas"
}
resource "aws_cognito_resource_server" "api" {
  identifier   = var.project
  name         = "API de ${local.name}"
  user_pool_id = aws_cognito_user_pool.users.id
  scope {
    scope_name        = "access"
    scope_description = "Acceso autenticado a la API; el backend valida cada operación"
  }
}
resource "aws_cognito_user_pool_domain" "users" {
  domain       = "${local.name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.users.id
}
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${local.name}-spa"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile", "${aws_cognito_resource_server.api.identifier}/access"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.frontend_url}/"]
  logout_urls                          = ["${local.frontend_url}/"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 60
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "minutes"
  }
}
