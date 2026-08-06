import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchDashboardStats, fetchIncidents } from "../api/client";
import { BreakdownPanels, StatsCards } from "../components/StatsCards";
import { IncidentTable } from "../components/IncidentTable";
import type { DashboardStats, IncidentSummary } from "../types";

export function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const serviceFilter = searchParams.get("service") || "";
  const statusFilter = searchParams.get("status") || "";

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsResult, listResult] = await Promise.all([
        fetchDashboardStats(serviceFilter || undefined),
        fetchIncidents({
          service: serviceFilter || undefined,
          status: statusFilter || undefined,
          limit: 25,
        }),
      ]);
      setStats(statsResult);
      setIncidents(listResult.items);
      setNextPageToken(listResult.next_page_token ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [serviceFilter, statusFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const loadMore = async () => {
    if (!nextPageToken) return;
    setLoadingMore(true);
    try {
      const listResult = await fetchIncidents({
        service: serviceFilter || undefined,
        status: statusFilter || undefined,
        limit: 25,
        page_token: nextPageToken,
      });
      setIncidents((prev) => [...prev, ...listResult.items]);
      setNextPageToken(listResult.next_page_token ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more incidents");
    } finally {
      setLoadingMore(false);
    }
  };

  const updateFilter = (key: "service" | "status", value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  };

  const services = stats
    ? Object.keys(stats.by_service).sort()
    : [...new Set(incidents.map((i) => i.service))].sort();

  return (
    <div className="dashboard-page">
      <section className="page-header">
        <div>
          <p className="eyebrow">Operations center</p>
          <h1>Incident dashboard</h1>
          <p className="page-subtitle">
            Monitor production failures, AI root-cause analysis, and downstream actions across your services.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => void loadData()}>
          Refresh
        </button>
      </section>

      <StatsCards stats={stats} incidentCount={incidents.length} />
      <BreakdownPanels stats={stats} />

      <section className="filters-bar panel">
        <label>
          Service
          <select value={serviceFilter} onChange={(e) => updateFilter("service", e.target.value)}>
            <option value="">All services</option>
            {services.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </select>
        </label>

        <label>
          Investigation status
          <select value={statusFilter} onChange={(e) => updateFilter("status", e.target.value)}>
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
        </label>

        {(serviceFilter || statusFilter) && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setSearchParams(new URLSearchParams())}
          >
            Clear filters
          </button>
        )}
      </section>

      {error ? <div className="error-banner">{error}</div> : null}

      <IncidentTable items={incidents} loading={loading} />

      {nextPageToken ? (
        <div className="load-more-row">
          <button type="button" className="btn btn-secondary" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? "Loading…" : "Load more incidents"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
