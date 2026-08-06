# EC2 Demo REST App — Plans Service Inspired (Aadish)

A minimal **Plans-like** FastAPI app on EC2 for DeployGuard demos. Mirrors critical endpoints and business flows from `unified-media-planner-api/api/plans` — media campaign planning, optimizer runs, save-draft, approval — with **query-param failure modes** for observability scenarios.

**No code yet — design only.**

---

## Why Plans Service (Not Generic Shop API)

| Real Plans flow | Demo value |
|---|---|
| Planner runs optimizer → saves draft → submits for approval | Judges recognize the workflow |
| Plans calls downstream Python optimizer (`run-optimizer/*`, `adu/run`) | Dependency failure + timeout demos feel real |
| Postgres enrichment before optimizer call | DB slow-query / timeout scenario |
| CSV export on large plan | Memory / IO spike scenario |
| ADU make-good allocation | Long-running job + CPU scenario |

Business context: **AdTech campaign planning** — deals, plan versions, linear/DDL/digital optimizer, ADU make-goods, agency approval.

---

## Architecture (Basic)

```
Demo script / UI stub
       │
       ▼
   EC2 — Plans Demo API (FastAPI, port 8088)
       │
       ├── In-memory deals / plans (no real Postgres for hackathon)
       ├── Mock optimizer HTTP service (optional 2nd process on :3030)
       ├── CloudWatch Logs (structured JSON)
       ├── CloudWatch Agent (CPU, memory)
       └── On 5xx → async POST DeployGuard /investigate
```

**Service name:** `plans-demo-api`  
**Port:** `8088` (same as local Plans service)

---

## Critical Endpoints (Mirrored from Plans)

Pick **8 endpoints** — covers happy path + all demo scenarios.

| # | Method | Endpoint | Real Plans equivalent | Business purpose |
|---|---|---|---|---|
| 1 | `GET` | `/health` | `GET /health` | ALB health check |
| 2 | `GET` | `/deals` | `GET /deals` | Dashboard — list deals with plan summary |
| 3 | `GET` | `/deals/{contractId}` | `GET /deals/:contractId` | Load plan for a deal |
| 4 | `POST` | `/run-optimizer/linear` | `POST /run-optimizer/linear` | Run linear optimizer (downstream call) |
| 5 | `POST` | `/run-optimizer/ddl` | `POST /run-optimizer/ddl` | Run DDL optimizer |
| 6 | `POST` | `/adu/run` | `POST /adu/run` | ADU make-good optimizer (heaviest path) |
| 7 | `POST` | `/save-draft` | `POST /save-draft` | Persist optimizer output as draft |
| 8 | `GET` | `/deals/{contractId}/export-csv` | `GET /deals/:contractId/export-csv` | Export plan allocations CSV |

**Optional (if time):**
- `POST /submit-approval` — approval workflow error
- `GET /ddl-inventory` — slow inventory fetch (Postgres simulation)
- `GET /adu/campaigns` — list ADU-eligible campaigns (happy path)

---

## In-Memory Seed Data (Minimal)

```text
Deal WBD-2026-Q1-001  — Linear plan, budget $2.5M, advertiser "Acme Corp"
Deal WBD-2026-Q1-002  — DDL plan, flight Mar–Jun 2026
Deal WBD-2026-Q1-003  — ADU make-good, 3 advertisers, impression deficit
```

Enough for dashboard list + optimizer payloads without a database.

---

## Failure Scenarios → Endpoint Map

Each scenario uses `?scenario=<name>` or header `X-Demo-Scenario: <name>` on the relevant endpoint.

| Scenario | Endpoint to hit | What breaks (business story) | Observability signal |
|---|---|---|---|
| **NPE** | `POST /run-optimizer/linear?scenario=npe` | `OPTIMIZER_URL` env var null after bad deploy | 500, stack trace, `AppErrors` metric |
| **Runtime error** | `POST /save-draft?scenario=runtime` | Invalid allocation payload — missing `contractId` | 500, validation error log |
| **Dependency down** | `POST /run-optimizer/linear?scenario=dependency` | Python optimizer unreachable (connection refused) | 503, `[ADU] Optimizer error` style log |
| **Optimizer timeout** | `POST /adu/run?scenario=timeout` | Optimizer hangs > 30s (real ADU pattern) | 504, high `TargetResponseTime` |
| **P99 latency** | `GET /deals?scenario=slow` × 30 | Dashboard list slow after deploy | p99 latency spike on ALB |
| **CPU high** | `POST /adu/run?scenario=cpu` | ADU inventory build + solver simulation | EC2 CPU > 80% |
| **Memory high** | `GET /deals/{id}/export-csv?scenario=memory` | Export huge CSV (500k rows) | Memory utilization spike |
| **5xx error rate** | `POST /run-optimizer/ddl?scenario=fail_rate` | 50% optimizer failures (flaky deploy) | 5xx rate alarm |
| **4xx client error** | `GET /deals/not-a-valid-id` | Bad contract ID from UI | 404 rate up |
| **DB slow (simulated)** | `GET /deals/{id}?scenario=db_slow&delay=5` | Postgres enrichment slow before optimizer | Slow query log, latency |

---

## Scenario Details (Business Narrative)

### 1. NPE — Optimizer URL missing after deploy

**Story:** DevOps deploy removed default `OPTIMIZER_URL`. Linear optimizer call crashes.

```
POST /run-optimizer/linear?scenario=npe
Body: { "payload": { "dealId": "WBD-2026-Q1-001", "budget": 2500000 }, "networkIds": [1, 2] }
```

- Code: `os.environ["OPTIMIZER_URL"].rstrip("/")` when env unset
- **Log:** `[run-optimizer/linear] OPTIMIZER_URL is null`
- **DeployGuard context:** `deploy_sha`, `service: plans-demo-api`, endpoint, scenario

---

### 2. Dependency failure — Optimizer service down

**Story:** Same as real Plans `adu/run` — fetch to Python optimizer fails.

```
POST /run-optimizer/linear?scenario=dependency
```

- Calls `http://localhost:9999/api/v1/optimize/linear` → connection refused
- **Log:** `Optimizer error: connection refused`
- **HTTP:** 503 with `{ "status": "ERROR", "metadata": { "status": "Optimizer unreachable" } }`
- Mirrors real Plans controller response shape

---

### 3. Timeout — ADU optimizer hang

**Story:** ADU make-good run stuck; planner waiting on `/adu/run`.

```
POST /adu/run?scenario=timeout
Body: { "advertisers": [...], "inventoryRules": { "networks": [1], "startDate": "2026-03-01", "endDate": "2026-06-30" } }
```

- Mock optimizer sleeps 45s
- **Metric:** ALB target response time, client timeout
- **Business impact:** "Make-good allocation blocked for Deal WBD-2026-Q1-003"

---

### 4. P99 degrade — Dashboard slow

**Story:** Bad query/deploy slows deal list; planners see spinner on home screen.

```
GET /deals?scenario=slow   (repeat 20–30×)
GET /deals                  (baseline ~50ms)
```

- Normal `/deals` returns instantly; `?scenario=slow` adds 3s delay
- **Metric:** `TargetResponseTime` p99 on ALB

---

### 5. CPU high — ADU inventory build

**Story:** Heavy ADU run builds inventory from Postgres + runs solver.

```
POST /adu/run?scenario=cpu&duration=60
```

- Background CPU burn simulating inventory matrix build
- **Log:** `[ADU] Building inventory from Postgres: networks=...`
- **Metric:** EC2 `CPUUtilization`

---

### 6. Memory high — CSV export

**Story:** Export plan allocations for large deal blows heap.

```
GET /deals/WBD-2026-Q1-001/export-csv?scenario=memory&rows=500000
```

- Generates large in-memory CSV string
- **Metric:** memory via CloudWatch Agent

---

### 7. Runtime error — Save draft with bad payload

**Story:** UI sends malformed optimizer output after schema change.

```
POST /save-draft?scenario=runtime
Body: { "contractId": null, "allocations": [] }
```

- Raises `ValueError("contractId required for save-draft")`
- **Log:** structured validation error with `dealId`, `endpoint`

---

### 8. 5xx rate — Flaky DDL optimizer

**Story:** Canary deploy; half of DDL runs fail.

```
POST /run-optimizer/ddl?scenario=fail_rate&rate=0.5
```

- Random 500 vs 200
- Load test 50 requests → error rate alarm fires

---

## Sample Request Bodies (Match Plans DTOs)

### Run optimizer (linear)

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

### Save draft

```json
{
  "contractId": "WBD-2026-Q1-001",
  "planTag": "Default",
  "allocations": [
    { "titleId": 101, "networkId": 1, "spots": 10, "spend": 50000 }
  ],
  "summary": {
    "totalSpend": 2500000,
    "totalImpressions": 120000000,
    "blendedCpm": 20.83
  }
}
```

### ADU run

```json
{
  "advertisers": [
    { "id": 1, "name": "Acme", "impressionDeficit": 500000 }
  ],
  "inventoryRules": {
    "networks": [1, 2],
    "startDate": "2026-03-01",
    "endDate": "2026-06-30",
    "availabilityPct": 0.1
  }
}
```

---

## Observability

### Structured logs (CloudWatch)

```json
{
  "level": "ERROR",
  "service": "plans-demo-api",
  "endpoint": "/run-optimizer/linear",
  "dealId": "WBD-2026-Q1-001",
  "scenario": "dependency",
  "message": "Optimizer unreachable at http://localhost:9999",
  "duration_ms": 1204,
  "trace_id": "abc-123"
}
```

### Metrics

| Metric | Source | Triggered by |
|---|---|---|
| `HTTPCode_Target_5XX_Count` | ALB | NPE, runtime, dependency, fail_rate |
| `TargetResponseTime` p99 | ALB | slow /deals, timeout /adu/run |
| `CPUUtilization` | EC2 | /adu/run?scenario=cpu |
| `mem_used_percent` | CW Agent | export-csv memory |
| `OptimizerErrors` (custom EMF) | App logs | linear/ddl/adu failures |
| `PlansSaveDraftErrors` (custom EMF) | App logs | save-draft failures |

---

## DeployGuard Trigger

On unhandled 500/503, middleware POSTs minimal payload:

```json
{
  "error_message": "ConnectionError: optimizer unreachable",
  "stack_trace": "<top 5 frames>",
  "service": "plans-demo-api",
  "environment": "demo",
  "context": {
    "endpoint": "/run-optimizer/linear",
    "dealId": "WBD-2026-Q1-001",
    "scenario": "dependency",
    "deploy_sha": "abc123",
    "log_snippet": "Optimizer error: connection refused"
  },
  "triggered_by": "ec2"
}
```

**Best demo trigger:** `POST /run-optimizer/linear?scenario=dependency` — maps directly to real Plans → Optimizer integration failures.

---

## 5-Minute Judge Demo Script

```bash
HOST=http://<ec2>:8088

# 1. Happy path — dashboard
curl $HOST/health
curl $HOST/deals
curl $HOST/deals/WBD-2026-Q1-001

# 2. NPE — broken deploy (DeployGuard + JIRA)
curl -X POST "$HOST/run-optimizer/linear?scenario=npe" \
  -H "Content-Type: application/json" \
  -d '{"payload":{"dealId":"WBD-2026-Q1-001","budget":2500000},"networkIds":[1]}'

# 3. Dependency down — optimizer unreachable (most realistic)
curl -X POST "$HOST/run-optimizer/linear?scenario=dependency" \
  -H "Content-Type: application/json" \
  -d '{"payload":{"dealId":"WBD-2026-Q1-001"},"networkIds":[1]}'

# 4. P99 — slow dashboard
for i in $(seq 1 25); do curl "$HOST/deals?scenario=slow" & done; wait

# 5. ADU timeout
curl -X POST "$HOST/adu/run?scenario=timeout" \
  -H "Content-Type: application/json" \
  -d '{"advertisers":[{"id":1,"impressionDeficit":500000}],"inventoryRules":{"networks":[1],"startDate":"2026-03-01","endDate":"2026-06-30"}}'

# 6. CPU spike
curl -X POST "$HOST/adu/run?scenario=cpu&duration=45" \
  -H "Content-Type: application/json" \
  -d '{"advertisers":[{"id":1}],"inventoryRules":{"networks":[1],"startDate":"2026-03-01","endDate":"2026-06-30"}}'

# 7. Memory — large CSV export
curl "$HOST/deals/WBD-2026-Q1-001/export-csv?scenario=memory&rows=300000" -o /dev/null

# 8. Save draft validation error
curl -X POST "$HOST/save-draft?scenario=runtime" \
  -H "Content-Type: application/json" \
  -d '{"contractId":null,"allocations":[]}'
```

---

## Mapping to Real Plans Service

| Demo endpoint | Real file reference |
|---|---|
| `POST /run-optimizer/linear` | `plans.controller.ts` → `runOptimizerLinear` |
| `POST /adu/run` | `plans.controller.ts` → `runAduOptimizer` (optimizer fetch) |
| `POST /save-draft` | `plans.controller.ts` → `saveDraft` |
| `GET /deals` | `plans.controller.ts` → `listDeals` |
| `GET /deals/{id}/export-csv` | `plans.controller.ts` → `exportCsv` |

---

## Keep Basic — Skip for Hackathon

- Real Postgres / TypeORM
- Cognito / JWT auth (use `X-Demo-Scenario` header instead)
- Full container/version branching API
- Real optimizer integration (mock on :3030 is enough)

---

## Summary

Replace generic ShopMini with **Plans Demo API** — same port (8088), same business language (deals, optimizer, ADU, save-draft, CSV export). Failure modes attach to **real critical paths** your team already knows, so DeployGuard demos tell a credible story: *"Optimizer broke after deploy → Plans service 503 → agent correlates commit + logs + metrics → RCA + JIRA."*
