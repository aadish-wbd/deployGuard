variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Resource name prefix"
  type        = string
  default     = "deployguard"
}

variable "environment" {
  description = "Environment label (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "instance_type" {
  description = "EC2 instance type for the DeployGuard API"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Optional EC2 key pair name for SSH access"
  type        = string
  default     = null
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to reach the ALB (use your office IP/VPN for prod)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "vpc_cidr" {
  description = "CIDR for the dedicated VPC (created because many enterprise accounts have no default VPC)"
  type        = string
  default     = "10.42.0.0/16"
}

variable "bedrock_agent_id" {
  description = "Bedrock Agent ID (create agent + KBs in console first)"
  type        = string
}

variable "bedrock_agent_alias_id" {
  description = "Bedrock Agent alias ID"
  type        = string
  default     = "TSTALIASID"
}

variable "git_repo_url" {
  description = "Git repo cloned on EC2 at bootstrap (HTTPS or SSH)"
  type        = string
  default     = "https://github.com/aadish-wbd/deployGuard.git"
}

variable "git_branch" {
  description = "Branch deployed on EC2"
  type        = string
  default     = "main"
}

variable "enable_jira" {
  description = "Enable JIRA integration in the app"
  type        = bool
  default     = true
}

variable "enable_slack" {
  description = "Enable Slack integration in the app"
  type        = bool
  default     = true
}

variable "jira_base_url" {
  description = "JIRA Cloud base URL (non-secret)"
  type        = string
  default     = ""
}

variable "jira_project_key" {
  description = "Default JIRA project key"
  type        = string
  default     = "OPS"
}

variable "slack_channel" {
  description = "Default Slack channel"
  type        = string
  default     = "#deployguard-alerts"
}

variable "daily_investigation_cap" {
  description = "Optional daily cap on investigations (null = unlimited)"
  type        = number
  default     = null
}

variable "aurora_instance_class" {
  description = "Aurora instance class — db.t4g.medium is the smallest (and cheapest) Aurora size"
  type        = string
  default     = "db.t4g.medium"
}

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "17.4"
}

variable "db_name" {
  description = "Initial database name on the Aurora cluster"
  type        = string
  default     = "deployguard"
}

variable "db_master_username" {
  description = "Aurora master username"
  type        = string
  default     = "deployguard"
}

variable "db_backup_retention_days" {
  description = "Aurora backup retention (1 day minimum — keeps dev cost down)"
  type        = number
  default     = 1
}

variable "secrets_placeholder" {
  description = "Initial Secrets Manager JSON (update real values in console after apply)"
  type        = map(string)
  default = {
    jira_email               = "replace-me@example.com"
    jira_api_token           = "replace-me"
    slack_bot_token          = "replace-me"
    databricks_client_id     = "replace-me"
    databricks_client_secret = "replace-me"
  }
  sensitive = true
}
