-- DeployGuard incident store — PostgreSQL schema (v1)
--
-- Target: Aurora PostgreSQL 17+ in dev account (usadsales-postgre cluster).
-- Database: deployguard (create via 00_create_database.sql first).
--
-- Storage model:
--   - Full RCA document (rca.md) and incident archive live in S3.
--   - Postgres stores only S3 URIs (rca_s3_uri, s3_report_uri) plus structured fields.
--   - Incidents start unassigned; JIRA ticket creation is not wired yet.
--
-- Apply: psql "$DATABASE_URL" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------

CREATE TYPE triggered_by AS ENUM ('databricks', 'ec2', 'manual');

CREATE TYPE severity_level AS ENUM ('low', 'medium', 'high', 'critical');

-- Bedrock investigation outcome (matches IncidentMetadata.status)
CREATE TYPE investigation_status AS ENUM ('completed', 'failed');

-- Human workflow status for the dashboard (assignee progress)
CREATE TYPE workflow_status AS ENUM ('open', 'in_progress', 'resolved', 'closed');

-- ---------------------------------------------------------------------------
-- developers — people who can be assigned to incidents (populated later)
-- ---------------------------------------------------------------------------

CREATE TABLE developers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    VARCHAR(128) NOT NULL,
    email           VARCHAR(255) UNIQUE,
    jira_account_id VARCHAR(64),
    slack_user_id   VARCHAR(64),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE developers IS
    'Engineers assignable to incidents. Empty at bootstrap; filled when JIRA/dashboard integration lands.';

-- ---------------------------------------------------------------------------
-- incidents — one row per POST /api/v1/investigate
-- ---------------------------------------------------------------------------

CREATE TABLE incidents (
    investigation_id    UUID PRIMARY KEY,

    -- When the error occurred (from request) vs when we investigated it
    occurred_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Identity
    service             VARCHAR(128) NOT NULL,
    environment         VARCHAR(32)  NOT NULL,
    triggered_by        triggered_by NOT NULL,

    -- Original request (full InvestigateRequest JSON for detail view)
    input_payload       JSONB NOT NULL,

    -- Denormalized error fields (for list/search without parsing JSONB)
    error_message       TEXT NOT NULL,
    stack_trace         TEXT,
    severity            severity_level,
    deploy_sha          VARCHAR(64),
    log_snippet         TEXT,
    databricks_job_id   VARCHAR(128),
    databricks_run_id   VARCHAR(128),
    databricks_task     VARCHAR(128),

    -- RCA — structured Bedrock output (summary fields for list/dashboard)
    root_cause          VARCHAR(200),
    confidence          NUMERIC(4, 3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    rca_summary         VARCHAR(500),
    suggested_fix       VARCHAR(300),
    evidence            JSONB NOT NULL DEFAULT '[]'::JSONB,
    error_detail        TEXT,

    -- RCA document — S3 only (full rca.md content is NOT stored in Postgres)
    rca_s3_uri          VARCHAR(512),
    s3_report_uri       VARCHAR(512),

    -- Status (two layers: AI investigation vs human workflow)
    investigation_status investigation_status NOT NULL,
    workflow_status      workflow_status NOT NULL DEFAULT 'open',

    -- People — NULL until assignee is set via dashboard/JIRA integration
    assigned_developer_id UUID REFERENCES developers (id) ON DELETE SET NULL,

    -- JIRA — NULL/false until ticket creation is integrated
    jira_ticket         VARCHAR(32),
    jira_url            VARCHAR(512),
    jira_created        BOOLEAN NOT NULL DEFAULT FALSE,
    slack_sent          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Operational metadata
    latency_ms          INTEGER NOT NULL DEFAULT 0,
    token_estimate      INTEGER NOT NULL DEFAULT 0
);

COMMENT ON TABLE incidents IS
    'One row per investigation. New incidents are unassigned with no JIRA ticket until integrations run.';
COMMENT ON COLUMN incidents.investigation_status IS 'Bedrock outcome: completed or failed.';
COMMENT ON COLUMN incidents.workflow_status IS 'Human lifecycle: open → in_progress → resolved → closed.';
COMMENT ON COLUMN incidents.rca_s3_uri IS 'S3 URI to rca.md (e.g. s3://bucket/2026/08/{id}/rca.md).';
COMMENT ON COLUMN incidents.s3_report_uri IS 'S3 prefix for the full incident archive folder.';
COMMENT ON COLUMN incidents.assigned_developer_id IS 'NULL = unassigned. Set when developer claims or is assigned.';
COMMENT ON COLUMN incidents.jira_ticket IS 'NULL until JIRA ticket creation is integrated.';
COMMENT ON COLUMN incidents.occurred_at IS 'Error timestamp from client payload (not investigation start time).';

-- ---------------------------------------------------------------------------
-- incident_watchers — optional tagged engineers (future JIRA watchers / Slack @)
-- ---------------------------------------------------------------------------

CREATE TABLE incident_watchers (
    incident_id   UUID NOT NULL REFERENCES incidents (investigation_id) ON DELETE CASCADE,
    developer_id  UUID NOT NULL REFERENCES developers (id) ON DELETE CASCADE,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (incident_id, developer_id)
);

-- ---------------------------------------------------------------------------
-- Indexes — tuned for dashboard queries
-- ---------------------------------------------------------------------------

CREATE INDEX idx_incidents_occurred_at_desc
    ON incidents (occurred_at DESC);

CREATE INDEX idx_incidents_created_at_desc
    ON incidents (created_at DESC);

CREATE INDEX idx_incidents_service
    ON incidents (service);

CREATE INDEX idx_incidents_environment
    ON incidents (environment);

CREATE INDEX idx_incidents_workflow_status
    ON incidents (workflow_status);

CREATE INDEX idx_incidents_investigation_status
    ON incidents (investigation_status);

CREATE INDEX idx_incidents_unassigned
    ON incidents (occurred_at DESC)
    WHERE assigned_developer_id IS NULL;

CREATE INDEX idx_incidents_assigned_developer
    ON incidents (assigned_developer_id)
    WHERE assigned_developer_id IS NOT NULL;

CREATE INDEX idx_incidents_severity
    ON incidents (severity)
    WHERE severity IS NOT NULL;

CREATE INDEX idx_incidents_no_jira
    ON incidents (created_at DESC)
    WHERE jira_ticket IS NULL;

CREATE INDEX idx_incidents_service_occurred_at
    ON incidents (service, occurred_at DESC);

CREATE INDEX idx_incidents_workflow_occurred_at
    ON incidents (workflow_status, occurred_at DESC);

CREATE INDEX idx_incidents_input_payload_gin
    ON incidents USING GIN (input_payload);

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_incidents_updated_at
    BEFORE UPDATE ON incidents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_developers_updated_at
    BEFORE UPDATE ON developers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Dashboard views
-- ---------------------------------------------------------------------------

CREATE VIEW v_incident_list AS
SELECT
    i.investigation_id,
    i.occurred_at,
    i.created_at,
    i.service,
    i.environment,
    i.investigation_status,
    i.workflow_status,
    i.root_cause,
    i.confidence,
    i.severity,
    i.jira_ticket,
    i.jira_url,
    i.jira_created,
    i.slack_sent,
    i.rca_s3_uri,
    i.s3_report_uri,
    i.assigned_developer_id IS NULL AS is_unassigned,
    d.display_name  AS assigned_developer_name,
    d.email         AS assigned_developer_email,
    (i.rca_s3_uri IS NOT NULL) AS has_rca_document
FROM incidents i
LEFT JOIN developers d ON d.id = i.assigned_developer_id;

COMMENT ON VIEW v_incident_list IS
    'Dashboard table: all incidents, unassigned flag, RCA doc availability via S3 URI.';

CREATE VIEW v_incident_detail AS
SELECT
    i.*,
    i.assigned_developer_id IS NULL AS is_unassigned,
    d.display_name  AS assigned_developer_name,
    d.email         AS assigned_developer_email,
    d.jira_account_id AS assigned_developer_jira_id,
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', w.developer_id,
                    'display_name', dw.display_name,
                    'email', dw.email
                )
            )
            FROM incident_watchers w
            JOIN developers dw ON dw.id = w.developer_id
            WHERE w.incident_id = i.investigation_id
        ),
        '[]'::JSONB
    ) AS watchers
FROM incidents i
LEFT JOIN developers d ON d.id = i.assigned_developer_id;

-- ---------------------------------------------------------------------------
-- Dashboard aggregation function
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_dashboard_stats(
    p_service VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    total_all           BIGINT,
    total_last_7_days   BIGINT,
    total_last_30_days  BIGINT,
    open_count          BIGINT,
    in_progress_count   BIGINT,
    resolved_count      BIGINT,
    closed_count        BIGINT,
    unassigned_count    BIGINT,
    no_jira_count       BIGINT,
    failed_count        BIGINT,
    by_service          JSONB,
    by_severity         JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM incidents i
        WHERE p_service IS NULL OR i.service = p_service
    ),
    time_counts AS (
        SELECT
            COUNT(*)::BIGINT AS total_all,
            COUNT(*) FILTER (WHERE occurred_at >= NOW() - INTERVAL '7 days')::BIGINT AS total_last_7_days,
            COUNT(*) FILTER (WHERE occurred_at >= NOW() - INTERVAL '30 days')::BIGINT AS total_last_30_days,
            COUNT(*) FILTER (WHERE workflow_status = 'open')::BIGINT AS open_count,
            COUNT(*) FILTER (WHERE workflow_status = 'in_progress')::BIGINT AS in_progress_count,
            COUNT(*) FILTER (WHERE workflow_status = 'resolved')::BIGINT AS resolved_count,
            COUNT(*) FILTER (WHERE workflow_status = 'closed')::BIGINT AS closed_count,
            COUNT(*) FILTER (WHERE assigned_developer_id IS NULL)::BIGINT AS unassigned_count,
            COUNT(*) FILTER (WHERE jira_ticket IS NULL)::BIGINT AS no_jira_count,
            COUNT(*) FILTER (WHERE investigation_status = 'failed')::BIGINT AS failed_count
        FROM filtered
    ),
    service_breakdown AS (
        SELECT COALESCE(jsonb_object_agg(service, cnt), '{}'::JSONB) AS by_service
        FROM (
            SELECT service, COUNT(*)::BIGINT AS cnt
            FROM filtered
            GROUP BY service
        ) s
    ),
    severity_breakdown AS (
        SELECT COALESCE(jsonb_object_agg(severity::TEXT, cnt), '{}'::JSONB) AS by_severity
        FROM (
            SELECT severity, COUNT(*)::BIGINT AS cnt
            FROM filtered
            WHERE severity IS NOT NULL
            GROUP BY severity
        ) s
    )
    SELECT
        t.total_all,
        t.total_last_7_days,
        t.total_last_30_days,
        t.open_count,
        t.in_progress_count,
        t.resolved_count,
        t.closed_count,
        t.unassigned_count,
        t.no_jira_count,
        t.failed_count,
        sb.by_service,
        sv.by_severity
    FROM time_counts t
    CROSS JOIN service_breakdown sb
    CROSS JOIN severity_breakdown sv;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_dashboard_stats IS
    'Dashboard KPI cards: totals, unassigned count, JIRA-not-created count, breakdowns.';
