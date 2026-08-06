# deployGuard

Automated production incident investigation agent — Python REST service + Bedrock + JIRA + Slack.

See [REQUIREMENTS.md](REQUIREMENTS.md) and [TEAM.md](TEAM.md) for the spec and team split, and
[RUNBOOK.md](RUNBOOK.md) for setup, configuration, and demo instructions.

## Layout

- `app/` — the FastAPI service (Bedrock invocation, JIRA/Slack, S3 persistence, incidents API)
- `tests/` — unit/integration tests (fakes for Bedrock/JIRA/Slack/S3, no AWS required)
- `infra/` — Terraform (EC2, ALB, S3, IAM, Secrets Manager)
- `scripts/deploy.sh` — redeploy app code via SSM after `git push`
- `team/` — other tracks' design docs (e.g. the EC2 demo app), kept out of the service's way

## AWS deployment

```bash
cd infra && cp terraform.tfvars.example terraform.tfvars
# edit bedrock_agent_id, jira_base_url, allowed_cidr_blocks
terraform init && terraform apply
```

Full guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
