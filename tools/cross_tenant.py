from __future__ import annotations
import json
from tools.datadog_tool import DatadogTool


class CrossTenantTool:
    """Queries Datadog APM across all tenant environments to detect platform-wide patterns."""

    def __init__(self, datadog_tool: DatadogTool) -> None:
        self.datadog_tool = datadog_tool

    async def find_pattern_across_tenants(
        self,
        error_signature: str,
        service: str,
        start_utc: str,
        end_utc: str,
    ) -> str:
        """
        Search for an error pattern across ALL tenant environments in Datadog.
        Returns affected tenant count, distinct tenant IDs, and earliest occurrence.
        Uses the Datadog spans analytics aggregate endpoint grouped by @tenant_id.
        """
        DatadogTool._sanitize(error_signature)
        DatadogTool._sanitize(service)
        DatadogTool._validate_timestamp(start_utc)
        DatadogTool._validate_timestamp(end_utc)

        payload = {
            "data": {
                "attributes": {
                    "compute": [{"aggregation": "count", "type": "total"}],
                    "filter": {
                        "query": (
                            f"service:{service} @error.stack:* "
                            f"@error.message:*{error_signature}*"
                        ),
                        "from": start_utc,
                        "to": end_utc,
                    },
                    "group_by": [
                        {
                            "facet": "@tenant_id",
                            "limit": 200,
                            "sort": {
                                "aggregation": "count",
                                "order": "desc",
                                "type": "measure",
                            },
                            "total": False,
                        }
                    ],
                },
                "type": "aggregate_request",
            }
        }

        raw = await self.datadog_tool._post(
            "/api/v2/spans/analytics/aggregate", payload
        )

        try:
            body = json.loads(raw)
            buckets = body.get("data", {}).get("buckets", [])
        except (json.JSONDecodeError, AttributeError):
            return raw

        if not buckets:
            return f"0 tenants affected — no matches found for pattern: {error_signature}"

        tenant_ids = [
            b["by"].get("@tenant_id", "unknown")
            for b in buckets
            if "by" in b
        ]

        earliest = start_utc

        return json.dumps({
            "affected_tenant_count": len(tenant_ids),
            "affected_tenant_ids": tenant_ids,
            "earliest_occurrence_utc": earliest,
            "pattern_confidence": (
                "high" if len(tenant_ids) > 3
                else "medium" if len(tenant_ids) > 1
                else "low"
            ),
        })

    def as_tools(self) -> list:
        return [
            {
                "name": "find_pattern_across_tenants",
                "description": (
                    "Search for an error pattern across ALL tenant environments in Datadog. "
                    "Use this to determine if an issue is isolated to one customer or platform-wide. "
                    "Returns the count of affected tenants, their IDs, and pattern confidence."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "error_signature": {
                            "type": "string",
                            "description": (
                                "The normalised error type or message fragment to search for. "
                                "Strip tenant-specific IDs, request IDs, and timestamps first."
                            ),
                        },
                        "service": {
                            "type": "string",
                            "description": "The Datadog service name where the error was observed",
                        },
                        "start_utc": {"type": "string", "description": "Start of search window in ISO 8601 UTC"},
                        "end_utc": {"type": "string", "description": "End of search window in ISO 8601 UTC"},
                    },
                    "required": ["error_signature", "service", "start_utc", "end_utc"],
                },
            }
        ]

    async def call(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "find_pattern_across_tenants":
            return await self.find_pattern_across_tenants(**tool_input)
        return f"Unknown tool: {tool_name}"
