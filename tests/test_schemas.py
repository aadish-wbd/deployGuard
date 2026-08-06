import pytest
from pydantic import ValidationError

from app.models.schemas import BedrockRcaOutput, InvestigateRequest


def test_bedrock_rca_output_truncates_overlong_suggested_fix():
    rca = BedrockRcaOutput.model_validate(
        {
            "root_cause": "API timeout",
            "confidence": 0.8,
            "evidence": ["log line"],
            "rca_summary": "summary",
            "suggested_fix": "step " + ("x" * 400),
        }
    )
    assert len(rca.suggested_fix) == 300
    assert rca.suggested_fix.endswith("...")


def test_minimal_valid_request():
    req = InvestigateRequest(
        error_message="NullPointerException: PAYMENT_URL is null",
        service="payment-api",
        environment="production",
    )
    assert req.triggered_by == "manual"


def test_error_message_too_long_rejected():
    with pytest.raises(ValidationError):
        InvestigateRequest(
            error_message="x" * 501,
            service="payment-api",
            environment="production",
        )


def test_stack_trace_too_long_rejected():
    with pytest.raises(ValidationError):
        InvestigateRequest(
            error_message="boom",
            stack_trace="x" * 2001,
            service="payment-api",
            environment="production",
        )


def test_log_snippet_too_long_rejected():
    with pytest.raises(ValidationError):
        InvestigateRequest(
            error_message="boom",
            service="payment-api",
            environment="production",
            context={"log_snippet": "x" * 1501},
        )
