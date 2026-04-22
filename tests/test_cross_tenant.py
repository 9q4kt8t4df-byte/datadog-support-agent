import pytest
import respx
import httpx
from tools.cross_tenant import CrossTenantTool
from tools.datadog_tool import DatadogTool

DD_API = "https://api.datadoghq.com"

MULTI_TENANT_RESPONSE = '{"data": {"buckets": [{"by": {"@tenant_id": "t1"}, "computes": {"c0": 10}}, {"by": {"@tenant_id": "t2"}, "computes": {"c0": 5}}, {"by": {"@tenant_id": "t3"}, "computes": {"c0": 3}}]}}'
EMPTY_BUCKET_RESPONSE = '{"data": {"buckets": []}}'


@pytest.fixture
def tool():
    datadog = DatadogTool(api_key="test-key", app_key="test-app-key")
    return CrossTenantTool(datadog_tool=datadog)


@pytest.mark.asyncio
async def test_find_pattern_returns_affected_tenants(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=MULTI_TENANT_RESPONSE)
        )
        result = await tool.find_pattern_across_tenants(
            error_signature="ThrottlingException",
            service="sync-worker",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    assert "t1" in result
    assert "t2" in result
    assert "t3" in result


@pytest.mark.asyncio
async def test_find_pattern_high_confidence_for_many_tenants(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=MULTI_TENANT_RESPONSE)
        )
        result = await tool.find_pattern_across_tenants(
            error_signature="ThrottlingException",
            service="sync-worker",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    import json
    data = json.loads(result)
    assert data["affected_tenant_count"] == 3
    assert data["pattern_confidence"] == "medium"


@pytest.mark.asyncio
async def test_find_pattern_empty_returns_no_matches(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=EMPTY_BUCKET_RESPONSE)
        )
        result = await tool.find_pattern_across_tenants(
            error_signature="SomeRareError",
            service="auth-service",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T14:00:00Z",
        )
    assert "0" in result or "no match" in result.lower()


@pytest.mark.asyncio
async def test_find_pattern_sends_correct_query(tool):
    with respx.mock:
        route = respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=EMPTY_BUCKET_RESPONSE)
        )
        await tool.find_pattern_across_tenants(
            error_signature="ThrottlingException",
            service="connector-service",
            start_utc="2026-04-21T13:00:00Z",
            end_utc="2026-04-21T14:00:00Z",
        )
    import json
    payload = json.loads(route.calls[0].request.content)
    query = payload["data"]["attributes"]["filter"]["query"]
    assert "connector-service" in query
    assert "ThrottlingException" in query
    group_by = payload["data"]["attributes"]["group_by"]
    assert group_by[0]["facet"] == "@tenant_id"


@pytest.mark.asyncio
async def test_call_dispatch(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=EMPTY_BUCKET_RESPONSE)
        )
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
