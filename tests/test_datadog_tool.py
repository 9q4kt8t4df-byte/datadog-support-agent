import pytest
from unittest.mock import AsyncMock, patch
from tools.datadog_tool import DatadogTool

SPANS_RESPONSE = '[{"trace_id": "abc123", "service": "sync-worker", "status": "error"}]'
EMPTY_RESPONSE = '[]'
ERROR_RATE_RESPONSE = '[{"minute": "2026-04-21T14:00", "error_count": 5}]'


@pytest.fixture
def tool():
    return DatadogTool(
        api_key="test-key",
        app_key="test-app-key",
        mcp_url="https://mcp.datadoghq.com",
    )


# ── query_traces ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_traces_calls_search_datadog_spans(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SPANS_RESPONSE
        result = await tool.query_traces(
            tenant_id="tenant-acme",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
            error_only=True,
        )
    mock.assert_called_once_with(
        "search_datadog_spans",
        {
            "query": "@tenant_id:tenant-acme @error.stack:*",
            "from": "2026-04-21T14:00:00Z",
            "to": "2026-04-21T15:00:00Z",
            "limit": 100,
        },
    )
    assert "abc123" in result


@pytest.mark.asyncio
async def test_query_traces_includes_service_in_query(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SPANS_RESPONSE
        await tool.query_traces(
            tenant_id="tenant-acme",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
            service="sync-worker",
        )
    call_args = mock.call_args
    query = call_args[0][1]["query"]
    assert "service:sync-worker" in query
    assert "@tenant_id:tenant-acme" in query
    assert "@error.stack:*" not in query


@pytest.mark.asyncio
async def test_query_traces_no_error_filter_by_default(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = EMPTY_RESPONSE
        await tool.query_traces(
            tenant_id="t1",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    query = mock.call_args[0][1]["query"]
    assert "@error.stack:*" not in query


# ── get_trace_detail ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_trace_detail_calls_get_datadog_trace(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SPANS_RESPONSE
        result = await tool.get_trace_detail(trace_id="abc123")
    mock.assert_called_once_with("get_datadog_trace", {"trace_id": "abc123"})
    assert "abc123" in result


# ── query_logs ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_logs_calls_search_datadog_logs(tool):
    logs_response = '[{"message": "ThrottlingException occurred", "service": "sync-worker"}]'
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = logs_response
        result = await tool.query_logs(
            tenant_id="tenant-acme",
            query="ThrottlingException",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    mock.assert_called_once_with(
        "search_datadog_logs",
        {
            "query": "@tenant_id:tenant-acme ThrottlingException",
            "from": "2026-04-21T14:00:00Z",
            "to": "2026-04-21T15:00:00Z",
        },
    )
    assert "ThrottlingException" in result


# ── get_service_error_rate ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_service_error_rate_calls_analyze_datadog_logs(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = ERROR_RATE_RESPONSE
        result = await tool.get_service_error_rate(
            tenant_id="tenant-acme",
            service="sync-worker",
            start_utc="2026-04-21T14:00:00Z",
            end_utc="2026-04-21T15:00:00Z",
        )
    assert mock.call_args[0][0] == "analyze_datadog_logs"
    payload = mock.call_args[0][1]
    assert "sync-worker" in payload["query"]
    assert "tenant-acme" in payload["query"]
    assert payload["from"] == "2026-04-21T14:00:00Z"
    assert payload["to"] == "2026-04-21T15:00:00Z"
    assert "error_count" in result or "5" in result


# ── transport selection ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_mcp_uses_http_when_mcp_url_set(tool):
    with patch.object(tool, "_call_mcp_http", new_callable=AsyncMock) as mock_http, \
         patch.object(tool, "_call_mcp_stdio", new_callable=AsyncMock) as mock_stdio:
        mock_http.return_value = SPANS_RESPONSE
        await tool._call_mcp("search_datadog_spans", {})
    mock_http.assert_called_once()
    mock_stdio.assert_not_called()


@pytest.mark.asyncio
async def test_call_mcp_uses_stdio_when_no_mcp_url():
    tool_no_url = DatadogTool(api_key="k", app_key="a", mcp_url="")
    with patch.object(tool_no_url, "_call_mcp_http", new_callable=AsyncMock) as mock_http, \
         patch.object(tool_no_url, "_call_mcp_stdio", new_callable=AsyncMock) as mock_stdio:
        mock_stdio.return_value = SPANS_RESPONSE
        await tool_no_url._call_mcp("search_datadog_spans", {})
    mock_stdio.assert_called_once()
    mock_http.assert_not_called()


# ── sanitization & validation ────────────────────────────────────────────────

def test_sanitize_rejects_sql_injection_chars(tool):
    with pytest.raises(ValueError, match="Invalid characters"):
        tool._sanitize("tenant'; DROP TABLE spans;--")


def test_sanitize_rejects_newlines(tool):
    with pytest.raises(ValueError, match="Invalid characters"):
        tool._sanitize("tenant\nevil")


def test_sanitize_accepts_normal_values(tool):
    assert tool._sanitize("tenant-acme") == "tenant-acme"
    assert tool._sanitize("sync-worker") == "sync-worker"


def test_validate_timestamp_rejects_invalid(tool):
    with pytest.raises(ValueError, match="Invalid timestamp"):
        tool._validate_timestamp("not-a-date")
    with pytest.raises(ValueError, match="Invalid timestamp"):
        tool._validate_timestamp("2026-04-21 14:00:00")


def test_validate_timestamp_accepts_valid_formats(tool):
    tool._validate_timestamp("2026-04-21T14:00:00Z")
    tool._validate_timestamp("2026-04-21T14:00:00+00:00")
    tool._validate_timestamp("2026-04-21T14:00:00.123Z")


# ── call dispatch ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_dispatch_query_traces(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SPANS_RESPONSE
        result = await tool.call(
            "query_traces",
            {"tenant_id": "t1", "start_utc": "2026-04-21T14:00:00Z", "end_utc": "2026-04-21T15:00:00Z"},
        )
    assert "abc123" in result


@pytest.mark.asyncio
async def test_call_dispatch_get_trace_detail(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = SPANS_RESPONSE
        await tool.call("get_trace_detail", {"trace_id": "abc123"})
    assert mock.call_args[0][0] == "get_datadog_trace"


@pytest.mark.asyncio
async def test_call_dispatch_query_logs(tool):
    with patch.object(tool, "_call_mcp", new_callable=AsyncMock) as mock:
        mock.return_value = "[]"
        await tool.call("query_logs", {
            "tenant_id": "t1", "query": "err",
            "start_utc": "2026-04-21T14:00:00Z", "end_utc": "2026-04-21T15:00:00Z",
        })
    assert mock.call_args[0][0] == "search_datadog_logs"


@pytest.mark.asyncio
async def test_call_dispatch_unknown_tool(tool):
    result = await tool.call("nonexistent_tool", {})
    assert "Unknown tool" in result


# ── as_tools definitions ─────────────────────────────────────────────────────

def test_as_tools_returns_four_definitions(tool):
    names = [d["name"] for d in tool.as_tools()]
    assert "query_traces" in names
    assert "get_trace_detail" in names
    assert "query_logs" in names
    assert "get_service_error_rate" in names


def test_mcp_url_stripped_of_trailing_slash():
    t = DatadogTool(api_key="k", app_key="a", mcp_url="https://mcp.datadoghq.com/")
    assert not t.mcp_url.endswith("/")


def test_empty_mcp_url_stays_empty():
    t = DatadogTool(api_key="k", app_key="a", mcp_url="")
    assert t.mcp_url == ""
