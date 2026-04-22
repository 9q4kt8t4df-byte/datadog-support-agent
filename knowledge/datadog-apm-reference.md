# Datadog APM MCP Reference

Quick reference for querying Datadog APM via the MCP server. Use this alongside `known_issues.md` when investigating trace and log data.

---

## MCP Tools Available

All tools are invoked through `DatadogTool` methods, which translate to Datadog MCP server calls.

### query_traces
Search spans across a time window for a specific tenant.

Parameters:
- `tenant_id` (required) — the tenant identifier stored in `@tenant_id` span tag
- `start_utc` / `end_utc` (required) — ISO-8601 with Z or offset, e.g. `2026-04-21T14:00:00Z`
- `service` (optional) — service name, e.g. `sync-worker`
- `error_only` (optional, default false) — when true, adds `@error.stack:*` filter

MCP tool called: `search_datadog_spans`

### get_trace_detail
Fetch all spans for a single trace ID.

Parameters:
- `trace_id` (required) — hex trace ID from a span

MCP tool called: `get_datadog_trace`

### query_logs
Search log events for a tenant with an optional keyword query.

Parameters:
- `tenant_id` (required)
- `query` (required) — keyword or phrase to search in log messages
- `start_utc` / `end_utc` (required)

MCP tool called: `search_datadog_logs`

### get_service_error_rate
Get a per-minute error count time series for a tenant + service combination.

Parameters:
- `tenant_id` (required)
- `service` (required)
- `start_utc` / `end_utc` (required)

MCP tool called: `analyze_datadog_logs`

### find_pattern_across_tenants (CrossTenantTool)
Count how many distinct tenants have seen a given error signature in a service during a window. Returns `pattern_confidence`: `high` (≥4 tenants), `medium` (2–3), `low` (1), or no matches.

Parameters:
- `error_signature` (required) — substring to match in the error message (case-insensitive)
- `service` (required)
- `start_utc` / `end_utc` (required)

MCP tool called: `ddsql_run_query` with a `GROUP BY tenant_id` DDSQL statement

---

## Datadog Span Filter Syntax

Filters use Lucene-style syntax with `@field:value` for span attributes.

| Filter | Meaning |
|--------|---------|
| `@tenant_id:acme` | Spans tagged with tenant_id = acme |
| `service:sync-worker` | Spans from the sync-worker service |
| `@error.stack:*` | Spans with a non-empty error stack (error spans) |
| `@http.status_code:429` | Spans with HTTP 429 status |
| `@error.message:*Throttling*` | Spans whose error message contains "Throttling" |
| `env:production` | Spans in the production environment |

Combine filters with space (implicit AND):
```
@tenant_id:acme service:sync-worker @error.stack:*
```

---

## DDSQL Basics

DDSQL is Datadog's SQL-like query language for spans. Use it when you need aggregation across many tenants (via `find_pattern_across_tenants`) or for custom analytics.

### Cross-tenant error count
```sql
SELECT tags['tenant_id'] AS tenant_id,
       count(*) AS error_count,
       min(start) AS earliest_occurrence
FROM spans
WHERE service = 'sync-worker'
  AND error = 1
  AND LOWER(error_message) LIKE '%throttlingexception%'
GROUP BY tenant_id
ORDER BY earliest_occurrence ASC
```

Key DDSQL notes:
- `tags['key']` accesses custom span tags
- `error = 1` selects error spans
- `LOWER(field) LIKE '%pattern%'` for case-insensitive substring match
- `start` is the span start timestamp (nanoseconds since epoch)
- `FROM spans` queries APM trace data

---

## Common Span Tag Names

These are the standard Datadog APM span attributes most relevant to support investigations:

| Tag | Description |
|-----|-------------|
| `@tenant_id` | Custom tag — the tenant this request belongs to |
| `service` | Service name (e.g. `sync-worker`, `connector-service`) |
| `resource_name` | Operation name (e.g. `POST /api/sync`, `SQSConsumer`) |
| `@error.stack` | Full exception stack trace |
| `@error.message` | Exception message |
| `@error.type` | Exception class (e.g. `ThrottlingException`) |
| `@http.status_code` | HTTP response status code |
| `@http.url` | Request URL |
| `@duration` | Span duration in nanoseconds |
| `env` | Deployment environment (e.g. `production`) |
| `version` | Service version |

---

## Investigation Workflow

1. **Start with `query_traces`** using `error_only=true` to get recent error spans for the tenant.
2. **Pick a representative trace ID** and call `get_trace_detail` to see the full call graph.
3. **Check `@error.type` and `@error.message`** on the root span — these identify the error class.
4. **Search `known_issues.md`** for the error type to find known root causes and runbooks.
5. **If the error looks external** (e.g. throttling from a third-party API), call `get_service_error_rate` to see if the error rate spiked at a specific time.
6. **If the spike is unexplained**, delegate to `smoke-detector` with `find_pattern_across_tenants` to check if other tenants are affected.
7. **If cross-tenant**: emit `<smoke_alert>` with structured JSON. The orchestrator will forward to Teams via Workato.

---

## Time Window Tips

- Always pass UTC timestamps in ISO-8601 format: `2026-04-21T14:00:00Z`
- Typical investigation window: last 2 hours from the case-reported time
- For spike analysis: extend to 24 hours to establish a baseline
- Datadog retains APM data for 15 days by default (vary by plan)
