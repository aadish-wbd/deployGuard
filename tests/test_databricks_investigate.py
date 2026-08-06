from app.models.schemas import DatabricksRunContextResponse
from app.services.databricks import DatabricksError


class FakeDatabricksClient:
    def __init__(self, failure=None, error=None, job_id="job-99"):
        self._failure = failure or {
            "error_message": "RuntimeError: Failed to fetch placement 95875283",
            "stack_trace": "RuntimeError: Failed to fetch placement 95875283\n  at line 1",
            "log_snippet": "2026-08-06 timeout fetching placement",
            "task_name": "Load Placements",
            "notebook_name": "freewheel_pipeline",
            "notebook_context": (
                "notebook: freewheel_pipeline\n"
                "--- cell 1 (code): Load Placements [FAILED] ---\n"
                " 1| raise RuntimeError('Failed to fetch placement 95875283')"
            ),
        }
        self._error = error
        self._job_id = job_id
        self.calls = []

    @property
    def configured(self) -> bool:
        return True

    def get_failure_context(self, run_id: str) -> dict:
        self.calls.append(("get_failure_context", run_id))
        if self._error:
            raise self._error
        return dict(self._failure, run_id=run_id)

    def resolve_job_id(self, run_id: str, job_id=None) -> str:
        self.calls.append(("resolve_job_id", run_id, job_id))
        return job_id or self._job_id


DATABRICKS_CONTEXT_PAYLOAD = {"run_id": "123456789"}

DATABRICKS_INVESTIGATE_PAYLOAD = {
    "run_id": "123456789",
    "environment": "production",
}


DATABRICKS_WEBHOOK_FAILURE = {
    "event_type": "jobs.on_failure",
    "workspace_id": "12345",
    "run": {"run_id": "123456789"},
    "job": {"job_id": "516892700102118", "name": "freewheel-placement-pipeline"},
}

DATABRICKS_WEBHOOK_SUCCESS = {
    "event_type": "jobs.on_success",
    "workspace_id": "12345",
    "run": {"run_id": "123456789"},
    "job": {"job_id": "516892700102118", "name": "freewheel-placement-pipeline"},
}

DATABRICKS_WEBHOOK_TASK_FAILURE = {
    "event_type": "jobs.on_failure",
    "workspace_id": "12345",
    "task": {"task_key": "Load Placements"},
    "run": {"run_id": "999", "parent_run_id": "123456789"},
    "job": {"job_id": "516892700102118", "name": "freewheel-placement-pipeline"},
}


def test_databricks_webhook_accepts_failure_and_investigates(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    response = client.post("/api/v1/databricks/webhook", json=DATABRICKS_WEBHOOK_FAILURE)
    assert response.status_code == 202

    body = response.json()
    assert body["status"] == "accepted"
    assert body["run_id"] == "123456789"
    assert body["event_type"] == "jobs.on_failure"
    assert len(fake_db.calls) == 2
    assert len(fakes["bedrock"].invocations) == 1


def test_databricks_webhook_ignores_non_failure_events(client, fakes):
    response = client.post("/api/v1/databricks/webhook", json=DATABRICKS_WEBHOOK_SUCCESS)
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert len(fakes["bedrock"].invocations) == 0


def test_databricks_webhook_accepts_numeric_workspace_id(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db
    payload = {
        **DATABRICKS_WEBHOOK_FAILURE,
        "workspace_id": 12345,
    }

    response = client.post("/api/v1/databricks/webhook", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_databricks_webhook_accepts_missing_job_name(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db
    payload = {
        **DATABRICKS_WEBHOOK_FAILURE,
        "job": {"job_id": "516892700102118"},
    }

    response = client.post("/api/v1/databricks/webhook", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_databricks_webhook_uses_task_run_id_for_task_failures(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    response = client.post("/api/v1/databricks/webhook", json=DATABRICKS_WEBHOOK_TASK_FAILURE)
    assert response.status_code == 202
    assert response.json()["run_id"] == "999"
    assert fake_db.calls[0] == ("get_failure_context", "999")


def test_databricks_automated_investigate_happy_path(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    response = client.post("/api/v1/databricks/investigate", json=DATABRICKS_INVESTIGATE_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "completed"
    assert body["root_cause"]
    assert len(fake_db.calls) == 2
    assert len(fakes["bedrock"].invocations) == 1

    session_id, input_text = fakes["bedrock"].invocations[0]
    assert "RuntimeError" in input_text
    assert "run_id: 123456789" in input_text
    assert "task_name: Load Placements" in input_text
    assert "notebook:" in input_text


def test_databricks_automated_investigate_api_failure(client):
    client.app.state.databricks_client = FakeDatabricksClient(
        error=DatabricksError("Databricks API /api/2.1/jobs/runs/export failed")
    )

    response = client.post("/api/v1/databricks/investigate", json=DATABRICKS_INVESTIGATE_PAYLOAD)
    assert response.status_code == 502


def test_databricks_run_context_happy_path(client):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    response = client.post("/api/v1/databricks/runs/context", json=DATABRICKS_CONTEXT_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert body["run_id"] == "123456789"
    assert body["job_id"] == "job-99"
    assert "RuntimeError" in body["error_message"]
    assert body["task_name"] == "Load Placements"
    assert body["notebook_context"]
    assert len(fake_db.calls) == 2


def test_databricks_run_context_api_failure(client):
    client.app.state.databricks_client = FakeDatabricksClient(
        error=DatabricksError("Databricks API /api/2.1/jobs/runs/export failed")
    )

    response = client.post("/api/v1/databricks/runs/context", json=DATABRICKS_CONTEXT_PAYLOAD)
    assert response.status_code == 502


def test_databricks_to_investigate_two_step_flow(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    context_response = client.post("/api/v1/databricks/runs/context", json=DATABRICKS_CONTEXT_PAYLOAD)
    assert context_response.status_code == 200

    context = DatabricksRunContextResponse.model_validate(context_response.json())
    investigate_payload = context.to_investigate_request(
        service="databricks-etl-job",
        environment="production",
        severity="high",
    )

    investigate_response = client.post(
        "/api/v1/investigate",
        json=investigate_payload.model_dump(mode="json"),
    )
    assert investigate_response.status_code == 200

    body = investigate_response.json()
    assert body["status"] == "completed"
    assert body["root_cause"]
    assert len(fakes["bedrock"].invocations) == 1

    session_id, input_text = fakes["bedrock"].invocations[0]
    assert "RuntimeError" in input_text
    assert "run_id: 123456789" in input_text
    assert "task_name: Load Placements" in input_text
    assert "notebook:" in input_text
    assert "Load Placements [FAILED]" in input_text
