import pytest
from pydantic import ValidationError

from app.models.schemas import InvestigateRequest


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
