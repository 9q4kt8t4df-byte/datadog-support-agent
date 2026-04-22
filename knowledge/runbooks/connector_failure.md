# Connector Failure Runbook

## Symptoms
- Error spans in `connector-service` visible in Datadog APM
- `@error.stack` is populated; `@resource_name` is `connector.execute`
- Repeated retry attempts visible across multiple consecutive spans

## Investigation Steps in Datadog

1. Query error spans: `query_traces` with `service:connector-service @tenant_id:<id>` and `error_only=true`.
2. Identify connector type from span attribute `@connector.type`.
3. Check `@http.status_code` to classify:
   - 4xx/5xx from upstream → external issue (third-party or customer config)
   - Exception with no HTTP status → internal connector bug
4. Check error recurrence: intermittent vs. persistent pattern using `get_service_error_rate`.
5. If internal exception, escalate to Development with trace IDs and `@error.stack` samples.

## Datadog Query Examples

Find connector errors for a tenant:
```
service:connector-service @tenant_id:<id> @error.stack:* @resource_name:connector.execute
```

Check if it's isolated:
```
service:connector-service @error.stack:* @resource_name:connector.execute
```
(run via `find_pattern_across_tenants` to see tenant spread)
