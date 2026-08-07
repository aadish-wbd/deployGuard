"""Find prior investigations / JIRA tickets for the same error fingerprint."""
from __future__ import annotations

from typing import Optional

from app.config import Settings
from app.core.investigation_fingerprint import investigation_fingerprint_label
from app.core.logging_config import get_logger
from app.models.schemas import ExistingInvestigation, InvestigateRequest
from app.services.jira import JiraClient
from app.services.postgres_store import PostgresIncidentStore

logger = get_logger(__name__)

_EXISTING_RCA_SUMMARY = (
    "Root cause analysis already completed for this error. "
    "See JIRA ticket {ticket} for details."
)


def existing_rca_summary(ticket_key: str) -> str:
    return _EXISTING_RCA_SUMMARY.format(ticket=ticket_key)


def find_existing_investigation(
    request: InvestigateRequest,
    settings: Settings,
    *,
    jira_client: JiraClient,
    postgres_store: Optional[PostgresIncidentStore],
) -> Optional[ExistingInvestigation]:
    """Return a prior completed investigation with a JIRA ticket, if one exists."""
    deploy_sha = request.context.deploy_sha if request.context else None

    if postgres_store is not None:
        try:
            prior = postgres_store.find_existing_jira(
                error_message=request.error_message,
                service=request.service,
                deploy_sha=deploy_sha,
            )
            if prior is not None:
                logger.info(
                    "investigation_existing_postgres_hit",
                    extra={"jira_ticket": prior.jira_ticket, "investigation_id": prior.investigation_id},
                )
                return prior
        except Exception:
            logger.exception("investigation_existing_postgres_lookup_failed")

    if settings.enable_jira:
        try:
            prior = jira_client.find_existing_ticket(request)
            if prior is not None:
                logger.info("investigation_existing_jira_hit", extra={"jira_ticket": prior.jira_ticket})
                return prior
        except Exception:
            logger.exception("investigation_existing_jira_lookup_failed")

    return None
