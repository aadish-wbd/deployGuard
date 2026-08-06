from app.core.prompt import build_agent_input
from app.models.schemas import InvestigateContext, InvestigateRequest


def test_build_agent_input_includes_notebook_context():
    request = InvestigateRequest(
        error_message="RuntimeError: boom",
        service="databricks-etl-job",
        environment="production",
        context=InvestigateContext(
            run_id="123",
            notebook_context="--- cell 1 (code): Task [FAILED] ---\n1| raise RuntimeError('boom')",
        ),
    )

    text = build_agent_input(request)
    assert "notebook:" in text
    assert "[FAILED]" in text
    assert "1| raise RuntimeError('boom')" in text
