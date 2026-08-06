resource "aws_instance" "app" {
  ami                    = local.amazon_linux_ami
  instance_type          = var.instance_type
  subnet_id              = local.ec2_subnet_id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.key_name

  user_data = base64encode(templatefile("${path.module}/templates/user_data.sh.tpl", {
    git_repo_url   = var.git_repo_url
    git_branch     = var.git_branch
    log_group_name = aws_cloudwatch_log_group.app.name
    env_file_content = templatefile("${path.module}/templates/deployguard.env.tpl", {
      aws_region                  = var.aws_region
      s3_bucket                   = aws_s3_bucket.incidents.bucket
      bedrock_agent_id            = var.bedrock_agent_id
      bedrock_agent_alias_id      = var.bedrock_agent_alias_id
      secrets_manager_secret_name = aws_secretsmanager_secret.app.name
      enable_jira                 = var.enable_jira
      enable_slack                = var.enable_slack
      jira_base_url               = var.jira_base_url
      jira_project_key            = var.jira_project_key
      slack_channel               = var.slack_channel
      daily_investigation_cap     = var.daily_investigation_cap
      database_secret_name        = aws_secretsmanager_secret.database.name
      db_host                     = aws_rds_cluster.incidents.endpoint
      db_port                     = tostring(aws_rds_cluster.incidents.port)
      db_name                     = var.db_name
      db_user                     = var.db_master_username
    })
    systemd_unit_content = file("${path.module}/templates/deployguard.service.tpl")
  }))

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = "${local.name_prefix}-api"
  }

  depends_on = [
    aws_secretsmanager_secret_version.app,
    aws_secretsmanager_secret_version.database,
    aws_rds_cluster_instance.incidents,
    aws_iam_role_policy.ec2,
  ]
}
