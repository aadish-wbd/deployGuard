#!/usr/bin/env bash
# Re-deploy DeployGuard application code to a running EC2 instance via SSM.
#
# Usage:
#   ./scripts/deploy.sh <instance-id> [aws-region]
#
# Prerequisites:
#   - AWS CLI configured
#   - EC2 instance has SSM agent + AmazonSSMManagedInstanceCore (created by Terraform)
#   - Instance finished initial user_data bootstrap (~3-5 min after terraform apply)
#
set -euo pipefail

INSTANCE_ID="${1:?Usage: $0 <instance-id> [aws-region]}"
AWS_REGION="${2:-us-east-1}"
APP_DIR="/opt/deployguard"
GIT_BRANCH="${GIT_BRANCH:-main}"

echo "Deploying to instance $INSTANCE_ID in $AWS_REGION (branch: $GIT_BRANCH)..."

COMMAND_ID=$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "DeployGuard code deploy" \
  --parameters commands="[
    \"set -euxo pipefail\",
    \"cd $APP_DIR\",
    \"sudo -u deployguard git fetch origin\",
    \"sudo -u deployguard git checkout $GIT_BRANCH\",
    \"sudo -u deployguard git pull origin $GIT_BRANCH\",
    \"sudo -u deployguard $APP_DIR/.venv/bin/pip install -r $APP_DIR/requirements.txt\",
    \"cd $APP_DIR/frontend\",
    \"sudo -u deployguard bash -lc 'export HOME=$APP_DIR NPM_CONFIG_CACHE=$APP_DIR/.npm-cache; rm -rf node_modules; npm install && npm run build'\",
    \"sudo systemctl restart deployguard\",
    \"sleep 3\",
    \"curl -sf http://127.0.0.1:8000/health\"
  ]" \
  --query "Command.CommandId" \
  --output text)

echo "SSM command id: $COMMAND_ID"
echo "Waiting for completion..."

for i in $(seq 1 30); do
  STATUS=$(aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query "Status" \
    --output text 2>/dev/null || echo "Pending")

  echo "  status=$STATUS"

  if [[ "$STATUS" == "Success" ]]; then
    aws ssm get-command-invocation \
      --region "$AWS_REGION" \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --query "StandardOutputContent" \
      --output text
    echo "Deploy succeeded."
    exit 0
  fi

  if [[ "$STATUS" == "Failed" || "$STATUS" == "Cancelled" || "$STATUS" == "TimedOut" ]]; then
    aws ssm get-command-invocation \
      --region "$AWS_REGION" \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --query "[StandardOutputContent, StandardErrorContent]" \
      --output text
    echo "Deploy failed."
    exit 1
  fi

  sleep 5
done

echo "Timed out waiting for SSM command."
exit 1
