# DeployGuard — Execution Guide

How to configure, run, and demo the DeployGuard FastAPI service implemented
in [`app/`](app/) against [REQUIREMENTS.md](REQUIREMENTS.md).

---

## 1. Prerequisites

- Python 3.9+ (tested on 3.9.6; 3.10+ recommended — boto3 drops 3.9 support April 2026)
- An AWS account with:
  - A **Bedrock Agent** already created and associated with the Code and Metrics
    Knowledge Bases (system prompt, RCA output schema, retrieval `numberOfResults`,
    and chunking are all configured *in the agent*, not in this codebase — see
    NFR-2/NFR-3 in REQUIREMENTS.md).
  - An **S3 bucket** for incident reports (`deployguard-incidents` by default).
  - Credentials available locally (`aws configure` / SSO) or, in production, an
    EC2 instance role with `bedrock:InvokeAgent`, `bedrock:GetAgent`,
    `s3:GetObject`/`PutObject` on the incidents bucket, and
    `secretsmanager:GetSecretValue` (NFR-8).
- Optional: a JIRA Cloud site + API token, and a Slack bot token with
  `chat:write` — only needed if `ENABLE_JIRA` / `ENABLE_SLACK` are on.

---

## 2. Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest
```

If boto3 raises `MissingDependencyException` about a `login_session` /
`crt` credential provider (seen with some AWS SSO profiles), run:

```bash
pip install "botocore[crt]"
```

---

## 3. Configuration

All settings are environment variables (see `app/config.py`), loaded from a
local `.env` file if present. **Never put real secrets in `.env` for a
shared repo** — in AWS, set `SECRETS_MANAGER_SECRET_NAME` instead and the
service pulls JIRA/Slack credentials from Secrets Manager at startup
(NFR-8). `.env` is only for local developer convenience and is already
gitignored.

| Variable | Default | Notes |
|---|---|---|
| `AWS_REGION` | `us-east-1` | |
| `BEDROCK_AGENT_ID` | *(required)* | Your Bedrock Agent ID |
| `BEDROCK_AGENT_ALIAS_ID` | `TSTALIASID` | Use a real alias in production |
| `BEDROCK_MAX_RETRIES` | `3` | Exponential backoff on throttling |
| `S3_BUCKET` | `deployguard-incidents` | |
| `SECRETS_MANAGER_SECRET_NAME` | *(unset)* | If set, overrides JIRA/Slack env vars at startup |
| `ENABLE_JIRA` | `true` | Set `false` if Muskan's dashboard owns ticket creation (TEAM.md Option B) |
| `JIRA_BASE_URL` | *(empty)* | e.g. `https://yourteam.atlassian.net` |
| `JIRA_EMAIL` / `JIRA_API_TOKEN` | *(empty)* | JIRA Cloud basic auth |
| `JIRA_PROJECT_KEY` | `OPS` | |
| `JIRA_DEFAULT_ASSIGNEE` | *(unset)* | JIRA accountId |
| `JIRA_DEFAULT_WATCHERS` | `[]` | JSON list of accountIds |
| `ENABLE_SLACK` | `true` | |
| `SLACK_BOT_TOKEN` | *(empty)* | |
| `SLACK_CHANNEL` | `#deployguard-alerts` | |
| `SLACK_ONCALL_MENTIONS` | `[]` | JSON list of Slack user IDs |
| `ENABLE_DATABRICKS` | `true` | |
| `DATABRICKS_HOST` | *(empty)* | e.g. `https://<workspace>.cloud.databricks.com` |
| `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` | *(empty)* | OAuth M2M (preferred in AWS) |
| `DATABRICKS_TOKEN` | *(empty)* | PAT fallback for local dev |
| `DAILY_INVESTIGATION_CAP` | *(unset)* | Optional cost guardrail (NFR-10) |

For a first local run with no JIRA/Slack setup yet, set:

```bash
export ENABLE_JIRA=false
export ENABLE_SLACK=false
export BEDROCK_AGENT_ID=<your-agent-id>
```

---

## 4. Run it

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On EC2 (production), drop `--reload` and put it behind systemd/an ALB:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 5. Try it

```bash
HOST=http://localhost:8000

# Health check (FR-7) — also verifies Bedrock connectivity
curl $HOST/health

# Trigger an investigation (FR-1) — minimal, token-efficient payload (NFR-1)
curl -X POST "$HOST/api/v1/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "error_message": "NullPointerException: PAYMENT_URL is null",
    "service": "payment-api",
    "environment": "production",
    "context": {
      "deploy_sha": "abc123",
      "log_snippet": "PaymentHandler.java:42 PAYMENT_URL null"
    },
    "triggered_by": "manual"
  }'

# List past incidents (dashboard API)
curl "$HOST/api/v1/incidents?service=payment-api&limit=10"

# Fetch one incident's full detail
curl "$HOST/api/v1/incidents/<investigation_id>"
```

Expected `/investigate` response shape matches the contract in `TEAM.md`:

```json
{
  "investigation_id": "...",
  "status": "completed",
  "root_cause": "...",
  "confidence": 0.9,
  "rca_summary": "...",
  "evidence": ["..."],
  "suggested_fix": "...",
  "s3_report_url": "s3://deployguard-incidents/2026/08/.../",
  "actions": { "jira_ticket": "OPS-123", "jira_url": "...", "jira_created": true, "slack_sent": true },
  "cached": false
}
```

If Bedrock fails after retries, you still get a `200` with
`"status": "failed"` and `error_detail` set — never a silent failure
(NFR-7).

---

## 6. Run the tests

```bash
source .venv/bin/activate
pytest -v
```

Tests use fakes for Bedrock/JIRA/Slack/S3 (see `tests/conftest.py`) — no
AWS credentials or live services required.

---

## 7. Known limitations (hackathon scope)

- The dedup cache (NFR-5) and daily investigation cap (NFR-10) are
  in-process and per-instance — fine for a single EC2 instance, not safe
  behind a multi-instance ALB without a shared store (DynamoDB/Redis).
- The S3 incidents index (`index/incidents.jsonl`) is read-modify-written
  on every save; concurrent investigations can race and drop an index
  entry (the per-incident `incident.json`/`by_id/*.json` objects are
  unaffected). Acceptable for demo traffic; swap for DynamoDB before
  scaling up.
- JIRA/Slack are called directly from this service (TEAM.md Option A). To
  use Option B instead (Muskan's dashboard owns ticket/alert creation),
  set `ENABLE_JIRA=false` and `ENABLE_SLACK=false` and read RCA data via
  `GET /api/v1/incidents`.

---

*Created using Anthropic Claude — review before relying on this as final
documentation.*
