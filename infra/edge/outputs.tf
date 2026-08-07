output "public_base_url" {
  description = "HTTPS base URL for DeployGuard"
  value       = "https://${var.domain_name}"
}

output "health_check_url" {
  value = "https://${var.domain_name}/health"
}

output "investigate_url" {
  value = "https://${var.domain_name}/api/v1/investigate"
}

output "databricks_webhook_url" {
  value = "https://${var.domain_name}/api/v1/databricks/webhook"
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.app.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.app.id
}
