# DeployGuard Terraform

Creates AWS infrastructure for the DeployGuard API:

| Resource | Purpose |
|---|---|
| EC2 | Runs FastAPI via systemd |
| ALB | Public HTTP entry, `/health` checks |
| S3 | Incident reports |
| Secrets Manager | JIRA + Slack credentials |
| IAM | Bedrock, S3, Secrets, CloudWatch, SSM |
| CloudWatch Logs | Application logs |

## Quick start

```bash
cp terraform.tfvars.example terraform.tfvars
# Set bedrock_agent_id (required)

terraform init
terraform plan
terraform apply
```

See [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) for secrets, verify, and redeploy steps.
