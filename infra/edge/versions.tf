terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "deployguard"
      Environment = var.environment
      ManagedBy   = "terraform"
      Component   = "edge"
    }
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
