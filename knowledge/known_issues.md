# Known Issues

## MS Throttling — Connector 429/503

When the Microsoft connector receives 429 (Too Many Requests) or 503 (Service Unavailable) responses,
the sync-worker service will emit error spans with `@error.message` containing "ThrottlingException"
or "ServiceUnavailableException". Check `@http.status_code` in Datadog APM span attributes.

This is an external issue, not a platform bug. Use `find_pattern_across_tenants` to check whether
multiple tenants are affected simultaneously — MS throttling often applies at subscription or
IP level, meaning many tenants can be impacted at once.

## Race Condition — Duplicate State Write

Concurrent span execution in the state-manager service can cause duplicate key errors on the
`tenant_state` table. Look for overlapping span timestamps on spans with `@resource_name:state.write`.
The error signature in Datadog will show `@error.type:DuplicateKeyException`.

## Auth Token Expiry

If spans show 401 responses from the identity service, the customer's connector auth token may
have expired. Check spans tagged `@operation_name:auth.refresh` for failure count.
In Datadog, filter with `@http.status_code:401 service:identity-service`.
