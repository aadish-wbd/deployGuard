# deployGuard

Automated production incident investigation agent — Python REST service + Bedrock + JIRA + Slack + dashboard UI.

See [REQUIREMENTS.md](REQUIREMENTS.md) and [TEAM.md](TEAM.md) for the spec and team split, and
[RUNBOOK.md](RUNBOOK.md) for setup, configuration, and demo instructions.

## Layout

- `app/` — the FastAPI service (Bedrock invocation, JIRA/Slack, S3 persistence, incidents API)
- `frontend/` — React dashboard (incident list, KPI stats, detail view)
- `tests/` — unit/integration tests (fakes for Bedrock/JIRA/Slack/S3, no AWS required)
- `infra/` — Terraform (EC2, ALB, S3, IAM, Secrets Manager)
- `scripts/deploy.sh` — redeploy app code via SSM after `git push`
- `scripts/build_dashboard.sh` — build the dashboard SPA locally
- `team/` — other tracks' design docs (e.g. the EC2 demo app), kept out of the service's way

## Dashboard UI

The dashboard is served from the same ALB as the API (port 80 → EC2 :8000):

```bash
# Local development — API + UI hot reload
uvicorn app.main:app --reload --port 8000          # terminal 1
cd frontend && npm install && npm run dev          # terminal 2 → http://localhost:5173

# Production build (also runs on EC2 bootstrap / deploy.sh)
./scripts/build_dashboard.sh
uvicorn app.main:app --host 0.0.0.0 --port 8000    # → http://localhost:8000/
```

Features: KPI cards, incident table with filters, detail view (RCA, evidence, JIRA/Slack status).

## AWS deployment

```bash
cd infra && cp terraform.tfvars.example terraform.tfvars
# edit bedrock_agent_id, jira_base_url, allowed_cidr_blocks
terraform init && terraform apply
```

Full guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
