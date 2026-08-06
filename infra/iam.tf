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

  # Converse API fallback (used when AGENTCORE_HARNESS_ARN is unset)
  statement {
    sid    = "BedrockInvokeModel"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*",
    ]
  }

  # AgentCore Harness (optional — when AGENTCORE_HARNESS_ARN is configured)
  statement {
    sid    = "BedrockAgentCoreHarness"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeHarness",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "BedrockInvokeModel"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:Converse",
    ]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*",
      "arn:aws:bedrock:*::foundation-model/*",
    ]
  }

  dynamic "statement" {
    for_each = var.agentcore_harness_arn != "" ? [1] : []
    content {
      sid    = "BedrockAgentCoreHarness"
      effect = "Allow"
      actions = [
        "bedrock-agentcore:InvokeHarness",
        "bedrock-agentcore:InvokeAgentRuntime",
      ]
      resources = [
        var.agentcore_harness_arn,
        "${var.agentcore_harness_arn}/*",
      ]
    }
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
      aws_secretsmanager_secret.database.arn,
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
