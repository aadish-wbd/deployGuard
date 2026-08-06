from app.config import Settings
from app.models.schemas import BedrockRcaOutput
from app.services.jira import _build_description, plain_text_to_adf, resolve_jira_rest_base


def test_build_description_returns_adf_doc():
    rca = BedrockRcaOutput(
        root_cause="PAYMENT_URL is null",
        confidence=0.88,
        evidence=["log line 1", "log line 2"],
        rca_summary="Missing env var in production.",
        suggested_fix="Restore PAYMENT_URL in config.",
    )

    doc = _build_description(rca)

    assert doc["type"] == "doc"
    assert doc["version"] == 1
    assert any(node["type"] == "bulletList" for node in doc["content"])
    assert any(
        item["content"][0]["content"][0]["text"] == "log line 1"
        for item in next(n for n in doc["content"] if n["type"] == "bulletList")["content"]
    )


def test_resolve_jira_rest_base_uses_cloud_id_for_scoped_tokens():
    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_cloud_id="abc-123",
        jira_api_token="ATCTT-scoped-token",
    )
    assert resolve_jira_rest_base(settings) == "https://api.atlassian.com/ex/jira/abc-123"


def test_resolve_jira_rest_base_uses_site_for_classic_tokens():
    settings = Settings.model_validate(
        {
            "jira_base_url": "https://example.atlassian.net/",
            "jira_api_token": "ATATT3x-classic-token",
            "jira_cloud_id": "",
        }
    )
    assert resolve_jira_rest_base(settings) == "https://example.atlassian.net"


def test_plain_text_to_adf_parses_bullet_blocks():
    doc = plain_text_to_adf("Summary line\n\n- first\n- second")

    assert doc["type"] == "doc"
    bullet = next(node for node in doc["content"] if node["type"] == "bulletList")
    items = [item["content"][0]["content"][0]["text"] for item in bullet["content"]]
    assert items == ["first", "second"]
