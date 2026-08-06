resource "aws_cloudwatch_log_group" "app" {
  name              = "/ec2/${local.name_prefix}"
  retention_in_days = 14
}
