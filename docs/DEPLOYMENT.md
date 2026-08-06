# DeployGuard — AWS Deployment Guide

How to provision infrastructure with Terraform and deploy application code to EC2.

---

## Architecture (what Terraform creates)

```
Internet
   │
   ▼
Application Load Balancer (:80)
   │  health check → GET /health
   ▼
EC2 (Amazon Linux 2023)
   ├── DeployGuard FastAPI (:8000, systemd)
   ├── IAM role → Bedrock, S3, Secrets Manager, CloudWatch Logs
   └── CloudWatch Agent → /var/log/deployguard/app.log

S3 bucket          → incident reports (incident.json, rca.md, index)
Secrets Manager    → JIRA + Slack tokens
CloudWatch Logs    → /ec2/deployguard-dev
```

**Not created by this Terraform** (set up manually before apply):

- Amazon Bedrock Agent + Knowledge Bases (code + metrics)
- JIRA Cloud site / Slack app tokens (stored in Secrets Manager)

---

## Prerequisites

1. **AWS CLI** configured (`aws sts get-caller-identity`)
2. **Terraform** >= 1.5
3. **Bedrock Agent** already created with agent ID ready
4. **Default VPC** in target region (Terraform uses default VPC/subnets)

---

## Step 1 — Configure Terraform

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
bedrock_agent_id       = "ABCDEF1234"
bedrock_agent_alias_id = "YOUR_ALIAS_ID"
jira_base_url          = "https://yourteam.atlassian.net"
allowed_cidr_blocks    = ["YOUR.IP.ADDRESS/32"]   # restrict ALB access
```

---

## Step 2 — Provision infrastructure

```bash
cd infra
terraform init
terraform plan
terraform apply
```

Note the outputs:

```bash
terraform output alb_dns_name
terraform output ec2_instance_id
terraform output secrets_manager_secret_name
```

---

## Step 3 — Set secrets

Update JIRA/Slack credentials in Secrets Manager (replace placeholders):

```bash
SECRET=$(terraform output -raw secrets_manager_secret_name)

aws secretsmanager put-secret-value \
  --region us-east-1 \
  --secret-id "$SECRET" \
  --secret-string '{
    "jira_email": "you@company.com",
    "jira_api_token": "your-jira-token",
    "slack_bot_token": "xoxb-your-slack-token",
    "databricks_client_id": "your-service-principal-client-id",
    "databricks_client_secret": "your-service-principal-oauth-secret"
  }'
```

Restart the app to reload secrets:

```bash
aws ssm send-command \
  --instance-ids "$(terraform output -raw ec2_instance_id)" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl restart deployguard"]'
```

---

## Step 4 — Verify deployment

Wait 3–5 minutes after `terraform apply` for EC2 user_data bootstrap (git clone, pip install, systemd start).

```bash
HOST=$(terraform output -raw alb_dns_name)

curl "$HOST/health"
curl -X POST "$HOST/api/v1/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "error_message": "NullPointerException: PAYMENT_URL is null",
    "service": "payment-api",
    "environment": "production",
    "triggered_by": "manual"
  }'
```

---

## How code is deployed

### Initial deploy (automatic)

On first `terraform apply`, EC2 **user_data** script:

1. Installs Python 3, Node.js, git, CloudWatch Agent
2. Clones `git_repo_url` @ `git_branch` → `/opt/deployguard`
3. Creates venv, `pip install -r requirements.txt`
4. Builds the dashboard SPA (`frontend/` → `frontend/dist/`)
5. Writes `/etc/deployguard.env` (Bedrock ID, S3 bucket, secret name)
6. Starts `deployguard` systemd service (`uvicorn app.main:app :8000`)

The ALB serves the dashboard at `/` and the API at `/api/v1/*`.

### Subsequent deploys (after code changes)

**Option A — SSM deploy script (recommended)**

```bash
chmod +x scripts/deploy.sh

./scripts/deploy.sh $(cd infra && terraform output -raw ec2_instance_id) us-east-1
```

This runs on the instance via SSM:

- `git pull origin main`
- `pip install -r requirements.txt`
- `npm install && npm run build` in `frontend/`
- `systemctl restart deployguard`
- local `curl /health`

**Option B — Manual SSH** (if `key_name` set in tfvars)

```bash
ssh ec2-user@<instance-public-ip>
sudo -u deployguard bash -c 'cd /opt/deployguard && git pull && .venv/bin/pip install -r requirements.txt'
sudo systemctl restart deployguard
```

**Option C — GitHub Actions (optional future)**

On push to `main`:

1. Run tests
2. Call `./scripts/deploy.sh` with `AWS_ACCESS_KEY_ID` / OIDC role

---

## Deployment flow diagram

```
Developer                    AWS
─────────                    ───
git push main
     │
     ▼
./scripts/deploy.sh ──────► SSM Run Command
                                  │
                                  ▼
                             git pull + pip install
                                  │
                                  ▼
                             systemctl restart deployguard
                                  │
                                  ▼
                             ALB health check /health
                                  │
                                  ▼
                             Traffic routed to new code
```

---

## Environment variables (set by Terraform on EC2)

| Variable | Source |
|---|---|
| `AWS_REGION` | terraform var |
| `S3_BUCKET` | created bucket name |
| `BEDROCK_AGENT_ID` | terraform var |
| `BEDROCK_AGENT_ALIAS_ID` | terraform var |
| `SECRETS_MANAGER_SECRET_NAME` | created secret |
| `JIRA_BASE_URL`, `JIRA_PROJECT_KEY` | terraform vars |
| `SLACK_CHANNEL` | terraform var |
| `JIRA_EMAIL`, `JIRA_API_TOKEN`, `SLACK_BOT_TOKEN`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | Secrets Manager at startup |

See `/etc/deployguard.env` on the instance.

---

## Tear down

```bash
cd infra
terraform destroy
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `/health` returns degraded | Check Bedrock agent ID/alias; verify IAM `bedrock:InvokeAgent` |
| 502 from ALB | Bootstrap still running — wait 5 min; check `systemctl status deployguard` via SSM |
| JIRA/Slack not working | Update Secrets Manager; restart service |
| SSM deploy fails | Instance needs `AmazonSSMManagedInstanceCore` (included in Terraform) |

**View logs via SSM:**

```bash
aws ssm start-session --target $(terraform output -raw ec2_instance_id)
sudo tail -f /var/log/deployguard/app.log
```

---

## Files

| Path | Purpose |
|---|---|
| `infra/` | Terraform modules (EC2, ALB, S3, IAM, Secrets) |
| `infra/templates/user_data.sh.tpl` | EC2 bootstrap script |
| `infra/templates/deployguard.env.tpl` | App env file template |
| `scripts/deploy.sh` | SSM-based code redeploy |
