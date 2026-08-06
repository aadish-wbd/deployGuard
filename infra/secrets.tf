resource "aws_secretsmanager_secret" "app" {
  name        = "${local.name_prefix}/app-credentials"
  description = "JIRA and Slack credentials for DeployGuard (update values after apply)"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode(var.secrets_placeholder)
}
