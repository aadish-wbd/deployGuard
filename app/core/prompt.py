"""Fixed prompt template assembly (NFR-2).

The system prompt, RCA format, and output schema live in the Bedrock Agent
config itself (configured once in AWS, not sent per request). The Python
service only assembles the dynamic, per-error fields below — no repeated
instructions, no duplicate fields.
"""
from app.models.schemas import InvestigateRequest


def build_agent_input(request: InvestigateRequest) -> str:
    lines = [
        f"error_message: {request.error_message}",
        f"service: {request.service}",
        f"environment: {request.environment}",
    ]

    if request.stack_trace:
        lines.append(f"stack_trace: {request.stack_trace}")

    ctx = request.context
    if ctx:
        if ctx.deploy_sha:
            lines.append(f"deploy_sha: {ctx.deploy_sha}")
        if ctx.log_snippet:
            lines.append(f"log_snippet: {ctx.log_snippet}")
        if ctx.metrics:
            metrics_str = ",".join(f"{k}:{v}" for k, v in ctx.metrics.items())
            lines.append(f"metrics: {metrics_str}")
        if ctx.job_id:
            lines.append(f"job_id: {ctx.job_id}")
        if ctx.run_id:
            lines.append(f"run_id: {ctx.run_id}")
        if ctx.task_name:
            lines.append(f"task_name: {ctx.task_name}")
        if ctx.severity:
            lines.append(f"severity: {ctx.severity}")
        if ctx.notebook_context:
            lines.append("notebook:")
            lines.append(ctx.notebook_context)
        if ctx.cloudwatch_alarm:
            alarm = ctx.cloudwatch_alarm
            if alarm.alarm_name:
                lines.append(f"cloudwatch_alarm: {alarm.alarm_name}")
            if alarm.metric_name:
                stat = alarm.statistic or "Sum"
                threshold = alarm.threshold if alarm.threshold is not None else "unknown"
                lines.append(f"cloudwatch_metric: {alarm.metric_name} {stat} threshold={threshold}")
            if alarm.reason:
                lines.append(f"cloudwatch_reason: {alarm.reason}")

    return "\n".join(lines)
