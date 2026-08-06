from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import BedrockRcaOutput, IncidentListResponse


class FakeBedrockClient:
    def __init__(self, rca: Optional[BedrockRcaOutput] = None, error: Optional[Exception] = None):
        self._rca = rca or BedrockRcaOutput(
            root_cause="NullPointerException: PAYMENT_URL is null",
            confidence=0.9,
            evidence=["PaymentHandler.java:42"],
            rca_summary="Deploy abc123 removed the PAYMENT_URL env var.",
            suggested_fix="Restore PAYMENT_URL in the deployment config.",
        )
        self._error = error
        self.invocations = []

    def invoke(self, session_id: str, input_text: str) -> BedrockRcaOutput:
        self.invocations.append((session_id, input_text))
        if self._error:
            raise self._error
        return self._rca

    def health_check(self) -> bool:
        return self._error is None


class FakeJiraClient:
    def __init__(self, error: Optional[Exception] = None):
        self._error = error
        self.calls = []

    def create_ticket(self, request, rca):
        self.calls.append((request, rca))
        if self._error:
            raise self._error
        return "OPS-123", "https://jira.example.com/browse/OPS-123"


class FakeSlackClient:
    def __init__(self, error: Optional[Exception] = None):
        self._error = error
        self.calls = []

    def send_alert(self, request, rca, jira_url):
        self.calls.append((request, rca, jira_url))
        if self._error:
            raise self._error


class FakeS3Store:
    def __init__(self):
        self.saved = []

    def save(self, record) -> str:
        self.saved.append(record)
        return f"s3://fake-bucket/{record.s3_prefix()}/"

    def get(self, investigation_id: str):
        for record in self.saved:
            if record.investigation_id == investigation_id:
                return record
        return None

    def list(self, service=None, status=None, limit=20, page_token=None) -> IncidentListResponse:
        return IncidentListResponse(items=[])


class FakePostgresStore:
    def __init__(self):
        self.saved = []

    def ping(self) -> bool:
        return True

    def save(self, record, *, rca_s3_uri: str, s3_report_uri: str) -> None:
        self.saved.append((record, rca_s3_uri, s3_report_uri))

    def get(self, investigation_id: str):
        for record, _, _ in self.saved:
            if record.investigation_id == investigation_id:
                return record
        return None

    def list(self, service=None, status=None, limit=20, page_token=None) -> IncidentListResponse:
        items = []
        for record, _, _ in self.saved:
            if service and record.service != service:
                continue
            if status and record.metadata.status != status:
                continue
            items.append(
                {
                    "investigation_id": record.investigation_id,
                    "timestamp": record.timestamp,
                    "service": record.service,
                    "environment": record.environment,
                    "status": record.metadata.status,
                    "root_cause": record.root_cause,
                    "confidence": record.confidence,
                    "jira_ticket": record.actions.jira_ticket,
                }
            )
        from app.models.schemas import IncidentSummary

        summaries = [IncidentSummary(**item) for item in items[:limit]]
        return IncidentListResponse(items=summaries)

    def dashboard_stats(self, service=None):
        return {
            "total_all": len(self.saved),
            "total_last_7_days": len(self.saved),
            "total_last_30_days": len(self.saved),
            "open_count": len(self.saved),
            "in_progress_count": 0,
            "resolved_count": 0,
            "closed_count": 0,
            "unassigned_count": len(self.saved),
            "no_jira_count": len(self.saved),
            "failed_count": 0,
            "by_service": {},
            "by_severity": {},
        }

    def close(self) -> None:
        return None


@pytest.fixture
def fakes():
    return {
        "bedrock": FakeBedrockClient(),
        "jira": FakeJiraClient(),
        "slack": FakeSlackClient(),
        "s3": FakeS3Store(),
        "postgres": FakePostgresStore(),
    }


@pytest.fixture
def client(fakes):
    with TestClient(app) as test_client:
        test_client.app.state.bedrock_client = fakes["bedrock"]
        test_client.app.state.jira_client = fakes["jira"]
        test_client.app.state.slack_client = fakes["slack"]
        test_client.app.state.s3_store = fakes["s3"]
        test_client.app.state.postgres_store = fakes["postgres"]
        test_client.app.state.databricks_client = FakeDatabricksClient()
        yield test_client


class FakeDatabricksClient:
    def __init__(self):
        self.configured = True

    def get_failure_context(self, run_id: str) -> dict:
        return {
            "error_message": "not used in generic investigate tests",
            "run_id": run_id,
        }

    def resolve_job_id(self, run_id: str, job_id=None):
        return job_id
