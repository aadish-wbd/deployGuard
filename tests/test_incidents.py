VALID_PAYLOAD = {
    "error_message": "NullPointerException: PAYMENT_URL is null",
    "service": "payment-api",
    "environment": "production",
    "context": {"deploy_sha": "abc123", "log_snippet": "PaymentHandler.java:42 PAYMENT_URL null"},
    "triggered_by": "manual",
}


def _create_incident(client):
    response = client.post("/api/v1/investigate", json=VALID_PAYLOAD)
    assert response.status_code == 200
    return response.json()["investigation_id"]


def test_get_incident_includes_workflow_status(client):
    investigation_id = _create_incident(client)

    response = client.get(f"/api/v1/incidents/{investigation_id}")
    assert response.status_code == 200
    assert response.json()["workflow_status"] == "open"


def test_update_workflow_status_open_to_closed(client):
    investigation_id = _create_incident(client)

    response = client.patch(
        f"/api/v1/incidents/{investigation_id}/workflow-status",
        json={"workflow_status": "closed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == "closed"

    get_response = client.get(f"/api/v1/incidents/{investigation_id}")
    assert get_response.json()["workflow_status"] == "closed"


def test_update_workflow_status_not_found(client):
    response = client.patch(
        "/api/v1/incidents/missing-id/workflow-status",
        json={"workflow_status": "closed"},
    )
    assert response.status_code == 404


def test_download_rca_report(client):
    investigation_id = _create_incident(client)

    response = client.get(f"/api/v1/incidents/{investigation_id}/rca")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert f'filename="rca-{investigation_id}.md"' in response.headers["content-disposition"]
    assert investigation_id in response.text
    assert "Root cause" in response.text


def test_download_rca_report_not_found(client):
    response = client.get("/api/v1/incidents/missing-id/rca")
    assert response.status_code == 404


def test_download_rca_report_failed_investigation(client):
    from app.services.bedrock import BedrockInvocationError
    from tests.conftest import FakeBedrockClient

    client.app.state.bedrock_client = FakeBedrockClient(error=BedrockInvocationError("throttled"))
    investigation_id = _create_incident(client)

    response = client.get(f"/api/v1/incidents/{investigation_id}/rca")
    assert response.status_code == 400
    assert "completed" in response.json()["detail"].lower()
