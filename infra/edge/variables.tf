variable "aws_region" {
  description = "AWS region for Route 53 (global service, but provider region)"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment label"
  type        = string
  default     = "dev"
}

variable "domain_name" {
  description = "HTTPS hostname (must match the ACM certificate)"
  type        = string
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for the domain"
  type        = string
}

variable "origin_dns_name" {
  description = "Public DNS name of the DeployGuard ALB (HTTP origin)"
  type        = string
}

variable "acm_certificate_arn" {
  description = "Validated ACM certificate ARN in us-east-1 (required for CloudFront custom domain)"
  type        = string
}
