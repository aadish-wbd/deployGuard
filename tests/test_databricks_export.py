import json
from pathlib import Path

import pytest

from app.services.databricks_export import (
    extract_failure_context,
    extract_notebook_model,
    format_notebook_for_agent,
    to_ipynb,
)


EXPORT_PATH = Path(__file__).resolve().parents[1] / "team" / "databricks_export.json"


@pytest.fixture
def export_data():
    if not EXPORT_PATH.exists():
        pytest.skip("team/databricks_export.json not present")
    return json.loads(EXPORT_PATH.read_text())


def test_extract_failure_context_from_sample_export(export_data):
    context = extract_failure_context(export_data)

    assert "RuntimeError" in context["error_message"]
    assert context["stack_trace"]
    assert context["task_name"] == "Load Placements"
    assert context["log_snippet"]
    assert context["notebook_context"]
    assert "[FAILED]" in context["notebook_context"]
    assert "Load Placements" in context["notebook_context"]
    assert "| " in context["notebook_context"]  # line-numbered code


def test_to_ipynb_preserves_cell_outputs(export_data):
    html = export_data["views"][0]["content"]
    model = extract_notebook_model(html)
    ipynb = to_ipynb(model)

    code_cells = [cell for cell in ipynb["cells"] if cell["cell_type"] == "code"]
    assert len(code_cells) == 11
    assert any(cell.get("outputs") for cell in code_cells)
