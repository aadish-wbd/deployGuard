"""CloudWatch alarm webhook payload validation and prompt assembly."""

from app.core.prompt import build_agent_input
from app.models.schemas import CloudWatchAlarmContext, InvestigateContext, InvestigateRequest


def test_cloudwatch_alarm_payload_validates():
    req = InvestigateRequest.model_validate(
        {
            "error_message": "CloudWatchAlarm: plans-demo-api-http503 abc Http503Count Sum breached threshold 0",
            "service": "plans-demo-api",
            "environment": "aws-demo",
            "triggered_by": "cloudwatch_alarm",
            "context": {
                "deploy_sha": "a1b2c3d",
                "severity": "high",
                "metrics": {
                    "alarm": "plans-demo-api-http503-abc",
                    "metric": "Http503Count",
                    "statistic": "Sum",
                    "threshold": "0",
                },
                "cloudwatch_alarm": {
                    "alarm_name": "plans-demo-api-http503-abc",
                    "state": "ALARM",
                    "reason": "Threshold Crossed: 1 datapoint was greater than 0",
                    "metric_name": "Http503Count",
                    "namespace": "PlansDemoAPI",
                    "statistic": "Sum",
                    "threshold": 0,
                    "period": 300,
                },
            },
        }
    )
    assert req.triggered_by == "cloudwatch_alarm"
    assert req.context is not None
    assert req.context.cloudwatch_alarm is not None
    assert req.context.cloudwatch_alarm.metric_name == "Http503Count"


def test_build_agent_input_includes_cloudwatch_alarm():
    req = InvestigateRequest(
        error_message="CloudWatchAlarm: latency breach",
        service="plans-demo-api",
        environment="aws-demo",
        triggered_by="cloudwatch_alarm",
        context=InvestigateContext(
            deploy_sha="abc1234",
            severity="high",
            metrics={"metric": "RequestDurationMs", "statistic": "p99", "threshold": "2000"},
            cloudwatch_alarm=CloudWatchAlarmContext(
                alarm_name="plans-demo-api-latency-p99",
                metric_name="RequestDurationMs",
                statistic="p99",
                threshold=2000,
                reason="Threshold Crossed: p99 was 3200",
            ),
        ),
    )
    prompt = build_agent_input(req)
    assert "cloudwatch_alarm: plans-demo-api-latency-p99" in prompt
    assert "RequestDurationMs p99 threshold=2000" in prompt
    assert "metrics: metric:RequestDurationMs" in prompt
