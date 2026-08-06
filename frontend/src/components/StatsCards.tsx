import { Link } from "react-router-dom";
import type { DashboardStats } from "../types";

interface StatsCardsProps {
  stats: DashboardStats | null;
  incidentCount: number;
}

function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: number | string;
  hint?: string;
  tone?: "default" | "warn" | "danger" | "success";
}) {
  return (
    <article className={`stat-card stat-${tone}`}>
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {hint ? <p className="stat-hint">{hint}</p> : null}
    </article>
  );
}

export function StatsCards({ stats, incidentCount }: StatsCardsProps) {
  if (!stats) {
    return (
      <section className="stats-grid stats-fallback">
        <StatCard label="Total incidents" value={incidentCount} hint="Stats DB unavailable — showing list count" />
        <StatCard label="Last 7 days" value="—" />
        <StatCard label="Open workflow" value="—" />
        <StatCard label="Needs JIRA" value="—" />
      </section>
    );
  }

  return (
    <section className="stats-grid">
      <StatCard label="Total incidents" value={stats.total_all} hint={`${stats.total_last_7_days} in last 7 days`} />
      <StatCard
        label="Open / in progress"
        value={stats.open_count + stats.in_progress_count}
        hint={`${stats.open_count} open · ${stats.in_progress_count} active`}
        tone="warn"
      />
      <StatCard
        label="Resolved"
        value={stats.resolved_count + stats.closed_count}
        hint={`${stats.resolved_count} resolved · ${stats.closed_count} closed`}
        tone="success"
      />
      <StatCard label="Unassigned" value={stats.unassigned_count} tone={stats.unassigned_count > 0 ? "warn" : "default"} />
      <StatCard label="No JIRA ticket" value={stats.no_jira_count} tone={stats.no_jira_count > 0 ? "danger" : "default"} />
      <StatCard label="Investigation failed" value={stats.failed_count} tone={stats.failed_count > 0 ? "danger" : "default"} />
    </section>
  );
}

export function BreakdownPanels({ stats }: { stats: DashboardStats | null }) {
  if (!stats) return null;

  const services = Object.entries(stats.by_service).sort((a, b) => b[1] - a[1]);
  const severities = Object.entries(stats.by_severity).sort((a, b) => b[1] - a[1]);

  if (services.length === 0 && severities.length === 0) return null;

  return (
    <section className="breakdown-grid">
      {services.length > 0 ? (
        <article className="panel">
          <h3>By service</h3>
          <ul className="breakdown-list">
            {services.map(([name, count]) => (
              <li key={name}>
                <Link to={`/?service=${encodeURIComponent(name)}`}>{name}</Link>
                <span>{count}</span>
              </li>
            ))}
          </ul>
        </article>
      ) : null}
      {severities.length > 0 ? (
        <article className="panel">
          <h3>By severity</h3>
          <ul className="breakdown-list">
            {severities.map(([name, count]) => (
              <li key={name}>
                <span className={`severity-dot severity-${name}`}>{name}</span>
                <span>{count}</span>
              </li>
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}
