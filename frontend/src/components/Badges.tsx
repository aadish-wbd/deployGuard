import type { InvestigationStatus, Severity, WorkflowStatus } from "../types";

const severityClass: Record<Severity, string> = {
  low: "badge badge-severity-low",
  medium: "badge badge-severity-medium",
  high: "badge badge-severity-high",
  critical: "badge badge-severity-critical",
};

const workflowClass: Record<WorkflowStatus, string> = {
  open: "badge badge-workflow-open",
  in_progress: "badge badge-workflow-progress",
  resolved: "badge badge-workflow-resolved",
  closed: "badge badge-workflow-closed",
};

const statusClass: Record<InvestigationStatus, string> = {
  completed: "badge badge-status-completed",
  failed: "badge badge-status-failed",
};

export function SeverityBadge({ severity }: { severity?: Severity | null }) {
  if (!severity) return <span className="badge badge-muted">—</span>;
  return <span className={severityClass[severity]}>{severity}</span>;
}

export function WorkflowBadge({ status }: { status?: WorkflowStatus }) {
  const value = status ?? "open";
  const label = value.replace("_", " ");
  return <span className={workflowClass[value]}>{label}</span>;
}

export function InvestigationBadge({ status }: { status: InvestigationStatus }) {
  return <span className={statusClass[status]}>{status}</span>;
}

export function ConfidenceMeter({ value }: { value?: number | null }) {
  if (value == null) return <span className="muted">—</span>;
  const pct = Math.round(value * 100);
  const tone = pct >= 80 ? "high" : pct >= 50 ? "mid" : "low";
  return (
    <div className="confidence-meter" title={`${pct}% confidence`}>
      <div className="confidence-track">
        <div className={`confidence-fill confidence-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span>{pct}%</span>
    </div>
  );
}
