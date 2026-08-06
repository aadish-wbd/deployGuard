#!/usr/bin/env python3
"""Provision the DeployGuard AgentCore Harness.

Creates an AgentCore Harness with inline function tools for JIRA, Slack,
and GitHub. The harness handles orchestration — the model decides when to
call each tool, and our service executes them client-side.

Usage:
    python scripts/create_bedrock_agent.py

Required environment variables:
    BEDROCK_AGENTCORE_ROLE_ARN  - IAM execution role ARN for the harness

Optional environment variables:
    AWS_REGION           - AWS region (default: us-east-1)
    HARNESS_NAME         - Harness name (default: DeployGuard)
    BEDROCK_MODEL_ID     - Model ID (default: us.anthropic.claude-sonnet-4-20250514-v1:0)
"""
from __future__ import annotations

import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
HARNESS_NAME = os.environ.get("HARNESS_NAME", "DeployGuard")
ROLE_ARN = os.environ.get("BEDROCK_AGENTCORE_ROLE_ARN", "")
MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
)

# ---------------------------------------------------------------------------
# System prompt for the harness
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are DeployGuard, an expert Site Reliability Engineer that investigates \
production incidents. You have tools to create JIRA tickets, send Slack alerts, \
and look up code from GitHub.

When given an error payload, follow this process:
1. Analyze the error message, stack trace, and any provided context.
2. If a GitHub repo/service is identified, use the github_search tool to find relevant code.
3. Correlate the error with code changes, metric anomalies, and log patterns.
4. Identify the most likely root cause with supporting evidence.
5. Create a JIRA ticket with the RCA using the jira_create_ticket tool.
6. Send a Slack alert with the summary using the slack_send_alert tool.

After completing your investigation, respond with ONLY a JSON object:
{
  "root_cause": "<concise root cause, max 200 chars>",
  "confidence": <float 0.0-1.0>,
  "evidence": ["<evidence item 1>", ...max 5 items],
  "rca_summary": "<detailed RCA summary, max 500 chars>",
  "suggested_fix": "<actionable fix suggestion, max 300 chars>"
}

Rules:
- Be precise and evidence-based.
- Use tools when they add value — don't skip creating JIRA/Slack alerts.
- confidence: 0.9+ = strong evidence, 0.5-0.8 = likely, <0.5 = speculative.
- The final response must be ONLY the JSON object above.
"""

# ---------------------------------------------------------------------------
# Tool definitions (inline functions — executed client-side)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "inline_function",
        "name": "jira_create_ticket",
        "config": {
            "inlineFunction": {
                "description": (
                    "Create a JIRA ticket for an incident. Returns the ticket key and URL."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Ticket summary (service + error type)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Full RCA description for the ticket body",
                        },
                        "priority": {
                            "type": "string",
                            "description": "Priority: Critical, High, Medium, Low",
                            "enum": ["Critical", "High", "Medium", "Low"],
                        },
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Labels to add to the ticket",
                        },
                    },
                    "required": ["summary", "description"],
                },
            }
        },
    },
    {
        "type": "inline_function",
        "name": "slack_send_alert",
        "config": {
            "inlineFunction": {
                "description": (
                    "Send a Slack alert to the incidents channel with the RCA summary."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The alert message to send to Slack",
                        },
                        "jira_ticket": {
                            "type": "string",
                            "description": "JIRA ticket key (e.g., OPS-123) to link",
                        },
                        "severity": {
                            "type": "string",
                            "description": "Severity level for @mention routing",
                            "enum": ["critical", "high", "medium", "low"],
                        },
                    },
                    "required": ["message"],
                },
            }
        },
    },
    {
        "type": "inline_function",
        "name": "github_search",
        "config": {
            "inlineFunction": {
                "description": (
                    "Search GitHub repository code for relevant files, functions, "
                    "or recent commits related to the error."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (function name, file path, error text)",
                        },
                        "repo": {
                            "type": "string",
                            "description": "Repository in owner/repo format",
                        },
                    },
                    "required": ["query"],
                },
            }
        },
    },
]


def check_credentials() -> str:
    """Verify AWS credentials and return account ID."""
    print("\n→ Checking AWS credentials...")
    try:
        sts = boto3.client("sts", region_name=AWS_REGION)
        identity = sts.get_caller_identity()
        print(f"  ✓ Authenticated as: {identity['Arn']}")
        return identity["Account"]
    except (NoCredentialsError, ClientError) as exc:
        print(f"  ✗ {exc}")
        sys.exit(1)


def create_harness(client) -> str:
    """Create the AgentCore Harness and return its ARN."""
    print(f"\n→ Creating AgentCore Harness '{HARNESS_NAME}'...")

    params = {
        "harnessName": HARNESS_NAME,
        "executionRoleArn": ROLE_ARN,
        "systemPrompt": [{"text": SYSTEM_PROMPT}],
        "tools": TOOLS,
    }

    try:
        resp = client.create_harness(**params)
        harness_id = resp.get("harnessId", "")
        harness_arn = resp.get("harnessArn", "")
        print(f"  ✓ Harness created: {harness_id}")
        print(f"    ARN: {harness_arn}")
        return harness_arn
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if "ConflictException" in error_code or "already exists" in str(exc):
            print(f"  ⚠ Harness '{HARNESS_NAME}' already exists. Fetching existing...")
            return get_existing_harness(client)
        print(f"  ✗ Failed: {exc}")
        sys.exit(1)


def get_existing_harness(client) -> str:
    """List harnesses and find the existing one."""
    try:
        resp = client.list_harnesses()
        for h in resp.get("harnesses", []):
            if HARNESS_NAME in h.get("harnessName", ""):
                arn = h.get("harnessArn", "")
                print(f"  ✓ Found existing harness: {arn}")
                return arn
    except ClientError as exc:
        print(f"  ✗ Could not list harnesses: {exc}")
    return ""


def wait_for_ready(client, harness_id: str, timeout: int = 120) -> None:
    """Poll until harness is READY."""
    print("  → Waiting for harness to be READY...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = client.get_harness(harnessId=harness_id)
            status = resp.get("status", "")
            if status == "READY":
                print("    ✓ Harness is READY.")
                return
            if status in ("FAILED", "DELETE_IN_PROGRESS"):
                print(f"    ✗ Harness status: {status}")
                sys.exit(1)
            print(f"    Status: {status} — waiting...")
        except ClientError:
            pass
        time.sleep(5)
    print(f"    ⚠ Timed out after {timeout}s")


def main() -> None:
    print("DeployGuard — AgentCore Harness Setup")
    print("=" * 40)

    if not ROLE_ARN:
        print("\n✗ BEDROCK_AGENTCORE_ROLE_ARN is required.")
        print("  This IAM role needs:")
        print("    - bedrock:InvokeModel on your chosen model")
        print("    - bedrock-agentcore:InvokeHarness")
        print("\n  Example:")
        print("    export BEDROCK_AGENTCORE_ROLE_ARN=arn:aws:iam::123456789012:role/AgentCoreRole")
        sys.exit(1)

    account_id = check_credentials()

    # Create harness
    control_client = boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)
    harness_arn = create_harness(control_client)

    if harness_arn:
        # Extract harness ID from ARN for polling
        harness_id = harness_arn.split("/")[-1] if "/" in harness_arn else ""
        if harness_id:
            wait_for_ready(control_client, harness_id)

    # Print configuration
    print("\n" + "=" * 60)
    print("✓ DeployGuard AgentCore Harness provisioned!")
    print("=" * 60)
    print("\nAdd to your .env:\n")
    print(f"  AWS_REGION={AWS_REGION}")
    print(f"  BEDROCK_MODEL_ID={MODEL_ID}")
    print(f"  AGENTCORE_HARNESS_ARN={harness_arn}")
    print()
    print("Or export:")
    print(f"  export AWS_REGION={AWS_REGION}")
    print(f"  export BEDROCK_MODEL_ID={MODEL_ID}")
    print(f"  export AGENTCORE_HARNESS_ARN={harness_arn}")
    print()

    # Print IAM policy
    print("Required IAM policy for the execution role:")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockModel",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": f"arn:aws:bedrock:{AWS_REGION}::foundation-model/*",
            },
            {
                "Sid": "AgentCoreHarness",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeHarness",
                    "bedrock-agentcore:InvokeAgentRuntimeCommand",
                ],
                "Resource": "*",
            },
        ],
    }
    print(json.dumps(policy, indent=2))
    print()


if __name__ == "__main__":
    main()
