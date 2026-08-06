"""FastAPI dependency providers — reads shared clients off app.state.

Clients are constructed once at startup (see app.main) and reused across
requests; boto3/httpx clients are safe to share across a single-process
FastAPI app.
"""
from fastapi import Request

from app.config import Settings, get_settings
from app.core.cache import TTLCache
from app.services.bedrock import BedrockAgentClient
from app.services.databricks import DatabricksClient
from app.services.jira import JiraClient
from app.services.s3_store import S3IncidentStore
from app.services.slack import SlackClient


def get_settings_dep() -> Settings:
    return get_settings()


def get_bedrock_client(request: Request) -> BedrockAgentClient:
    return request.app.state.bedrock_client


def get_jira_client(request: Request) -> JiraClient:
    return request.app.state.jira_client


def get_slack_client(request: Request) -> SlackClient:
    return request.app.state.slack_client


def get_s3_store(request: Request) -> S3IncidentStore:
    return request.app.state.s3_store


def get_dedup_cache(request: Request) -> TTLCache:
    return request.app.state.dedup_cache


def get_databricks_client(request: Request) -> DatabricksClient:
    return request.app.state.databricks_client
