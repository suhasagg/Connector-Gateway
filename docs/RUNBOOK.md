# Operations Runbook

## Gateway readiness failing
1. Check Redis connectivity.
2. Inspect gateway logs.
3. Validate DNS/network policy.
4. Confirm Redis authentication/TLS configuration.
5. Restore dependency or temporarily remove affected cell from traffic.

## Upstream error spike
1. Group metrics by connector/provider.
2. Check provider status and quota.
3. Open circuit for failing provider if necessary.
4. Disable only affected tool versions, not the whole gateway.
5. Preserve audit events.

## Suspected credential leak
1. Revoke/rotate the credential immediately.
2. Disable affected tools.
3. identify requests through audit/traces.
4. Check logs for accidental secret persistence.
5. Reissue narrowly scoped credentials.
6. Complete incident review.

## CLI sandbox incident
1. Stop scheduling new jobs to affected pool.
2. Destroy suspect sandbox instances.
3. Rotate credentials exposed to the pool.
4. preserve forensic metadata.
5. patch image/policy before restoring traffic.
