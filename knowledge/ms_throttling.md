# MS Throttling Investigation Runbook

## Symptoms
- HTTP 429 or 503 in Datadog APM spans from `connector-service`
- `@error.message` contains: ThrottlingException, RetryAfter, ServiceUnavailableException
- `@http.status_code` is 429 or 503
- Spike in error rate starting at a consistent time visible in `get_service_error_rate`

## Investigation Steps in Datadog

1. Call `get_service_error_rate` for the affected tenant/service to confirm the spike window.
2. Call `query_traces` with `error_only=true` for `service:connector-service @tenant_id:<id>`.
3. Inspect a representative trace with `get_trace_detail` — confirm `@connector.provider` is "microsoft".
4. Note the `timestamp` of the first throttling span.
5. Call `find_pattern_across_tenants` with error_signature="ThrottlingException" — MS throttling
   often affects multiple tenants simultaneously at the subscription or IP level.
6. Use `query_logs` to find retry patterns and backoff behaviour.

## Datadog Query Examples

Spans filter for throttling errors:
```
service:connector-service @error.message:*ThrottlingException* @http.status_code:429
```

Cross-tenant check:
```
service:connector-service @error.message:*ThrottlingException* @error.stack:*
```

## Escalation Priority
- Single tenant: P3 — advise customer to check their MS subscription limits
- Multiple tenants (>3): P1 — platform-wide MS subscription or IP-level throttling
