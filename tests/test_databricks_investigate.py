from app.services.databricks import DatabricksError


class FakeDatabricksClient:
    def __init__(self, failure=None, error=None, job_id="job-99"):
        self._failure = failure or {
            "error_message": "RuntimeError: Failed to fetch placement 95875283",
            "stack_trace": "RuntimeError: Failed to fetch placement 95875283\n  at line 1",
            "log_snippet": "2026-08-06 timeout fetching placement",
            "task_name": "Load Placements",
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


DATABRICKS_PAYLOAD = {
    "run_id": "123456789",
    "service": "databricks-etl-job",
    "environment": "production",
}


def test_databricks_investigate_happy_path(client, fakes):
    fake_db = FakeDatabricksClient()
    client.app.state.databricks_client = fake_db

    response = client.post("/api/v1/databricks/investigate", json=DATABRICKS_PAYLOAD)
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
    assert "Load Placements [FAILED]" in input_text


def test_databricks_investigate_api_failure(client):
    client.app.state.databricks_client = FakeDatabricksClient(
        error=DatabricksError("Databricks API /api/2.1/jobs/runs/export failed")
    )

    response = client.post("/api/v1/databricks/investigate", json=DATABRICKS_PAYLOAD)
    assert response.status_code == 502
