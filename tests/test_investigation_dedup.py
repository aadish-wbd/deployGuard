from app.core.investigation_fingerprint import investigation_fingerprint_label
from app.models.schemas import ExistingInvestigation, InvestigateRequest
from app.services.investigation_dedup import existing_rca_summary, find_existing_investigation


def test_investigation_fingerprint_label_is_stable():
    label1 = investigation_fingerprint_label("boom", "payment-api", "production")
    label2 = investigation_fingerprint_label("boom", "payment-api", "production")
    label3 = investigation_fingerprint_label("boom", "auth-api", "production")

    assert label1 == label2
    assert label1.startswith("dgfp")
    assert label1 != label3


def test_investigation_fingerprint_ignores_deploy_sha():
    from app.core.investigation_fingerprint import investigation_fingerprint

    fp1 = investigation_fingerprint(
        "NullPointerException: PAYMENT_URL is null", "payment-api", "production"
    )
    fp2 = investigation_fingerprint(
        "NullPointerException: PAYMENT_URL is null", "payment-api", "production"
    )
    assert fp1 == fp2


def test_investigation_fingerprint_differs_by_environment():
    prod = investigation_fingerprint_label("boom", "payment-api", "production")
    staging = investigation_fingerprint_label("boom", "payment-api", "staging")
    assert prod != staging


def test_existing_rca_summary_mentions_ticket():
    assert "KAN-14" in existing_rca_summary("KAN-14")


def test_find_existing_investigation_prefers_postgres():
    from app.config import Settings

    settings = Settings(enable_jira=True)
    postgres_hit = ExistingInvestigation(
        investigation_id="prior-id",
        jira_ticket="KAN-1",
        jira_url="https://jira.example.com/browse/KAN-1",
        root_cause="Known issue",
    )

    class PostgresStub:
        def find_existing_jira(self, **kwargs):
            return postgres_hit

    class JiraStub:
        def find_existing_ticket(self, request):
            raise AssertionError("JIRA lookup should be skipped when Postgres hits")

    result = find_existing_investigation(
        _sample_request(),
        settings,
        jira_client=JiraStub(),
        postgres_store=PostgresStub(),
    )
    assert result == postgres_hit


def test_find_existing_investigation_falls_back_to_jira():
    from app.config import Settings

    settings = Settings(enable_jira=True)
    jira_hit = ExistingInvestigation(
        jira_ticket="KAN-2",
        jira_url="https://jira.example.com/browse/KAN-2",
    )

    class PostgresStub:
        def find_existing_jira(self, **kwargs):
            return None

    class JiraStub:
        def find_existing_ticket(self, request):
            return jira_hit

    result = find_existing_investigation(
        _sample_request(),
        settings,
        jira_client=JiraStub(),
        postgres_store=PostgresStub(),
    )
    assert result == jira_hit


def _sample_request() -> InvestigateRequest:
    return InvestigateRequest(
        error_message="NullPointerException: PAYMENT_URL is null",
        service="payment-api",
        environment="production",
    )
