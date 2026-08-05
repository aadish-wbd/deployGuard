# DeployGuard — Team Work Division

## Overview

| Person | Focus Area | Primary Deliverable |
|---|---|---|
| **Kiran** | DeployGuard Python service + incident persistence | REST API, Bedrock integration, S3 incident reports |
| **Aadish** | EC2 sample REST service | Demo/trigger app that calls DeployGuard on failure |
| **Saurabh / Vinay** | Databricks integration | Webhook/trigger from Databricks job failures |
| **Muskan** | Dashboard + JIRA + RCA + tagging | UI for past incidents, JIRA ticket flow, people tagging |

---

## Kiran — DeployGuard Python Service & Persistence

### Owns
- `POST /api/v1/investigate` — main investigation endpoint
- `GET /health`
- Amazon Bedrock Agent invocation
- Incident metadata model and persistence
- S3 report storage

### Deliverables
1. FastAPI Python service deployed on EC2
2. Bedrock Agent integration (code + metrics Knowledge Bases)
3. Incident record schema, e.g.:
   - `investigation_id`, `timestamp`, `service`, `environment`
   - Input payload (error message, stack trace, context)
   - Bedrock output (root cause, confidence, evidence, suggested fix)
   - Actions taken (JIRA ticket ID, Slack sent, status)
   - Metadata (latency, token estimate, triggered_by: databricks | ec2 | manual)
4. S3 storage layout, e.g.:
   ```
   s3://deployguard-incidents/
     {year}/{month}/{investigation_id}/
       incident.json          # full metadata
       rca.md                 # human-readable RCA report
       input.json             # original request payload
   ```
5. API for dashboard to list incidents (coordinate with Muskan):
   - `GET /api/v1/incidents` — list with pagination/filters
   - `GET /api/v1/incidents/{id}` — single incident + S3 report link

### Interfaces
| With | Contract |
|---|---|
| Aadish | Receives POST from EC2 app on exception |
| Saurabh / Vinay | Receives POST from Databricks webhook/bridge |
| Muskan | Exposes list/detail APIs; may share JIRA module or Muskan calls JIRA separately |

---

## Aadish — EC2 REST Service (Trigger Client)

### Owns
- Sample production-style REST app on EC2
- Intentional or realistic failure scenarios for demo
- Async call to DeployGuard on error

### Deliverables
1. Simple REST API (e.g. FastAPI/Flask) with 1–2 endpoints that can fail
2. Exception handler / middleware that POSTs to DeployGuard:
   - Structured, token-minimal payload (see REQUIREMENTS.md)
   - Fire-and-forget (don't block response on investigation)
3. CloudWatch Logs for the sample app (optional but good for demo)
4. README with how to trigger a demo failure

### Payload sent to Kiran's service
```json
{
  "error_message": "...",
  "stack_trace": "...",
  "service": "sample-ec2-api",
  "environment": "production",
  "timestamp": "...",
  "context": {
    "deploy_sha": "...",
    "log_snippet": "..."
  },
  "triggered_by": "ec2"
}
```

### Depends on
- Kiran: DeployGuard `/investigate` URL and expected payload schema

---

## Saurabh / Vinay — Databricks Job Webhook

### Owns
- Trigger path from Databricks job failure → DeployGuard
- Webhook or lightweight bridge (Lambda / small Python service)

### Deliverables
1. Databricks job notebook or pipeline with failure handling
2. On failure: capture exception, job ID, run ID, task name
3. POST structured payload to DeployGuard `/investigate`
4. Optional: Databricks webhook → API Gateway → Lambda → DeployGuard

### Payload sent to Kiran's service
```json
{
  "error_message": "...",
  "stack_trace": "...",
  "service": "databricks-etl-job",
  "environment": "production",
  "timestamp": "...",
  "context": {
    "job_id": "...",
    "run_id": "...",
    "task_name": "..."
  },
  "triggered_by": "databricks"
}
```

### Depends on
- Kiran: DeployGuard endpoint URL, auth (if any), payload schema

---

## Muskan — Dashboard, JIRA, RCA & Tagging

### Owns
- DeployGuard dashboard (previous incidents)
- JIRA ticket creation with full RCA
- Tagging relevant people (assignee, watchers, Slack @mentions)

### Deliverables
1. **Dashboard UI** showing:
   - List of all past incidents (from Kiran's `GET /api/v1/incidents` or S3)
   - Status, service, root cause summary, confidence, JIRA link, timestamp
   - Detail view: full RCA, evidence, actions taken
2. **JIRA integration**:
   - Create ticket with RCA in description
   - Set priority, labels (`deployguard`, service name)
   - Assignee + watchers (tag relevant people)
3. **RCA presentation**:
   - Format Bedrock output into readable RCA for JIRA and dashboard
   - Slack alert with summary + JIRA link + @mentions

### Coordination with Kiran
| Option | Who owns JIRA/Slack |
|---|---|
| A — Kiran's service calls JIRA/Slack after Bedrock | Kiran implements; Muskan builds dashboard only |
| B — Muskan's layer calls JIRA/Slack after investigation | Kiran returns RCA JSON; Muskan's dashboard/backend handles JIRA + Slack |

**Recommended for hackathon:** Kiran persists incident + RCA to S3/API; Muskan's dashboard reads incidents and owns JIRA create + tagging UI/flow (can be a button "Create JIRA" or auto on new incident).

### Depends on
- Kiran: Incidents list/detail API or S3 read access
- JIRA API token, Slack webhook (Secrets Manager)

---

## Integration Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Aadish (EC2)   │────▶│                  │     │                 │
└─────────────────┘     │  Kiran           │────▶│  S3 Reports     │
                        │  DeployGuard API │     │  + incident DB  │
┌─────────────────┐     │  + Bedrock       │     └────────┬────────┘
│ Saurabh/Vinay   │────▶│  + Persistence   │              │
│ (Databricks)    │     └────────┬─────────┘              │
└─────────────────┘              │                        │
                                 │ RCA + metadata          │
                                 ▼                        ▼
                        ┌────────────────────────────────────┐
                        │  Muskan — Dashboard + JIRA + Slack │
                        └────────────────────────────────────┘
```

---

## Shared Contracts (Agree Day 1 Morning)

### 1. Investigation request schema
See `REQUIREMENTS.md` — all clients use the same POST body shape.

### 2. Investigation response schema
```json
{
  "investigation_id": "uuid",
  "status": "completed | failed",
  "root_cause": "...",
  "confidence": 0.85,
  "rca_summary": "...",
  "evidence": ["..."],
  "suggested_fix": "...",
  "s3_report_url": "s3://...",
  "actions": {
    "jira_ticket": "OPS-123",
    "jira_url": "https://...",
    "slack_sent": true
  }
}
```

### 3. DeployGuard base URL
Agree one EC2 host:port or ALB URL for all clients.

### 4. Secrets
GitHub, JIRA, Slack, Bedrock — stored in AWS Secrets Manager; document key names in README.

---

## Suggested Timeline (2 Days)

| When | Milestone |
|---|---|
| **Day 1 AM** | Kiran: skeleton API + health; Aadish: EC2 app stub; Saurabh/Vinay: Databricks job stub; Muskan: dashboard wireframe |
| **Day 1 PM** | Kiran: Bedrock invoke + S3 write; clients POST to `/investigate` |
| **Day 2 AM** | Muskan: dashboard reads incidents + JIRA create; end-to-end demo path |
| **Day 2 PM** | Polish, demo script, Slack/JIRA live test |

---

## Out of Scope (All)

- Auto PR / code changes
- CloudWatch auto-trigger (manual/client trigger only for hackathon)
- Feedback learning loop
