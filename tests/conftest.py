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


@pytest.fixture
def fakes():
    return {
        "bedrock": FakeBedrockClient(),
        "jira": FakeJiraClient(),
        "slack": FakeSlackClient(),
        "s3": FakeS3Store(),
    }


@pytest.fixture
def client(fakes):
    with TestClient(app) as test_client:
        test_client.app.state.bedrock_client = fakes["bedrock"]
        test_client.app.state.jira_client = fakes["jira"]
        test_client.app.state.slack_client = fakes["slack"]
        test_client.app.state.s3_store = fakes["s3"]
        yield test_client
