# Threat Model

## Protected assets
Credentials, tenant data, provider data, infrastructure, audit integrity and approval authority.

## Primary threats
1. Prompt injection causing unintended tool calls.
2. SSRF through configurable HTTP endpoints.
3. Command injection through CLI tools.
4. Cross-tenant access.
5. Credential leakage through logs/output.
6. Approval replay/substitution.
7. Retry-induced duplicate writes.
8. Malicious/compromised MCP server.
9. Tool registry supply-chain compromise.
10. Denial of service through expensive tools.

## Required production mitigations
Use workload identity, narrow schemas, endpoint allowlists, egress proxy, sandboxing, tenant-scoped keys, KMS/Vault, signed approval objects, durable idempotency, signed/versioned registry manifests, quotas, bulkheads and immutable audit events.

## Trust rule
No content retrieved through a connector is authorization. Authorization comes only from trusted identity/policy/approval systems.
