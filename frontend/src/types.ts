export type InvestigationStatus = "completed" | "failed";
export type WorkflowStatus = "open" | "in_progress" | "resolved" | "closed";
export type Severity = "low" | "medium" | "high" | "critical";
export type TriggeredBy = "databricks" | "ec2" | "manual" | "cloudwatch_alarm";

export interface IncidentSummary {
  investigation_id: string;
  timestamp: string;
  service: string;
  environment: string;
  status: InvestigationStatus;
  root_cause?: string | null;
  confidence?: number | null;
  jira_ticket?: string | null;
  jira_url?: string | null;
  rca_summary?: string | null;
  severity?: Severity | null;
  workflow_status?: WorkflowStatus;
  triggered_by?: TriggeredBy | null;
  slack_sent?: boolean;
}

export interface IncidentListResponse {
  items: IncidentSummary[];
  next_page_token?: string | null;
}

export interface DashboardStats {
  total_all: number;
  total_last_7_days: number;
  total_last_30_days: number;
  open_count: number;
  in_progress_count: number;
  resolved_count: number;
  closed_count: number;
  unassigned_count: number;
  no_jira_count: number;
  failed_count: number;
  by_service: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface CloudWatchAlarmContext {
  alarm_name?: string | null;
  state?: string | null;
  reason?: string | null;
  metric_name?: string | null;
  namespace?: string | null;
  statistic?: string | null;
  threshold?: number | null;
  period?: number | null;
}

export interface InvestigateContext {
  deploy_sha?: string | null;
  log_snippet?: string | null;
  job_id?: string | null;
  run_id?: string | null;
  task_name?: string | null;
  severity?: Severity | null;
  cloudwatch_alarm?: CloudWatchAlarmContext | null;
}

export interface InvestigateRequest {
  error_message: string;
  stack_trace?: string | null;
  service: string;
  environment: string;
  timestamp: string;
  context?: InvestigateContext | null;
  triggered_by?: TriggeredBy;
}

export interface ActionsTaken {
  jira_ticket?: string | null;
  jira_url?: string | null;
  jira_created?: boolean;
  slack_sent?: boolean;
}

export interface IncidentMetadata {
  latency_ms: number;
  token_estimate: number;
  triggered_by: TriggeredBy;
  status: InvestigationStatus;
}

export interface IncidentRecord {
  investigation_id: string;
  timestamp: string;
  service: string;
  environment: string;
  input: InvestigateRequest;
  root_cause?: string | null;
  confidence?: number | null;
  evidence: string[];
  rca_summary?: string | null;
  suggested_fix?: string | null;
  error_detail?: string | null;
  actions: ActionsTaken;
  metadata: IncidentMetadata;
  workflow_status?: WorkflowStatus;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  bedrock_reachable: boolean;
  postgres_reachable?: boolean | null;
  detail?: string | null;
}
