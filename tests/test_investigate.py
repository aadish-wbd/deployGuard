from app.core.rate_limit import DailyCap
from app.services.bedrock import BedrockInvocationError
from tests.conftest import FakeBedrockClient, FakeJiraClient, FakeSlackClient

VALID_PAYLOAD = {
    "error_message": "NullPointerException: PAYMENT_URL is null",
    "service": "payment-api",
    "environment": "production",
    "context": {"deploy_sha": "abc123", "log_snippet": "PaymentHandler.java:42 PAYMENT_URL null"},
    "triggered_by": "manual",
}


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["bedrock_reachable"] is True


def test_investigate_happy_path(client, fakes):
    response = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "completed"
    assert body["root_cause"]
    assert body["actions"]["jira_created"] is True
    assert body["actions"]["slack_sent"] is True
    assert body["cached"] is False
    assert len(fakes["s3"].saved) == 1


def test_investigate_bedrock_failure_returns_failed_status(client):
    client.app.state.bedrock_client = FakeBedrockClient(error=BedrockInvocationError("throttled"))
    jira = FakeJiraClient()
    slack = FakeSlackClient()
    client.app.state.jira_client = jira
    client.app.state.slack_client = slack

    response = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "failed"
    assert body["error_detail"]
    assert not jira.calls
    assert not slack.calls


def test_investigate_oversized_body_rejected(client):
    payload = dict(VALID_PAYLOAD)
    payload["context"] = dict(payload["context"], metrics={f"k{i}": "v" * 50 for i in range(300)})
    response = client.post("/api/v1/investigate", json=payload)
    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"]


def test_investigate_dedup_cache_hit_skips_second_bedrock_call(client, fakes):
    first = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    second = client.post("/api/v1/investigate", json=VALID_PAYLOAD)

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert len(fakes["bedrock"].invocations) == 1
    assert len(fakes["s3"].saved) == 1


def test_investigate_cache_hit_does_not_consume_daily_cap(client):
    client.app.state.daily_cap = DailyCap(1)

    first = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    assert first.status_code == 200
    assert first.json()["cached"] is False

    cached = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    assert cached.status_code == 200
    assert cached.json()["cached"] is True

    other_payload = dict(VALID_PAYLOAD, error_message="Connection refused on db-primary")
    blocked = client.post("/api/v1/investigate", json=other_payload)
    assert blocked.status_code == 429
