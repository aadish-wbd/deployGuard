# Agent Prompt — Build Plans Demo API (Incident Scenario App)

Copy everything below the line into another coding agent.

---

## PROMPT START

You are building a **dummy Plans Demo REST API** for the **DeployGuard** hackathon project. DeployGuard is an incident investigation agent that accepts structured error payloads via `POST /api/v1/investigate` and produces RCA (root cause analysis).

Your job: build a **minimal but realistic** Python FastAPI app that simulates the **UMP Plans service** (AdTech campaign planning) and can **deliberately trigger production-like incidents** for demo and RCA testing.

### Do NOT over-engineer
- No real Postgres, Cognito, or Kubernetes
- In-memory data is fine
- Focus on **8 critical endpoints** and **10 incident scenarios**
- Must integrate with DeployGuard on failure

---

## Business context

**Domain:** Warner Bros Discovery — Unified Media Planner (UMP)  
**Service name:** `plans-demo-api`  
**Real-world flow:** Media planners list deals → run linear/DDL/ADU optimizer → save draft → export CSV  

Your app mirrors this so incident demos tell a credible story to judges.

**Seed deals (in-memory):**
```
WBD-2026-Q1-001 — Linear plan, $2.5M budget, advertiser "Acme Corp"
WBD-2026-Q1-002 — DDL plan, flight Mar–Jun 2026
WBD-2026-Q1-003 — ADU make-good, 3 advertisers, impression deficit
```

---

## Tech stack

| Item | Choice |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI + Uvicorn |
| Port | **8088** (matches real Plans service locally) |
| Data | In-memory dicts/lists |
| Optional | Mock optimizer on port 3030 (simple FastAPI stub) |
| Logs | Structured JSON to stdout (CloudWatch-ready) |
| DeployGuard call | httpx async fire-and-forget on 500/503 |

**Project layout:**
```
team/plans-demo-api/
├── app/
│   ├── main.py
│   ├── routes/health.py, deals.py, optimizer.py, adu.py, save_draft.py
│   ├── middleware/logging.py, deployguard.py
│   ├── scenarios/          # scenario handlers (npe, timeout, cpu, etc.)
│   └── data/seed.py        # in-memory deals
├── demo/run_all_scenarios.sh
├── requirements.txt
└── README.md
```

---

## Critical endpoints (must implement)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns `{"status":"ok"}` |
| GET | `/deals` | List deals with plan summary (dashboard) |
| GET | `/deals/{contractId}` | Get plan for a deal |
| POST | `/run-optimizer/linear` | Call downstream optimizer (linear) |
| POST | `/run-optimizer/ddl` | Call downstream optimizer (DDL) |
| POST | `/adu/run` | ADU make-good optimizer (heaviest path) |
| POST | `/save-draft` | Save optimizer output as draft |
| GET | `/deals/{contractId}/export-csv` | Export plan allocations as CSV |

**Optional:** `GET /adu/campaigns`, `POST /submit-approval`, `GET /ddl-inventory`

---

## Incident scenarios (must implement all 10)

Each scenario is triggered via query param `?scenario=<name>` or header `X-Demo-Scenario: <name>`.

| # | scenario | Endpoint | HTTP | Business story | What agent should find in RCA |
|---|---|---|---|---|---|
| 1 | `npe` | POST `/run-optimizer/linear?scenario=npe` | 500 | Bad deploy removed `OPTIMIZER_URL` env var | Missing env var in config/deploy |
| 2 | `dependency` | POST `/run-optimizer/linear?scenario=dependency` | 503 | Python optimizer unreachable | Downstream service down / wrong URL |
| 3 | `runtime` | POST `/save-draft?scenario=runtime` | 500 | UI sent null `contractId` after schema change | Validation/payload mismatch |
| 4 | `timeout` | POST `/adu/run?scenario=timeout` | 504 | ADU optimizer hangs 45s | Long-running dependency timeout |
| 5 | `slow` | GET `/deals?scenario=slow` | 200 (3s delay) | Dashboard regression after deploy | Latency spike, p99 degradation |
| 6 | `cpu` | POST `/adu/run?scenario=cpu` | 200 | ADU inventory build pegs CPU | CPU saturation from heavy job |
| 7 | `memory` | GET `/deals/{id}/export-csv?scenario=memory` | 500 | Huge CSV export OOM risk | Memory spike from large export |
| 8 | `fail_rate` | POST `/run-optimizer/ddl?scenario=fail_rate` | 500/200 random | Flaky canary deploy 50% fail | Intermittent 5xx after deploy |
| 9 | `db_slow` | GET `/deals/{id}?scenario=db_slow` | 200 (5s delay) | Postgres enrichment slow | DB/query latency |
| 10 | `not_found` | GET `/deals/invalid-id` | 404 | Bad contract ID from UI | Client error (contrast case) |

### Scenario implementation hints

**npe:** `os.environ["OPTIMIZER_URL"]` when unset → AttributeError  
**dependency:** HTTP call to `http://localhost:9999` → connection refused  
**timeout:** `time.sleep(45)`  
**slow/db_slow:** configurable delay via query param  
**cpu:** background thread matrix multiplication for 60s  
**memory:** generate CSV with 300k–500k rows in memory  
**fail_rate:** `random.random() < 0.5` → raise exception  

---

## Structured logging (required)

Every request logs JSON to stdout:

```json
{
  "level": "ERROR",
  "service": "plans-demo-api",
  "endpoint": "/run-optimizer/linear",
  "scenario": "dependency",
  "dealId": "WBD-2026-Q1-001",
  "message": "Optimizer unreachable at http://localhost:9999",
  "duration_ms": 1204,
  "trace_id": "<uuid>"
}
```

Use **Embedded Metric Format (EMF)** for custom metrics: `OptimizerErrors`, `SaveDraftErrors`, `RequestDurationMs`.

---

## DeployGuard integration (required)

On unhandled **500/503**, fire-and-forget POST to DeployGuard (do NOT block the HTTP response).

**Env vars:**
```
DEPLOYGUARD_URL=http://<alb-dns>/api/v1/investigate
DEPLOYGUARD_ENABLED=true
```

**Payload must be token-minimal** (see schema below). Trim stack trace to top 5–10 frames.

```json
{
  "error_message": "ConnectionError: optimizer unreachable",
  "stack_trace": "...",
  "service": "plans-demo-api",
  "environment": "demo",
  "context": {
    "deploy_sha": "abc123",
    "log_snippet": "Optimizer error: connection refused",
    "metrics": {"5xx_rate": "100%", "endpoint": "/run-optimizer/linear"},
    "severity": "high"
  },
  "triggered_by": "ec2"
}
```

Implement in `middleware/deployguard.py` — catch exceptions, build payload from request context (`dealId`, `scenario`, endpoint), POST async via `asyncio.create_task` or BackgroundTasks.

---

## Request body examples (match real Plans DTOs)

**POST /run-optimizer/linear**
```json
{
  "payload": {
    "dealId": "WBD-2026-Q1-001",
    "budget": 2500000,
    "flightStartDate": "2026-03-01",
    "flightEndDate": "2026-06-30"
  },
  "networkIds": [1, 2, 3]
}
```

**POST /save-draft**
```json
{
  "contractId": "WBD-2026-Q1-001",
  "planTag": "Default",
  "allocations": [{"titleId": 101, "networkId": 1, "spots": 10, "spend": 50000}],
  "summary": {"totalSpend": 2500000, "totalImpressions": 120000000, "blendedCpm": 20.83}
}
```

**POST /adu/run**
```json
{
  "advertisers": [{"id": 1, "name": "Acme", "impressionDeficit": 500000}],
  "inventoryRules": {
    "networks": [1, 2],
    "startDate": "2026-03-01",
    "endDate": "2026-06-30",
    "availabilityPct": 0.1
  }
}
```

**503 response shape (dependency scenario)** — mirror real Plans:
```json
{
  "status": "ERROR",
  "metadata": {"status": "Optimizer unreachable", "solveTimeMs": 0}
}
```

---

## Demo script (include `demo/run_all_scenarios.sh`)

```bash
HOST=http://localhost:8088

curl $HOST/health
curl $HOST/deals
curl -X POST "$HOST/run-optimizer/linear?scenario=npe" -H "Content-Type: application/json" -d '{"payload":{"dealId":"WBD-2026-Q1-001"},"networkIds":[1]}'
curl -X POST "$HOST/run-optimizer/linear?scenario=dependency" -H "Content-Type: application/json" -d '{"payload":{"dealId":"WBD-2026-Q1-001"},"networkIds":[1]}'
for i in $(seq 1 20); do curl "$HOST/deals?scenario=slow" & done; wait
curl -X POST "$HOST/adu/run?scenario=timeout" -H "Content-Type: application/json" -d '{"advertisers":[{"id":1}],"inventoryRules":{"networks":[1],"startDate":"2026-03-01","endDate":"2026-06-30"}}'
```

---

## Acceptance criteria

- [ ] All 8 endpoints implemented with happy path
- [ ] All 10 incident scenarios trigger correctly via `?scenario=`
- [ ] Structured JSON logs with `service`, `endpoint`, `scenario`, `dealId`
- [ ] DeployGuard POST fires on 500/503 with minimal payload
- [ ] README documents each scenario + expected RCA narrative
- [ ] `demo/run_all_scenarios.sh` runs end-to-end
- [ ] No auth required (hackathon demo)
- [ ] Runs with: `uvicorn app.main:app --host 0.0.0.0 --port 8088`

---

## Best demo scenario for DeployGuard RCA

**Primary:** `POST /run-optimizer/linear?scenario=dependency`  
**Why:** Mirrors real Plans → Python optimizer failure. Agent should correlate: deploy changed URL → connection refused → 503 on linear optimizer → deal WBD-2026-Q1-001 blocked.

**Expected RCA fields:**
- root_cause: Optimizer service unreachable
- evidence: log snippet, endpoint, dealId, deploy_sha
- suggested_fix: Rollback deploy or restore OPTIMIZER_URL

---

## Reference

- Design doc: `team/EC2_DEMO_APP.md` in deployGuard repo
- DeployGuard investigate schema: `app/models/schemas.py` → `InvestigateRequest`
- Real Plans controller: `unified-media-planner-api/api/plans/src/plans/plans.controller.ts`

Build the app in `team/plans-demo-api/` inside the deployGuard repository. Keep it basic, demo-ready, and credible.

## PROMPT END
