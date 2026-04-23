from __future__ import annotations
import json
from tools.datadog_tool import DatadogTool


class CrossTenantTool:
    """
    Detects platform-wide error patterns by querying across all tenant environments
    in Datadog using the MCP ddsql_run_query tool.

    DDSQL (Datadog SQL) lets us GROUP BY the @tenant_id tag directly, giving an
    accurate per-tenant error count without pagination limits — equivalent to the
    logfire-mcp GROUP BY approach used in the original.
    """

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
        Count how many tenants are affected by an error pattern using DDSQL.
        The query groups error spans by @tenant_id so we get one row per tenant,
        regardless of how many matching spans exist.
        """
        if not error_signature:
            return '{"affected_tenant_count": 0, "affected_tenant_ids": [], "error": "error_signature must not be empty"}'
        DatadogTool._sanitize(error_signature)
        DatadogTool._sanitize_identifier(service)
        DatadogTool._validate_timestamp(start_utc)
        DatadogTool._validate_timestamp(end_utc)

        # DDSQL query over APM spans grouped by tenant tag.
        # The spans table exposes custom tags as @<tag_name>.
        ddsql = (
            f"SELECT tags['tenant_id'] AS tenant_id, "
            f"count(*) AS error_count, "
            f"min(start) AS earliest_occurrence "
            f"FROM spans "
            f"WHERE service = '{service}' "
            f"AND error = 1 "
            f"AND LOWER(error_message) LIKE '%{error_signature.lower()}%' "
            f"AND start >= '{start_utc}' "
            f"AND start <= '{end_utc}' "
            f"GROUP BY tenant_id "
            f"ORDER BY earliest_occurrence ASC"
        )

        raw = await self.datadog_tool._call_mcp("ddsql_run_query", {"query": ddsql})

        # Parse the DDSQL result. The MCP tool returns JSON or a text table.
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list):
                rows = rows.get("data", rows.get("rows", []))
        except (json.JSONDecodeError, AttributeError):
            # If DDSQL returned an error or non-JSON, surface it directly.
            if "error" in raw.lower() or not raw.strip().startswith("["):
                return raw
            rows = []

        if not rows:
            return f"0 tenants affected — no matches found for pattern: {error_signature}"

        tenant_ids = [
            r.get("tenant_id") or r.get("0") or "unknown"
            for r in rows
            if isinstance(r, dict)
        ]
        earliest = min(
            (r.get("earliest_occurrence", "") for r in rows if isinstance(r, dict)),
            default=start_utc,
        )

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
                    "Search for an error pattern across ALL tenant environments in Datadog "
                    "using DDSQL (via the Datadog MCP ddsql_run_query tool). "
                    "Groups results by @tenant_id to determine platform-wide vs isolated impact. "
                    "Returns affected tenant count, IDs, earliest occurrence, and confidence level."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "error_signature": {
                            "type": "string",
                            "description": (
                                "Normalised error message fragment to search for. "
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
