import { Link } from "react-router-dom";
import type { IncidentSummary } from "../types";
import { formatDate, formatRelative, shortId, truncate } from "../utils/format";
import { ConfidenceMeter, InvestigationBadge, SeverityBadge, WorkflowBadge } from "./Badges";

interface IncidentTableProps {
  items: IncidentSummary[];
  loading?: boolean;
}

export function IncidentTable({ items, loading }: IncidentTableProps) {
  if (loading) {
    return (
      <div className="panel table-panel">
        <div className="loading-state">Loading incidents…</div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="panel table-panel">
        <div className="empty-state">
          <h3>No incidents yet</h3>
          <p>When DeployGuard investigates a production failure, it will appear here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="panel table-panel">
      <div className="table-scroll">
        <table className="incident-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Service</th>
              <th>Root cause</th>
              <th>Severity</th>
              <th>Confidence</th>
              <th>Workflow</th>
              <th>Status</th>
              <th>Integrations</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.investigation_id}>
                <td>
                  <Link to={`/incidents/${item.investigation_id}`} className="row-link">
                    <span className="time-primary">{formatRelative(item.timestamp)}</span>
                    <span className="time-secondary">{formatDate(item.timestamp)}</span>
                  </Link>
                </td>
                <td>
                  <div className="service-cell">
                    <strong>{item.service}</strong>
                    <span className="mono">{item.environment}</span>
                    <span className="mono muted">{shortId(item.investigation_id)}</span>
                  </div>
                </td>
                <td className="cause-cell">
                  <Link to={`/incidents/${item.investigation_id}`} className="cause-link">
                    {truncate(item.root_cause || item.rca_summary || "Pending analysis", 72)}
                  </Link>
                </td>
                <td>
                  <SeverityBadge severity={item.severity} />
                </td>
                <td>
                  <ConfidenceMeter value={item.confidence} />
                </td>
                <td>
                  <WorkflowBadge status={item.workflow_status} />
                </td>
                <td>
                  <InvestigationBadge status={item.status} />
                </td>
                <td>
                  <div className="integration-icons">
                    {item.jira_url ? (
                      <a href={item.jira_url} target="_blank" rel="noreferrer" className="chip chip-jira">
                        {item.jira_ticket || "JIRA"}
                      </a>
                    ) : (
                      <span className="chip chip-muted">No JIRA</span>
                    )}
                    {item.slack_sent ? <span className="chip chip-slack">Slack</span> : null}
                    {item.triggered_by ? <span className="chip chip-source">{item.triggered_by}</span> : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
