import { Link, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { fetchHealth } from "../api/client";
import type { HealthResponse } from "../types";

export function Layout() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const isDetail = location.pathname.startsWith("/incidents/");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <Link to="/" className="brand-link">
            <span className="brand-mark" aria-hidden="true">
              DG
            </span>
            <div>
              <strong>DeployGuard</strong>
              <span>Production incident intelligence</span>
            </div>
          </Link>
        </div>

        <nav className="topbar-nav">
          <Link to="/" className={!isDetail ? "nav-active" : ""}>
            Dashboard
          </Link>
          <a href="/docs" target="_blank" rel="noreferrer">
            API Docs
          </a>
        </nav>

        <div className="topbar-status">
          {health ? (
            <>
              <span className={`health-dot health-${health.status}`} />
              <span>{health.status === "ok" ? "All systems operational" : "Degraded"}</span>
              {health.postgres_reachable === false ? <span className="status-note">DB offline</span> : null}
            </>
          ) : (
            <span className="muted">Checking health…</span>
          )}
        </div>
      </header>

      <main className="main-content">
        <Outlet />
      </main>

      <footer className="app-footer">
        <span>DeployGuard · Automated RCA · JIRA · Slack</span>
      </footer>
    </div>
  );
}
