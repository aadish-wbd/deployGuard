# DeployGuard — Requirements

## Overview

DeployGuard is a Python REST service that automates production incident investigation. Clients (Databricks jobs, EC2 services, or manual triggers) send error details to `POST /api/v1/investigate`. The service invokes an Amazon Bedrock Agent to analyze the error using indexed codebase and observability data, then creates a JIRA ticket and sends a Slack alert with an evidence-backed RCA.

---

## Functional Requirements

### FR-1: Investigation API

The system shall expose a Python REST endpoint `POST /api/v1/investigate` that accepts an error payload and returns a structured investigation result including root cause, confidence, RCA summary, JIRA ticket ID, and status.

### FR-2: Error Ingestion

The system shall accept, at minimum:

- Error message
- Stack trace (optional)
- Service name and environment
- Timestamp
- Optional context (deploy SHA, log snippet, job/run ID)

### FR-3: Bedrock-Powered Analysis

The system shall invoke an Amazon Bedrock Agent to analyze the error. Bedrock shall retrieve relevant context from:

- **Code Knowledge Base** — indexed GitHub repository code
- **Metrics Knowledge Base** — indexed CloudWatch metrics, logs, and custom observability exports

The agent shall correlate code and observability data to identify the likely root cause and produce an evidence-backed RCA.

### FR-4: JIRA Integration

On successful investigation, the system shall create a JIRA ticket containing:

- Summary (service + error type)
- Full RCA in the description
- Priority/labels from the request or derived from severity
- Assignee and watchers (tag relevant people)

### FR-5: Slack Notification

The system shall post a concise Slack alert to the configured channel with:

- Root cause summary
- Confidence score
- JIRA ticket link
- @mentions for on-call engineers

### FR-6: Client Integration

The system shall be callable over HTTP by:

- Databricks jobs (on job failure)
- EC2 REST services (exception handler / async fire-and-forget)
- Manual triggers (Postman, curl)

### FR-7: Health Check

The system shall expose `GET /health` to verify the service and Bedrock connectivity.

### FR-8: Future Scope (Out of v1)

- Auto-trigger from CloudWatch alarms / deploy events
- Previous-incidents directory and feedback-based learning
- Automated GitHub PR and code fix generation

---

## Non-Functional Requirements

### NFR-1: Token Efficiency — Prompt Design

Error prompts sent to Bedrock shall be **minimal, structured, and high-signal** to reduce token usage and cost.

**Rules for client-submitted payloads:**

| Field | Guideline |
|---|---|
| `error_message` | One line; strip boilerplate and repeated frames |
| `stack_trace` | Top 5–10 frames only; omit library/framework noise |
| `context.log_snippet` | Max 10–20 lines; only lines matching the error |
| `context.metrics` | Key-value pairs, not prose (e.g. `5xx_rate:8.2%,baseline:0.1%`) |
| Free-text fields | Avoid; use structured JSON keys instead |

**Example — verbose (avoid):**

```text
We deployed version 2.3.1 to production around 10:30 AM and after that
we started seeing a lot of 500 errors in the payment API...
```

**Example — minimal (preferred):**

```json
{
  "error_message": "NullPointerException: PAYMENT_URL is null",
  "service": "payment-api",
  "context": {
    "deploy_sha": "abc123",
    "5xx_rate": "8.2%",
    "log_snippet": "PaymentHandler.java:42 PAYMENT_URL null"
  }
}
```

### NFR-2: Token Efficiency — Prompt Assembly

The Python service shall assemble the Bedrock prompt using a fixed template with placeholders — no redundant instructions on every request.

| Optimization | Approach |
|---|---|
| System prompt | Stored once in Bedrock Agent config; not resent per call |
| Static instructions | RCA format, output schema, tone — in agent definition, not request body |
| Dynamic content only | Error fields + service metadata in the user turn |
| No duplicate context | Do not repeat the same field in multiple keys |

### NFR-3: Token Efficiency — Bedrock Retrieval

Knowledge Base retrieval shall return **top-K relevant chunks only** (e.g. K=5–10), not full files or repos.

| Control | Setting |
|---|---|
| Chunk size | 300–512 tokens per chunk at index time |
| Retrieval count | `numberOfResults: 5–8` per Knowledge Base |
| Metadata filtering | Filter by `service`, `repo`, or `time_window` before semantic search |
| Code retrieval | File path + relevant function, not entire module |

### NFR-4: Token Efficiency — Response Format

Bedrock output shall use a **structured JSON schema** (fixed fields, no markdown essays) to keep response tokens low and parsing reliable.

Required output fields:

```json
{
  "root_cause": "string (max 200 chars)",
  "confidence": 0.0,
  "evidence": ["string (max 3–5 items)"],
  "rca_summary": "string (max 500 chars)",
  "suggested_fix": "string (max 300 chars)"
}
```

RCA expansion for JIRA/Slack shall happen in Python using a template — not by asking the model to write long-form prose.

### NFR-5: Token Efficiency — Session & Caching

| Technique | Benefit |
|---|---|
| Bedrock Agent session ID per incident | Avoids resending prior context on follow-up turns |
| Cache repeated file retrievals within one investigation | Same chunk not re-injected into context |
| Deduplicate identical investigations | Hash `(error_message + service + deploy_sha)`; return cached result if within TTL (e.g. 5 min) |

### NFR-6: Performance

| Metric | Target |
|---|---|
| End-to-end `/investigate` latency | ≤ 90 seconds (p95) |
| Bedrock agent tool/retrieval rounds | ≤ 5 per investigation |
| API timeout for clients | 120 seconds |

### NFR-7: Availability & Reliability

- Service shall handle Bedrock throttling with exponential backoff (max 3 retries).
- If Bedrock fails, return a partial response with status `failed` and error detail — no silent failure.
- JIRA/Slack failures shall not block the API response; failures logged and flagged in response (`jira_created: false`).

### NFR-8: Security

- GitHub, JIRA, and Slack credentials stored in AWS Secrets Manager — not in code or request payloads.
- EC2 instance role with least-privilege IAM (`bedrock:InvokeAgent`, `secretsmanager:GetSecretValue`).
- Request payloads shall not contain secrets, full env dumps, or PII.

### NFR-9: Observability

- All investigations logged with `investigation_id`, token usage estimate, latency, and outcome.
- CloudWatch Logs for the Python service; optional custom metric `DeployGuard/InvestigationCount`.

### NFR-10: Cost Control

| Guardrail | Limit |
|---|---|
| Max input tokens per request | ~2,000 (enforced by payload validation) |
| Max output tokens | ~800 (set in Bedrock inference config) |
| Max retrievals per KB | 8 |
| Daily investigation cap (optional) | Configurable rate limit on `/investigate` |

---

## Payload Size Limits (Enforced by API)

| Field | Max Size |
|---|---|
| `error_message` | 500 chars |
| `stack_trace` | 2,000 chars |
| `context.log_snippet` | 1,500 chars |
| Total request body | 8 KB |

Requests exceeding limits shall be rejected with `400 Bad Request` and guidance on how to trim the payload.

---

## Token Optimization Summary

**Principle:** Clients send **facts**, Bedrock returns **structured conclusions**, Python **expands for humans** (JIRA/Slack) — keeping LLM tokens focused on reasoning, not formatting or repetition.

| Layer | Responsibility |
|---|---|
| **Client** | Structured JSON, trimmed stack trace, key-value metrics |
| **Python service** | Validate/truncate payload, fixed prompt template, expand RCA for JIRA/Slack |
| **Bedrock agent** | System prompt in agent config, KB retrieval top-K with metadata filter, structured JSON output |
