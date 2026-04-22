import pytest
import respx
import httpx
from tools.datadog_tool import DatadogTool

DD_API = "https://api.datadoghq.com"

SPANS_RESPONSE = '{"data": [{"type": "span", "id": "abc123", "attributes": {"trace_id": "abc123", "service": "sync-worker", "status": "error"}}], "meta": {}}'
EMPTY_RESPONSE = '{"data": [], "meta": {}}'
AGGREGATE_RESPONSE = '{"data": {"buckets": [{"by": {"timestamp": "2026-04-21T14:00"}, "computes": {"c0": 5}}]}}'


@pytest.fixture
def tool():
    return DatadogTool(api_key="test-key", app_key="test-app-key")


@pytest.mark.asyncio
async def test_query_traces_returns_spans(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(200, text=SPANS_RESPONSE)
        )
        result = await tool.query_traces(
            tenant_id="tenant-acme",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
            error_only=True,
        )
    assert "abc123" in result


@pytest.mark.asyncio
async def test_query_traces_sends_correct_filter(tool):
    with respx.mock:
        route = respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(200, text=SPANS_RESPONSE)
        )
        await tool.query_traces(
            tenant_id="tenant-acme",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
            service="sync-worker",
            error_only=True,
        )
    import json
    payload = json.loads(route.calls[0].request.content)
    query = payload["data"]["attributes"]["filter"]["query"]
    assert "@tenant_id:tenant-acme" in query
    assert "service:sync-worker" in query
    assert "@error.stack:*" in query


@pytest.mark.asyncio
async def test_query_traces_sends_auth_headers(tool):
    with respx.mock:
        route = respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(200, text=SPANS_RESPONSE)
        )
        await tool.query_traces(
            tenant_id="t1",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    headers = route.calls[0].request.headers
    assert headers["DD-API-KEY"] == "test-key"
    assert headers["DD-APPLICATION-KEY"] == "test-app-key"


@pytest.mark.asyncio
async def test_get_trace_detail_queries_by_trace_id(tool):
    with respx.mock:
        route = respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(200, text=SPANS_RESPONSE)
        )
        result = await tool.get_trace_detail(trace_id="abc123")
    import json
    payload = json.loads(route.calls[0].request.content)
    query = payload["data"]["attributes"]["filter"]["query"]
    assert "@trace_id:abc123" in query
    assert "abc123" in result


@pytest.mark.asyncio
async def test_query_logs_searches_logs_endpoint(tool):
    logs_response = '{"data": [{"type": "log", "attributes": {"message": "ThrottlingException occurred"}}]}'
    with respx.mock:
        route = respx.post(f"{DD_API}/api/v2/logs/events/search").mock(
            return_value=httpx.Response(200, text=logs_response)
        )
        result = await tool.query_logs(
            tenant_id="tenant-acme",
            query="ThrottlingException",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    import json
    payload = json.loads(route.calls[0].request.content)
    assert "@tenant_id:tenant-acme" in payload["filter"]["query"]
    assert "ThrottlingException" in payload["filter"]["query"]
    assert "ThrottlingException" in result


@pytest.mark.asyncio
async def test_get_service_error_rate_uses_aggregate_endpoint(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/analytics/aggregate").mock(
            return_value=httpx.Response(200, text=AGGREGATE_RESPONSE)
        )
        result = await tool.get_service_error_rate(
            tenant_id="tenant-acme",
            service="sync-worker",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    assert result is not None


@pytest.mark.asyncio
async def test_query_traces_http_error_returns_error_string(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        result = await tool.query_traces(
            tenant_id="t1",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    assert "403" in result
    assert "Datadog API error" in result


@pytest.mark.asyncio
async def test_query_traces_network_error_returns_error_string(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            side_effect=httpx.ConnectError("refused")
        )
        result = await tool.query_traces(
            tenant_id="t1",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    assert "Datadog API unreachable" in result


def test_sanitize_rejects_metacharacters(tool):
    import pytest
    with pytest.raises(ValueError, match="Invalid characters"):
        tool._sanitize('tenant"evil')
    with pytest.raises(ValueError, match="Invalid characters"):
        tool._sanitize("tenant\nevil")


def test_validate_timestamp_rejects_invalid(tool):
    import pytest
    with pytest.raises(ValueError, match="Invalid timestamp"):
        tool._validate_timestamp("not-a-date")
    with pytest.raises(ValueError, match="Invalid timestamp"):
        tool._validate_timestamp("2026-04-21 14:00:00")


def test_validate_timestamp_accepts_valid(tool):
    tool._validate_timestamp("2026-04-21T14:00:00Z")
    tool._validate_timestamp("2026-04-21T14:00:00+00:00")
    tool._validate_timestamp("2026-04-21T14:00:00.123Z")


@pytest.mark.asyncio
async def test_call_dispatch_query_traces(tool):
    with respx.mock:
        respx.post(f"{DD_API}/api/v2/spans/events/search").mock(
            return_value=httpx.Response(200, text=SPANS_RESPONSE)
        )
        result = await tool.call(
            "query_traces",
            {"tenant_id": "t1", "start_utc": "2026-04-21T14:00:00Z", "end_utc": "2026-04-21T15:00:00Z"},
        )
    assert "abc123" in result


@pytest.mark.asyncio
async def test_call_dispatch_unknown_tool(tool):
    result = await tool.call("nonexistent_tool", {})
    assert "Unknown tool" in result


def test_as_tools_returns_four_definitions(tool):
    defs = tool.as_tools()
    names = [d["name"] for d in defs]
    assert "query_traces" in names
    assert "get_trace_detail" in names
    assert "query_logs" in names
    assert "get_service_error_rate" in names


def test_custom_site_sets_base_url():
    t = DatadogTool(api_key="k", app_key="a", site="datadoghq.eu")
    assert t.base_url == "https://api.datadoghq.eu"
