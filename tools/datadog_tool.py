from __future__ import annotations
import os
import re

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
# Identifiers: tenant IDs and service names — alphanumeric, hyphens, underscores, dots only.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class DatadogTool:
    """
    Wraps the Datadog MCP server for querying APM spans, logs, and metrics.

    Connects via Streamable HTTP transport (primary) using DD-API-KEY /
    DD-APPLICATION-KEY headers, matching the Datadog MCP docs' header-auth
    configuration. Falls back to the local datadog_mcp_cli binary via stdio
    transport when mcp_url is empty (useful for developer workstations that
    have run `datadog_mcp_cli login`).

    Datadog MCP tools used:
        query_traces          → search_datadog_spans
        get_trace_detail      → get_datadog_trace
        query_logs            → search_datadog_logs
        get_service_error_rate → analyze_datadog_logs (SQL aggregation)
    """

    TOOLSETS = "core,apm,ddsql"

    def __init__(
        self,
        api_key: str,
        app_key: str,
        mcp_url: str,
        binary_path: str = "datadog_mcp_cli",
    ) -> None:
        self.api_key = api_key
        self.app_key = app_key
        self.mcp_url = mcp_url.rstrip("/") if mcp_url else ""
        self.binary_path = binary_path

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        """Whitelist-validate identifiers (tenant IDs, service names, trace IDs).

        Only alphanumeric characters, hyphens, underscores, and dots are allowed.
        This prevents Datadog filter syntax injection (e.g. '@service:admin') and
        DDSQL injection via embedded quotes or operators.
        """
        if not value or not _IDENTIFIER_RE.match(value):
            raise ValueError(
                f"Invalid identifier — only alphanumeric, hyphens, underscores, "
                f"and dots are allowed: {value!r}"
            )
        return value

    @staticmethod
    def _sanitize(value: str) -> str:
        """Blacklist-validate free-text query strings (log queries, error signatures).

        Rejects characters that could inject Datadog query syntax or DDSQL operators.
        Use _sanitize_identifier for structured identifiers instead.
        """
        for c in ('"', "'", "\\", "\n", "\r", "\x00", ";", "--", "%"):
            if c in value:
                raise ValueError(f"Invalid characters in query parameter: {value!r}")
        return value

    @staticmethod
    def _validate_timestamp(value: str) -> str:
        if not _ISO_UTC_RE.match(value):
            raise ValueError(f"Invalid timestamp format (expected ISO 8601 UTC): {value!r}")
        return value

    async def _call_mcp(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch a call to the Datadog MCP server (HTTP or stdio transport)."""
        if self.mcp_url:
            return await self._call_mcp_http(tool_name, tool_input)
        return await self._call_mcp_stdio(tool_name, tool_input)

    async def _call_mcp_http(self, tool_name: str, tool_input: dict) -> str:
        """
        Open a fresh Streamable HTTP connection to the Datadog MCP server,
        authenticated via DD-API-KEY / DD-APPLICATION-KEY headers, call a tool,
        and return the text result.
        """
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError:
            return (
                "[Error: mcp library with Streamable HTTP support not installed. "
                "Run: pip install 'mcp>=1.9.0']"
            )

        url = f"{self.mcp_url}?toolsets={self.TOOLSETS}"
        headers = {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
        }
        try:
            async with streamablehttp_client(url=url, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, tool_input)
                    if result.content:
                        return result.content[0].text
                    return "[]"
        except Exception as e:
            return f"[Datadog MCP error — {type(e).__name__}]"

    async def _call_mcp_stdio(self, tool_name: str, tool_input: dict) -> str:
        """
        Open a fresh stdio connection to the local datadog_mcp_cli binary
        (OAuth-authenticated via `datadog_mcp_cli login`), call a tool,
        and return the text result.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            return "[Error: mcp library not installed. Run: pip install 'mcp>=1.9.0']"

        server_params = StdioServerParameters(
            command=self.binary_path,
            args=["--toolsets", self.TOOLSETS],
            env=os.environ.copy(),
        )
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, tool_input)
                    if result.content:
                        return result.content[0].text
                    return "[]"
        except FileNotFoundError:
            return (
                "[Error: datadog_mcp_cli binary not found. "
                "Install via: curl -sSL https://coterm.datadoghq.com/mcp-cli/install.sh | bash "
                "then run: datadog_mcp_cli login]"
            )
        except Exception as e:
            return f"[Datadog MCP (stdio) error — {type(e).__name__}]"

    async def query_traces(
        self,
        tenant_id: str,
        start_utc: str,
        end_utc: str,
        service: Optional[str] = None,
        error_only: bool = False,
    ) -> str:
        """Search Datadog APM spans for a tenant using the MCP search_datadog_spans tool."""
        self._sanitize_identifier(tenant_id)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)
        if service:
            self._sanitize_identifier(service)

        parts = [f"@tenant_id:{tenant_id}"]
        if service:
            parts.append(f"service:{service}")
        if error_only:
            parts.append("@error.stack:*")

        return await self._call_mcp("search_datadog_spans", {
            "query": " ".join(parts),
            "from": start_utc,
            "to": end_utc,
            "limit": 100,
        })

    async def get_trace_detail(self, trace_id: str) -> str:
        """Fetch the complete span tree for a trace using the MCP get_datadog_trace tool."""
        self._sanitize_identifier(trace_id)
        return await self._call_mcp("get_datadog_trace", {"trace_id": trace_id})

    async def query_logs(
        self, tenant_id: str, query: str, start_utc: str, end_utc: str
    ) -> str:
        """Search Datadog logs for a tenant using the MCP search_datadog_logs tool."""
        self._sanitize_identifier(tenant_id)
        self._sanitize(query)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)

        return await self._call_mcp("search_datadog_logs", {
            "query": f"@tenant_id:{tenant_id} {query}",
            "from": start_utc,
            "to": end_utc,
        })

    async def get_service_error_rate(
        self, tenant_id: str, service: str, start_utc: str, end_utc: str
    ) -> str:
        """
        Aggregate error counts per minute using the MCP analyze_datadog_logs tool.
        This uses the SQL aggregation capability to group error log events by minute.
        """
        self._sanitize_identifier(tenant_id)
        self._sanitize_identifier(service)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)

        sql = (
            f"SELECT date_trunc('minute', timestamp) AS minute, "
            f"count(*) AS error_count "
            f"FROM logs "
            f"WHERE service = '{service}' "
            f"AND @tenant_id = '{tenant_id}' "
            f"AND status = 'error' "
            f"GROUP BY minute "
            f"ORDER BY minute ASC"
        )
        return await self._call_mcp("analyze_datadog_logs", {
            "query": sql,
            "from": start_utc,
            "to": end_utc,
        })

    def as_tools(self) -> list[dict]:
        """Return Anthropic tool definitions exposed to Claude."""
        return [
            {
                "name": "query_traces",
                "description": (
                    "Search Datadog APM spans/traces for a specific tenant and time window "
                    "via the Datadog MCP server. Use error_only=true to filter to error spans. "
                    "Returns up to 100 spans with trace_id, service name, and error details."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string", "description": "The @tenant_id tag value in Datadog"},
                        "start_utc": {"type": "string", "description": "Start of time window in ISO 8601 UTC"},
                        "end_utc": {"type": "string", "description": "End of time window in ISO 8601 UTC"},
                        "service": {"type": "string", "description": "Filter to a specific service name (optional)"},
                        "error_only": {"type": "boolean", "description": "If true, return only error/exception spans"},
                    },
                    "required": ["tenant_id", "start_utc", "end_utc"],
                },
            },
            {
                "name": "get_trace_detail",
                "description": (
                    "Fetch the complete span tree for a single Datadog trace ID via the MCP server. "
                    "Use this to understand the full call chain, timing, and errors for a specific request."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "trace_id": {"type": "string", "description": "The Datadog trace ID to inspect"}
                    },
                    "required": ["trace_id"],
                },
            },
            {
                "name": "query_logs",
                "description": (
                    "Search Datadog logs for a tenant matching a keyword or error string "
                    "via the MCP server's search_datadog_logs tool."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "query": {"type": "string", "description": "Keyword or error string to search in log messages"},
                        "start_utc": {"type": "string"},
                        "end_utc": {"type": "string"},
                    },
                    "required": ["tenant_id", "query", "start_utc", "end_utc"],
                },
            },
            {
                "name": "get_service_error_rate",
                "description": (
                    "Get error log count per minute for a service/tenant pair using the MCP "
                    "analyze_datadog_logs tool (SQL aggregation). Use this for a quick surface "
                    "scan to confirm an error spike before deep investigation."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "service": {"type": "string"},
                        "start_utc": {"type": "string"},
                        "end_utc": {"type": "string"},
                    },
                    "required": ["tenant_id", "service", "start_utc", "end_utc"],
                },
            },
        ]

    async def call(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch a tool call by name."""
        if tool_name == "query_traces":
            return await self.query_traces(**tool_input)
        if tool_name == "get_trace_detail":
            return await self.get_trace_detail(**tool_input)
        if tool_name == "query_logs":
            return await self.query_logs(**tool_input)
        if tool_name == "get_service_error_rate":
            return await self.get_service_error_rate(**tool_input)
        return f"Unknown tool: {tool_name}"
