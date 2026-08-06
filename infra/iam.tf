data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

data "aws_iam_policy_document" "ec2_permissions" {
  statement {
    sid    = "BedrockInvokeAgent"
    effect = "Allow"
    actions = [
      "bedrock:InvokeAgent",
      "bedrock:GetAgent",
      "bedrock:GetAgentAlias",
    ]
    resources = [
      local.bedrock_agent_arn,
      "${local.bedrock_agent_arn}/alias/*",
    ]
  }

  statement {
    sid    = "S3IncidentsBucket"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.incidents.arn,
      "${aws_s3_bucket.incidents.arn}/*",
    ]
  }

  statement {
    sid    = "SecretsManagerRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.app.arn,
    ]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "${aws_cloudwatch_log_group.app.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "ec2" {
  name   = "${local.name_prefix}-ec2-policy"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_permissions.json
}

# SSM Session Manager — deploy script uses send-command without SSH keys
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}
