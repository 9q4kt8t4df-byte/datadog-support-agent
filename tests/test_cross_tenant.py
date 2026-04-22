import json
import pytest
from unittest.mock import AsyncMock, patch
from tools.cross_tenant import CrossTenantTool
from tools.datadog_tool import DatadogTool

MULTI_TENANT_DDSQL = json.dumps([
    {"tenant_id": "t1", "error_count": 10, "earliest_occurrence": "2026-04-21T13:00:00Z"},
    {"tenant_id": "t2", "error_count": 5,  "earliest_occurrence": "2026-04-21T13:05:00Z"},
    {"tenant_id": "t3", "error_count": 3,  "earliest_occurrence": "2026-04-21T13:10:00Z"},
])
SINGLE_TENANT_DDSQL = json.dumps([
    {"tenant_id": "t1", "error_count": 20, "earliest_occurrence": "2026-04-21T13:00:00Z"},
])
EMPTY_DDSQL = "[]"


@pytest.fixture
def tool():
    datadog = DatadogTool(
        api_key="test-key",
        app_key="test-app-key",
        mcp_url="https://mcp.datadoghq.com",
    )
    return CrossTenantTool(datadog_tool=datadog)


@pytest.mark.asyncio
async def test_find_pattern_returns_affected_tenants(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = MULTI_TENANT_DDSQL
        result = await tool.find_pattern_across_tenants(
            error_signature="ThrottlingException",
            service="sync-worker",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    data = json.loads(result)
    assert "t1" in data["affected_tenant_ids"]
    assert "t2" in data["affected_tenant_ids"]
    assert "t3" in data["affected_tenant_ids"]


@pytest.mark.asyncio
async def test_find_pattern_calls_ddsql_run_query(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = EMPTY_DDSQL
        await tool.find_pattern_across_tenants(
            error_signature="ThrottlingException",
            service="connector-service",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T14:00:00Z",
        )
    assert mock.call_args[0][0] == "ddsql_run_query"
    query = mock.call_args[0][1]["query"]
    assert "connector-service" in query
    assert "throttlingexception" in query.lower()
    assert "tenant_id" in query.lower()


@pytest.mark.asyncio
async def test_find_pattern_confidence_high_for_4plus_tenants(tool):
    four_tenants = json.dumps([
        {"tenant_id": f"t{i}", "error_count": 1, "earliest_occurrence": "2026-04-21T13:00:00Z"}
        for i in range(1, 5)
    ])
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = four_tenants
        result = await tool.find_pattern_across_tenants(
            error_signature="err", service="svc",
            start_utc="2026-04-21T13:00:00Z", end_utc="2026-04-21T14:00:00Z",
        )
    data = json.loads(result)
    assert data["pattern_confidence"] == "high"
    assert data["affected_tenant_count"] == 4


@pytest.mark.asyncio
async def test_find_pattern_confidence_medium_for_2_to_3_tenants(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = MULTI_TENANT_DDSQL  # 3 tenants
        result = await tool.find_pattern_across_tenants(
            error_signature="err", service="svc",
            start_utc="2026-04-21T13:00:00Z", end_utc="2026-04-21T14:00:00Z",
        )
    assert json.loads(result)["pattern_confidence"] == "medium"


@pytest.mark.asyncio
async def test_find_pattern_confidence_low_for_single_tenant(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SINGLE_TENANT_DDSQL
        result = await tool.find_pattern_across_tenants(
            error_signature="err", service="svc",
            start_utc="2026-04-21T13:00:00Z", end_utc="2026-04-21T14:00:00Z",
        )
    assert json.loads(result)["pattern_confidence"] == "low"


@pytest.mark.asyncio
async def test_find_pattern_empty_returns_no_matches(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = EMPTY_DDSQL
        result = await tool.find_pattern_across_tenants(
            error_signature="SomeRareError",
            service="auth-service",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T14:00:00Z",
        )
    assert "0" in result or "no match" in result.lower()


@pytest.mark.asyncio
async def test_call_dispatch(tool):
    with patch.object(tool.datadog_tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = EMPTY_DDSQL
        result = await tool.call(
            "find_pattern_across_tenants",
            {
                "error_signature": "err",
                "service": "svc",
                "start_utc": "2026-04-21T13:00:00Z",
                "end_utc": "2026-04-21T14:00:00Z",
            },
        )
    assert "0" in result or "no match" in result.lower()


@pytest.mark.asyncio
async def test_call_unknown_tool(tool):
    result = await tool.call("nonexistent_tool", {})
    assert "Unknown tool" in result
