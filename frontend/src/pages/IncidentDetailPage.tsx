import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { downloadRcaReport, fetchIncident, updateIncidentWorkflowStatus } from "../api/client";
import { ConfidenceMeter, InvestigationBadge, SeverityBadge, WorkflowBadge } from "../components/Badges";
import type { IncidentRecord } from "../types";
import { formatDate, formatConfidence } from "../utils/format";

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    fetchIncident(id)
      .then(setIncident)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load incident"))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleCloseIncident() {
    if (!id || !incident) return;
    setClosing(true);
    setActionError(null);
    try {
      const updated = await updateIncidentWorkflowStatus(id, "closed");
      setIncident(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to close incident");
    } finally {
      setClosing(false);
    }
  }

  async function handleDownloadRca() {
    if (!id) return;
    setDownloading(true);
    setActionError(null);
    try {
      await downloadRcaReport(id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to download RCA report");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return <div className="panel detail-panel loading-state">Loading incident…</div>;
  }

  if (error || !incident) {
    return (
      <div className="panel detail-panel">
        <p className="error-banner">{error || "Incident not found"}</p>
        <Link to="/" className="btn btn-secondary">
          Back to dashboard
        </Link>
      </div>
    );
  }

  const severity = incident.input.context?.severity;
  const workflowStatus = incident.workflow_status ?? "open";
  const canClose = workflowStatus === "open";
  const canDownloadRca = incident.metadata.status === "completed";

  return (
    <div className="detail-page">
      <div className="detail-header">
        <Link to="/" className="back-link">
          ← Back to dashboard
        </Link>
        <div className="detail-title-row">
          <div>
            <p className="eyebrow">{incident.service} · {incident.environment}</p>
            <h1>{incident.root_cause || "Investigation in progress"}</h1>
            <p className="page-subtitle mono">{incident.investigation_id}</p>
          </div>
          <div className="detail-badges">
            <InvestigationBadge status={incident.metadata.status} />
            <WorkflowBadge status={workflowStatus} />
            <SeverityBadge severity={severity} />
          </div>
        </div>
        <div className="detail-meta-grid">
          <div>
            <span className="meta-label">Occurred</span>
            <strong>{formatDate(incident.timestamp)}</strong>
          </div>
          <div>
            <span className="meta-label">Triggered by</span>
            <strong>{incident.metadata.triggered_by}</strong>
          </div>
          <div>
            <span className="meta-label">Confidence</span>
            <strong>{formatConfidence(incident.confidence)}</strong>
          </div>
          <div>
            <span className="meta-label">Latency</span>
            <strong>{incident.metadata.latency_ms} ms</strong>
          </div>
        </div>
        <div className="detail-actions">
          {canClose ? (
            <button type="button" className="btn btn-primary" disabled={closing} onClick={handleCloseIncident}>
              {closing ? "Closing…" : "Close incident"}
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!canDownloadRca || downloading}
            onClick={handleDownloadRca}
            title={canDownloadRca ? "Download RCA report as Markdown" : "RCA report unavailable for failed investigations"}
          >
            {downloading ? "Downloading…" : "Download RCA report"}
          </button>
        </div>
        {actionError ? <p className="error-banner detail-action-error">{actionError}</p> : null}
      </div>

      <div className="detail-grid">
        <section className="panel detail-section">
          <h2>Root cause analysis</h2>
          {incident.rca_summary ? <p className="lead-text">{incident.rca_summary}</p> : null}
          {incident.suggested_fix ? (
            <div className="callout callout-fix">
              <h3>Suggested fix</h3>
              <p>{incident.suggested_fix}</p>
            </div>
          ) : null}
          {incident.evidence.length > 0 ? (
            <>
              <h3>Evidence</h3>
              <ul className="evidence-list">
                {incident.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
          {incident.error_detail ? (
            <div className="callout callout-error">
              <h3>Investigation error</h3>
              <p>{incident.error_detail}</p>
            </div>
          ) : null}
        </section>

        <section className="panel detail-section">
          <h2>Original error</h2>
          <pre className="code-block">{incident.input.error_message}</pre>
          {incident.input.stack_trace ? (
            <>
              <h3>Stack trace</h3>
              <pre className="code-block code-scroll">{incident.input.stack_trace}</pre>
            </>
          ) : null}
          {incident.input.context?.log_snippet ? (
            <>
              <h3>Log snippet</h3>
              <pre className="code-block code-scroll">{incident.input.context.log_snippet}</pre>
            </>
          ) : null}
        </section>

        <section className="panel detail-section">
          <h2>Actions taken</h2>
          <div className="actions-grid">
            <div className="action-card">
              <span className="meta-label">JIRA</span>
              {incident.actions.jira_url ? (
                <a href={incident.actions.jira_url} target="_blank" rel="noreferrer" className="action-link">
                  {incident.actions.jira_ticket}
                </a>
              ) : (
                <span className="muted">No ticket created</span>
              )}
            </div>
            <div className="action-card">
              <span className="meta-label">Slack alert</span>
              <strong>{incident.actions.slack_sent ? "Sent" : "Not sent"}</strong>
            </div>
            <div className="action-card">
              <span className="meta-label">Confidence score</span>
              <ConfidenceMeter value={incident.confidence} />
            </div>
          </div>

          {(incident.input.context?.job_id || incident.input.context?.run_id) && (
            <>
              <h3>Databricks context</h3>
              <dl className="kv-list">
                {incident.input.context.job_id ? (
                  <>
                    <dt>Job ID</dt>
                    <dd className="mono">{incident.input.context.job_id}</dd>
                  </>
                ) : null}
                {incident.input.context.run_id ? (
                  <>
                    <dt>Run ID</dt>
                    <dd className="mono">{incident.input.context.run_id}</dd>
                  </>
                ) : null}
                {incident.input.context.task_name ? (
                  <>
                    <dt>Task</dt>
                    <dd>{incident.input.context.task_name}</dd>
                  </>
                ) : null}
              </dl>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
