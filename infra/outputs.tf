output "alb_dns_name" {
  description = "Public ALB URL — use as HOST for curl / client integrations"
  value       = "http://${aws_lb.app.dns_name}"
}

output "health_check_url" {
  description = "Health endpoint"
  value       = "http://${aws_lb.app.dns_name}/health"
}

output "investigate_url" {
  description = "Main investigation endpoint"
  value       = "http://${aws_lb.app.dns_name}/api/v1/investigate"
}

output "ec2_instance_id" {
  description = "EC2 instance ID (for SSM deploy script)"
  value       = aws_instance.app.id
}

output "ec2_private_ip" {
  description = "EC2 private IP"
  value       = aws_instance.app.private_ip
}

output "s3_bucket_name" {
  description = "Incidents S3 bucket"
  value       = aws_s3_bucket.incidents.bucket
}

output "secrets_manager_secret_name" {
  description = "Update JIRA/Slack credentials here after apply"
  value       = aws_secretsmanager_secret.app.name
}

output "cloudwatch_log_group" {
  description = "Application log group"
  value       = aws_cloudwatch_log_group.app.name
}

output "deploy_command_hint" {
  description = "Re-deploy app code after git push"
  value       = "./scripts/deploy.sh ${aws_instance.app.id} ${var.aws_region}"
}
