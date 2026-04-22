from __future__ import annotations
import json
import re
from typing import Optional
import httpx

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class DatadogTool:
    """Wraps the Datadog REST API for querying APM spans and logs."""

    def __init__(self, api_key: str, app_key: str, site: str = "datadoghq.com") -> None:
        self.api_key = api_key
        self.app_key = app_key
        self.base_url = f"https://api.{site}"

    def _headers(self) -> dict:
        return {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _sanitize(value: str) -> str:
        """Reject values containing Datadog query metacharacters to prevent injection."""
        for c in ('"', "\\", "\n", "\r", "\x00", "(", ")"):
            if c in value:
                raise ValueError(f"Invalid characters in query parameter: {value!r}")
        return value

    @staticmethod
    def _validate_timestamp(value: str) -> str:
        if not _ISO_UTC_RE.match(value):
            raise ValueError(f"Invalid timestamp format (expected ISO 8601 UTC): {value!r}")
        return value

    async def _post(self, path: str, payload: dict) -> str:
        """POST to a Datadog API endpoint, return response body as string."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                    timeout=30,
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            return f"[Datadog API error — HTTP {e.response.status_code}: {e.response.text[:200]}]"
        except httpx.RequestError as e:
            return f"[Datadog API unreachable — {type(e).__name__}: {e}]"

    async def query_traces(
        self,
        tenant_id: str,
        start_utc: str,
        end_utc: str,
        service: Optional[str] = None,
        error_only: bool = False,
    ) -> str:
        """Return spans for a tenant in a time window via the Datadog spans search API."""
        self._sanitize(tenant_id)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)
        if service:
            self._sanitize(service)

        query_parts = [f"@tenant_id:{tenant_id}"]
        if service:
            query_parts.append(f"service:{service}")
        if error_only:
            query_parts.append("@error.stack:*")

        payload = {
            "data": {
                "attributes": {
                    "filter": {
                        "query": " ".join(query_parts),
                        "from": start_utc,
                        "to": end_utc,
                    },
                    "sort": "-timestamp",
                    "page": {"limit": 100},
                },
                "type": "search_request",
            }
        }
        return await self._post("/api/v2/spans/events/search", payload)

    async def get_trace_detail(self, trace_id: str) -> str:
        """Return the full span tree for a single trace via spans search."""
        self._sanitize(trace_id)
        payload = {
            "data": {
                "attributes": {
                    "filter": {
                        "query": f"@trace_id:{trace_id}",
                    },
                    "sort": "timestamp",
                    "page": {"limit": 1000},
                },
                "type": "search_request",
            }
        }
        return await self._post("/api/v2/spans/events/search", payload)

    async def query_logs(
        self, tenant_id: str, query: str, start_utc: str, end_utc: str
    ) -> str:
        """Search Datadog logs for a tenant matching a keyword or error string."""
        self._sanitize(tenant_id)
        self._sanitize(query)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)

        payload = {
            "filter": {
                "query": f"@tenant_id:{tenant_id} {query}",
                "from": start_utc,
                "to": end_utc,
            },
            "sort": "-timestamp",
            "page": {"limit": 50},
        }
        return await self._post("/api/v2/logs/events/search", payload)

    async def get_service_error_rate(
        self, tenant_id: str, service: str, start_utc: str, end_utc: str
    ) -> str:
        """Error count per minute for a service in a time window via spans analytics."""
        self._sanitize(tenant_id)
        self._sanitize(service)
        self._validate_timestamp(start_utc)
        self._validate_timestamp(end_utc)

        # Two aggregate requests: total spans and error spans, both grouped by minute.
        base_filter = {
            "from": start_utc,
            "to": end_utc,
        }

        async def _aggregate(extra_query: str) -> list:
            payload = {
                "data": {
                    "attributes": {
                        "compute": [{"aggregation": "count", "type": "total"}],
                        "filter": {
                            **base_filter,
                            "query": f"service:{service} @tenant_id:{tenant_id}{extra_query}",
                        },
                        "group_by": [
                            {
                                "facet": "timestamp",
                                "interval": "1m",
                                "limit": 60,
                                "sort": {
                                    "aggregation": "count",
                                    "order": "asc",
                                    "type": "measure",
                                },
                                "total": False,
                            }
                        ],
                    },
                    "type": "aggregate_request",
                }
            }
            raw = await self._post("/api/v2/spans/analytics/aggregate", payload)
            try:
                return json.loads(raw).get("data", {}).get("buckets", [])
            except (json.JSONDecodeError, AttributeError):
                return []

        total_buckets = await _aggregate("")
        error_buckets = await _aggregate(" @error.stack:*")

        error_by_minute = {
            b["by"].get("timestamp", ""): b["computes"].get("c0", 0)
            for b in error_buckets
            if "by" in b
        }

        result = []
        for bucket in total_buckets:
            minute = bucket.get("by", {}).get("timestamp", "")
            result.append({
                "minute": minute,
                "total_spans": bucket.get("computes", {}).get("c0", 0),
                "error_count": error_by_minute.get(minute, 0),
            })

        return json.dumps(result) if result else json.dumps([])

    def as_tools(self) -> list[dict]:
        """Return Anthropic tool definitions for this tool."""
        return [
            {
                "name": "query_traces",
                "description": (
                    "Query Datadog APM spans/traces for a specific tenant and time window. "
                    "Use error_only=true to filter to error spans only. "
                    "Returns up to 100 spans with trace_id, service, error details."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string", "description": "The tenant identifier tag value in Datadog"},
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
                    "Get the complete span tree for a single trace ID from Datadog APM. "
                    "Use this to understand the full call chain for a specific error."
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
                "description": "Search Datadog logs for a tenant matching a keyword or error string.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "query": {"type": "string", "description": "Keyword to search in log messages"},
                        "start_utc": {"type": "string"},
                        "end_utc": {"type": "string"},
                    },
                    "required": ["tenant_id", "query", "start_utc", "end_utc"],
                },
            },
            {
                "name": "get_service_error_rate",
                "description": (
                    "Get error count per minute for a service/tenant pair using Datadog spans analytics. "
                    "Use this for a quick surface scan to confirm there is a spike before deep investigation."
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
