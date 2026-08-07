data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id

  bedrock_agent_arn = "arn:aws:bedrock:${var.aws_region}:${local.account_id}:agent/${var.bedrock_agent_id}"

  # EC2 in first public subnet; ALB spans both (required for internet-facing ALB)
  public_subnet_ids = aws_subnet.public[*].id
  ec2_subnet_id     = aws_subnet.public[0].id
  vpc_id            = aws_vpc.main.id

  https_enabled = var.domain_name != ""

  certificate_arn = var.acm_certificate_arn != "" ? var.acm_certificate_arn : (
    length(aws_acm_certificate_validation.app) > 0 ? aws_acm_certificate_validation.app[0].certificate_arn : ""
  )

  tls_enabled = local.certificate_arn != ""

  public_host     = local.tls_enabled ? var.domain_name : aws_lb.app.dns_name
  public_base_url = local.tls_enabled ? "https://${var.domain_name}" : "http://${aws_lb.app.dns_name}"
}

data "aws_ssm_parameter" "amazon_linux_2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  amazon_linux_ami = data.aws_ssm_parameter.amazon_linux_2023.value
}
