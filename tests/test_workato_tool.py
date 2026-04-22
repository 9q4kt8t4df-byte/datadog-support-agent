from __future__ import annotations
import pytest
import respx
import httpx
from unittest.mock import patch
from tools.workato_tool import WorkatoTool


def make_tool(
    sf_url: str = "",
    tfs_url: str = "",
    api_key: str = "",
    teams_url: str = "",
    sf_update_url: str = "",
) -> WorkatoTool:
    with patch.multiple(
        "config",
        WORKATO_WEBHOOK_SF_READ=sf_url,
        WORKATO_WEBHOOK_TFS_WRITE=tfs_url,
        WORKATO_API_KEY=api_key,
        WORKATO_WEBHOOK_TEAMS_NOTIFY=teams_url,
        WORKATO_WEBHOOK_SF_UPDATE=sf_update_url,
    ):
        return WorkatoTool()


SF_URL = "https://workato.example.com/sf-read"
TFS_URL = "https://workato.example.com/tfs-write"
API_KEY = "test-key"
TEAMS_URL = "https://workato.example.com/teams-notify"
SF_UPDATE_URL = "https://workato.example.com/sf-update"

TFS_KWARGS = dict(
    title="Sync failure on tenant-X",
    root_cause="MS throttling — 429 from external connector",
    affected_tenants=["tenant-X"],
    evidence_links=["https://app.datadoghq.com/apm/trace/abc123"],
    priority="P2",
    linked_sf_case_id="SF-12345",
)

TEAMS_KWARGS = dict(
    case_id="SF-12345",
    root_cause="MS throttling — sync-worker connector",
    affected_tenant_count=14,
    affected_tenant_ids=["tenant-a", "tenant-b"],
    earliest_occurrence_utc="2026-04-22T09:14:00Z",
    pattern_confidence="high",
    conversation_url="http://localhost:8000/api/conversations/abc/messages",
)


@pytest.mark.asyncio
async def test_read_sf_case_returns_body_when_configured():
    tool = make_tool(sf_url=SF_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(SF_URL).mock(return_value=httpx.Response(200, text='{"subject":"Login failure"}'))
        result = await tool.read_salesforce_case("SF-12345")
    assert "Login failure" in result


@pytest.mark.asyncio
async def test_read_sf_case_sends_api_key_header():
    tool = make_tool(sf_url=SF_URL, api_key=API_KEY)
    with respx.mock:
        route = respx.post(SF_URL).mock(return_value=httpx.Response(200, text="ok"))
        await tool.read_salesforce_case("SF-99")
    assert route.calls[0].request.headers["x-api-key"] == API_KEY


@pytest.mark.asyncio
async def test_read_sf_case_stub_when_not_configured():
    tool = make_tool()
    result = await tool.read_salesforce_case("SF-12345")
    assert "not configured" in result
    assert "SF-12345" in result


@pytest.mark.asyncio
async def test_read_sf_case_http_error_returns_status_code():
    tool = make_tool(sf_url=SF_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(SF_URL).mock(return_value=httpx.Response(404))
        result = await tool.read_salesforce_case("SF-12345")
    assert "404" in result


@pytest.mark.asyncio
async def test_read_sf_case_network_error_returns_message():
    tool = make_tool(sf_url=SF_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(SF_URL).mock(side_effect=httpx.ConnectError("timeout"))
        result = await tool.read_salesforce_case("SF-12345")
    assert "Workato unreachable" in result


@pytest.mark.asyncio
async def test_create_tfs_ticket_returns_body_when_configured():
    tool = make_tool(tfs_url=TFS_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(TFS_URL).mock(return_value=httpx.Response(200, text='{"id":"TFS-99"}'))
        result = await tool.create_tfs_ticket(**TFS_KWARGS)
    assert "TFS-99" in result


@pytest.mark.asyncio
async def test_create_tfs_ticket_sends_structured_payload():
    tool = make_tool(tfs_url=TFS_URL, api_key=API_KEY)
    with respx.mock:
        route = respx.post(TFS_URL).mock(return_value=httpx.Response(200, text="ok"))
        await tool.create_tfs_ticket(**TFS_KWARGS)
    import json
    payload = json.loads(route.calls[0].request.content)
    assert payload["title"] == TFS_KWARGS["title"]
    assert payload["priority"] == "P2"
    assert payload["linked_sf_case_id"] == "SF-12345"
    assert "body" in payload


@pytest.mark.asyncio
async def test_create_tfs_ticket_stub_when_not_configured():
    tool = make_tool()
    result = await tool.create_tfs_ticket(**TFS_KWARGS)
    assert "not configured" in result
    assert "SF-12345" in result
    assert "P2" in result
    assert "MS throttling" in result


@pytest.mark.asyncio
async def test_create_tfs_ticket_http_error():
    tool = make_tool(tfs_url=TFS_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(TFS_URL).mock(return_value=httpx.Response(500))
        result = await tool.create_tfs_ticket(**TFS_KWARGS)
    assert "500" in result


@pytest.mark.asyncio
async def test_send_teams_alert_posts_to_webhook():
    tool = make_tool(teams_url=TEAMS_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(TEAMS_URL).mock(return_value=httpx.Response(200, text='{"ok":true}'))
        result = await tool.send_teams_alert(**TEAMS_KWARGS)
    assert "ok" in result


@pytest.mark.asyncio
async def test_send_teams_alert_payload_contains_all_fields():
    tool = make_tool(teams_url=TEAMS_URL, api_key=API_KEY)
    with respx.mock:
        route = respx.post(TEAMS_URL).mock(return_value=httpx.Response(200, text="ok"))
        await tool.send_teams_alert(**TEAMS_KWARGS)
    import json
    payload = json.loads(route.calls[0].request.content)
    assert payload["case_id"] == "SF-12345"
    assert payload["affected_tenant_count"] == 14
    assert payload["pattern_confidence"] == "high"
    assert "conversation_url" in payload


@pytest.mark.asyncio
async def test_send_teams_alert_stub_when_not_configured():
    tool = make_tool()
    result = await tool.send_teams_alert(**TEAMS_KWARGS)
    assert "not configured" in result
    assert "SF-12345" in result
    assert "14" in result


@pytest.mark.asyncio
async def test_update_sf_priority_posts_to_webhook():
    tool = make_tool(sf_update_url=SF_UPDATE_URL, api_key=API_KEY)
    with respx.mock:
        respx.post(SF_UPDATE_URL).mock(return_value=httpx.Response(200, text='{"updated":true}'))
        result = await tool.update_salesforce_case_priority("SF-12345", "P1")
    assert "updated" in result


@pytest.mark.asyncio
async def test_update_sf_priority_stub_when_not_configured():
    tool = make_tool()
    result = await tool.update_salesforce_case_priority("SF-12345", "P1")
    assert "not configured" in result
    assert "SF-12345" in result
    assert "P1" in result


def test_build_ticket_body_contains_all_sections():
    body = WorkatoTool._build_ticket_body(
        root_cause="MS throttling on sync-worker",
        affected_tenants=["tenant-A", "tenant-B"],
        evidence_links=["https://app.datadoghq.com/apm/trace/abc"],
        priority="P1",
        linked_sf_case_id="SF-555",
    )
    assert "## Root Cause" in body
    assert "MS throttling on sync-worker" in body
    assert "## Affected Tenants" in body
    assert "- tenant-A" in body
    assert "- tenant-B" in body
    assert "## Evidence" in body
    assert "## Priority" in body
    assert "P1" in body
    assert "## Linked Salesforce Case" in body
    assert "SF-555" in body


def test_build_ticket_body_empty_lists_show_none():
    body = WorkatoTool._build_ticket_body(
        root_cause="Unknown",
        affected_tenants=[],
        evidence_links=[],
        priority="P3",
        linked_sf_case_id="SF-0",
    )
    assert "- (none)" in body


def test_as_tools_has_required_definitions():
    tool = make_tool()
    names = [d["name"] for d in tool.as_tools()]
    assert "read_salesforce_case" in names
    assert "create_tfs_ticket" in names
    assert "update_salesforce_case_priority" in names
