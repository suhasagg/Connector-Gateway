# Connector Gateway

**Production-oriented control plane and execution gateway for MCP, REST, GraphQL, and CLI tools**

Connector Gateway gives AI agents, workflow engines, copilots, and automation systems one governed interface for discovering and invoking heterogeneous tools. Instead of teaching an agent four different transport models, the agent sees a stable tool catalog and invocation API while the gateway owns protocol adaptation, authorization, policy, approval, schema validation, retries, idempotency, observability, and execution boundaries.

## Table of contents

1. Goals
2. Why a connector gateway
3. Architecture
4. Request lifecycle
5. Connector model
6. MCP adapter
7. REST adapter
8. GraphQL adapter
9. CLI adapter
10. Tool registry
11. Tool schemas
12. Policy engine
13. Authentication and authorization
14. Human approval
15. Idempotency
16. Retries and timeouts
17. Circuit breaking and bulkheads
18. Security model
19. Prompt injection and tool-output trust
20. CLI sandboxing
21. SSRF and egress controls
22. Secrets
23. Multi-tenancy
24. Observability
25. SLOs
26. Failure modes
27. Scalability
28. Cell architecture
29. High availability
30. Data architecture
31. Deployment
32. Local run instructions
33. API examples
34. Adding a REST connector
35. Adding a GraphQL connector
36. Adding an MCP connector
37. Adding a CLI connector
38. Testing
39. Kubernetes
40. Applications
41. AI-agent integration
42. LangGraph integration
43. Muse-style integration
44. Governance
45. Production hardening
46. Principal-level design tradeoffs
47. Roadmap
48. Repository map

## 1. Goals

The gateway is designed around six invariants:

- **One agent-facing contract.** Agents should not need transport-specific logic.
- **Policy before execution.** Authorization and risk decisions occur before a connector receives input.
- **Schemas are security boundaries.** Inputs are validated before dispatch.
- **Writes are different from reads.** Risk classification supports stronger controls for mutating operations.
- **Execution is observable.** Every invocation has an identity, result, latency and metrics trail.
- **Protocol adapters are replaceable.** MCP, REST, GraphQL and CLI share a small connector interface.

The project intentionally separates **control plane** concerns—catalog, policy, configuration, credentials—from **data plane** execution. The sample keeps the registry in process for easy execution; a production deployment should persist versioned definitions and distribute immutable snapshots to workers.

## 2. Why a connector gateway?

A serious agent can easily accumulate hundreds or thousands of tools. Direct integrations create N×M coupling between agents and providers. A gateway turns that into N agents → one gateway → M providers.

Without a gateway:

```text
Agent ── REST ── Jira
      ├─ GraphQL ─ GitHub
      ├─ MCP ───── internal MCP server
      └─ subprocess ─ kubectl
```

With the gateway:

```text
                         ┌──────────── Control Plane ────────────┐
                         │ Registry  Policy  Secrets  Approvals  │
                         └────────────────┬──────────────────────┘
                                          │
Agent / LangGraph / Muse ── HTTPS ── Connector Gateway
                                          │
                         ┌────────────────┼────────────────┐
                         ▼                ▼                ▼
                        MCP             REST            GraphQL
                         │                │                │
                         └──────────────┬─┴───────────────┘
                                        ▼
                                      CLI
```

## 3. Architecture

The runtime pipeline is:

```text
Request
  │
  ▼
Identity verification
  │
  ▼
Tenant + scope resolution
  │
  ▼
Tool registry lookup
  │
  ▼
Policy evaluation
  │
  ├── deny ─────────────► audit / response
  │
  ▼
Approval gate (when required)
  │
  ▼
JSON Schema validation
  │
  ▼
Idempotency lookup
  │
  ▼
Connector router
  │
  ├── MCP adapter
  ├── REST adapter
  ├── GraphQL adapter
  └── CLI adapter
  │
  ▼
Timeout / retry / execution
  │
  ▼
Output normalization
  │
  ▼
Metrics + audit
  │
  ▼
Response
```

The `Connector` abstract class is the protocol seam. A new transport implements `invoke(tool, args)` and is registered with the service router.

## 4. Request lifecycle

`POST /v1/invoke` accepts a tool name and JSON arguments. `GatewayService.invoke` creates a request ID, resolves the tool, asks `PolicyEngine` for a decision, validates the request against the tool's JSON Schema, checks idempotency state, routes to the connector and returns a normalized `InvocationResult`.

A production version should also emit a durable audit event using a transactional outbox or an append-only event pipeline. Metrics alone are not an audit trail.

## 5. Connector model

`app/connectors/base.py` defines:

```python
class Connector(ABC):
    @abstractmethod
    async def invoke(self, tool, args):
        ...
```

This small SPI prevents policy and API code from depending on transport details. It also makes connectors independently testable.

### Why not expose protocols directly?

Protocol normalization provides:
- consistent auth and policy;
- one retry vocabulary;
- one telemetry model;
- one approval system;
- stable schemas for agents;
- provider replacement without prompt changes.

## 6. MCP adapter

`McpConnector` translates a gateway invocation into JSON-RPC `tools/call`.

Conceptually:

```text
Gateway Invocation
      │
      ▼
MCP adapter
      │
      ▼
{"jsonrpc":"2.0","method":"tools/call", ...}
      │
      ▼
MCP server
```

For a mature MCP implementation add initialization/capability negotiation, protocol-version handling, tool discovery synchronization, cancellation, streaming, session lifecycle, transport support, and upstream identity propagation. Keep MCP content untrusted: a remote tool can return malicious instructions just as a web page can.

## 7. REST adapter

The REST connector uses `httpx.AsyncClient`, explicit timeout, no redirect following, retry policy, status validation and JSON/text normalization.

Production extensions:
- host allowlists;
- DNS/IP revalidation;
- mTLS;
- OAuth token injection;
- request signing;
- per-provider rate limits;
- pagination adapters;
- typed response schemas;
- retry only safe/idempotent operations.

**Important:** indiscriminate retries on POST can duplicate side effects. The sample demonstrates retry plumbing; production policies should use method/tool semantics and provider idempotency keys.

## 8. GraphQL adapter

The GraphQL connector accepts a query plus variables and rejects GraphQL-level errors.

Production controls should include:
- persisted/allowlisted queries for sensitive environments;
- query depth and complexity limits;
- introspection policy;
- response-size ceilings;
- field-level authorization when needed;
- provider-specific rate-cost accounting.

## 9. CLI adapter

The CLI connector is intentionally restrictive. It:
- requires an executable allowlist;
- uses `asyncio.create_subprocess_exec`;
- never uses `shell=True`;
- supplies a minimal environment;
- enforces a timeout;
- caps returned output.

This is **not sufficient isolation for hostile commands**. Production CLI execution belongs in an ephemeral sandbox: container, microVM, restricted Kubernetes Job, or equivalent execution cell with seccomp/AppArmor, read-only filesystem, resource quotas, network policy, short-lived credentials and no host socket.

Never turn the CLI adapter into:

```python
subprocess.run(user_string, shell=True)
```

That would collapse the security boundary.

## 10. Tool registry

`ToolRegistry` maps stable names to `ToolDefinition`.

A tool definition contains:
- stable name;
- connector kind;
- human description;
- risk classification;
- endpoint or command;
- method;
- JSON input schema;
- enabled state.

Production registry requirements:
- PostgreSQL or configuration repository as source of truth;
- immutable versions;
- review/approval workflow;
- tenant visibility;
- ownership metadata;
- credential reference, never plaintext credential;
- health status;
- deprecation;
- rollout percentage;
- compatibility metadata;
- provenance.

## 11. Tool schemas

Agents are probabilistic; connectors should not be.

JSON Schema validation is performed before execution. A schema is both developer documentation and an execution guardrail. Prefer narrow enums, bounded strings, bounded arrays and `additionalProperties: false` where practical.

Avoid generic tools such as:

```text
execute_any_http_request(url, method, headers, body)
```

for ordinary agents. Such a tool effectively bypasses the registry and egress policy.

Prefer capability-specific tools:

```text
jira.issue.read
jira.issue.create
github.pr.comment
deployment.status
```

## 12. Policy engine

The included `PolicyEngine` demonstrates scope and risk decisions.

Risk classes:
- `read`
- `write`
- `destructive`

A production policy decision should consider:

```text
principal
tenant
agent identity
tool
tool version
risk
resource
environment
arguments
time
network zone
approval state
delegation chain
```

ABAC is usually more expressive than pure RBAC for agent systems. OPA/Cedar or an internal policy service can replace the local implementation without changing connector code.

## 13. Authentication and authorization

The sample supports bearer JWT and development identity fallback.

Production:
1. authenticate the caller at the edge;
2. validate issuer, audience, expiry, key ID and signature;
3. resolve tenant and workload identity;
4. evaluate scopes/policy;
5. issue narrowly scoped downstream credentials.

Prefer workload identity and short-lived credentials over long-lived API keys.

Never trust tenant IDs supplied only in request bodies.

## 14. Human approval

Destructive tools return `approval required` without an approval token.

The sample token check is intentionally only the integration seam. A real approval object should cryptographically bind:

```text
principal
tenant
tool
tool_version
canonical_arguments_hash
risk
expiry
approver
request_id
```

Otherwise an approval for one action can be replayed for another.

A good flow:

```text
Agent requests action
       │
       ▼
Policy says APPROVAL_REQUIRED
       │
       ▼
Create pending action
       │
       ▼
Human sees exact diff/action
       │
       ▼
Approval service signs authorization
       │
       ▼
Gateway verifies binding + expiry
       │
       ▼
Execute once
```

## 15. Idempotency

The implementation supports an `idempotency_key`, scoped by tenant and tool, cached in Redis.

For production write operations:
- require idempotency keys;
- hash canonical request arguments;
- reject reuse with different payload;
- store state as `IN_PROGRESS/SUCCEEDED/FAILED`;
- use durable storage for critical operations;
- propagate provider idempotency keys;
- define retention by business semantics.

Exactly-once execution across networks is generally not something a gateway can promise. Design for **at-least-once delivery plus idempotent effects**.

## 16. Retries and timeouts

Every external call needs a deadline. Retries need budgets and semantics.

Retry:
- transient connect failures;
- selected 429/5xx responses;
- safe reads;
- idempotent writes with provider support.

Do not blindly retry:
- destructive operations;
- non-idempotent POSTs;
- authentication failures;
- schema failures.

Use exponential backoff plus jitter in production.

## 17. Circuit breaking and bulkheads

The compact runnable project includes retry/timeout primitives but intentionally leaves provider-aware circuit breaking as a hardening extension.

At scale use independent concurrency pools:

```text
GitHub bulkhead      max 200
Jira bulkhead        max 100
CLI sandbox pool     max 20
MCP provider A       max 50
```

This prevents one slow provider from exhausting gateway workers.

A circuit breaker should track failures per upstream and transition CLOSED → OPEN → HALF_OPEN.

## 18. Security model

Assume all of these can be hostile:
- agent arguments;
- connector output;
- web content;
- MCP server content;
- GraphQL responses;
- CLI output;
- tool metadata from untrusted registries.

Trust boundaries should be explicit.

Core defenses:
- identity at ingress;
- least privilege;
- schema validation;
- egress allowlisting;
- secret indirection;
- approval for high-risk effects;
- sandboxed local execution;
- bounded output;
- audit logging;
- no arbitrary shell;
- no arbitrary unrestricted URL fetch.

## 19. Prompt injection and tool-output trust

A connector gateway does not solve prompt injection merely by validating JSON.

Tool output must be represented to the agent as **untrusted data**, not higher-priority instructions. Do not allow text returned by a website or connector to silently authorize another tool invocation.

For high-risk actions, policy should be based on trusted identity and structured intent—not a sentence from retrieved content.

## 20. CLI sandboxing

Recommended production topology:

```text
Gateway
   │
   ▼
Sandbox Scheduler
   │
   ├── microVM A
   ├── microVM B
   └── microVM C
```

Each sandbox should have:
- immutable base image;
- read-only root;
- temporary workspace;
- CPU/memory/pid quotas;
- syscall restrictions;
- explicit egress;
- no cloud metadata endpoint;
- no Docker socket;
- short TTL;
- short-lived secret injection;
- full audit metadata.

## 21. SSRF and egress controls

The sample seed contains public demonstration URLs. Do not allow arbitrary endpoint registration by untrusted callers in production.

Production REST/MCP/GraphQL egress should:
- allowlist schemes and hosts;
- reject loopback/link-local/private ranges unless explicitly approved;
- resolve DNS and validate resulting IPs;
- protect against DNS rebinding;
- block cloud metadata addresses;
- disable uncontrolled redirects;
- route through an egress proxy;
- log destination identity.

## 22. Secrets

Tool definitions should store `credential_ref`, not credentials.

Example:

```text
credential_ref = vault://prod/connectors/github/team-a
```

At execution:
1. authenticate gateway workload;
2. retrieve/issue credential;
3. keep it in memory briefly;
4. inject it into the downstream request;
5. redact it from logs;
6. rotate independently of tool metadata.

## 23. Multi-tenancy

Every stateful key must be tenant-scoped.

The included idempotency key follows:

```text
idem:{tenant}:{tool}:{key}
```

Production registry, audit and approvals should have the same invariant. For strong isolation, larger tenants can be assigned separate execution cells and encryption keys.

## 24. Observability

The project exports Prometheus metrics at `/metrics`.

Included:
- invocation counter by tool/status;
- invocation latency histogram.

Production telemetry should add:
- connector/provider;
- policy outcome;
- retry count;
- timeout count;
- circuit state;
- queue time;
- sandbox startup time;
- upstream latency;
- output bytes;
- approval latency.

Avoid high-cardinality labels such as user ID and request ID in Prometheus. Put those in traces/logs.

Distributed tracing should propagate a trace ID across gateway → connector → upstream where supported.

## 25. SLOs

Illustrative SLOs—not measured claims:

```text
Gateway availability          99.95%
Policy/registry lookup p99    < 50 ms
Gateway-added latency p99     < 100 ms excluding upstream
Read invocation success       > 99.9% excluding provider failures
Audit-event durability        99.999%
```

Separate gateway health from upstream health. Jira being down should not make the gateway's `/health/live` fail.

## 26. Failure modes

### Redis unavailable
Idempotency and readiness are affected. Decide whether reads can fail open; writes generally should fail closed if idempotency is mandatory.

### Upstream timeout
Return a bounded error, record metrics, and retry only if policy permits.

### Policy service unavailable
For consequential operations, fail closed.

### Registry unavailable
Serve a last-known-good signed snapshot for a bounded period if your threat model allows it.

### CLI worker crash
Terminate the sandbox, preserve audit metadata, mark the invocation indeterminate if side effects cannot be proven.

### Client disconnect
Do not assume the upstream operation stopped. Cancellation should be explicit and protocol-aware.

## 27. Scalability

The HTTP gateway can be stateless except for external dependencies, allowing horizontal scaling.

A large deployment might use:

```text
Global traffic manager
        │
   ┌────┴─────┐
   ▼          ▼
Cell A       Cell B
 │            │
 ├ Gateway    ├ Gateway
 ├ Redis      ├ Redis
 ├ Workers    ├ Workers
 └ Egress     └ Egress
```

Partition by tenant hash or residency requirement.

The most important scaling limit is often not gateway CPU—it is provider quotas and long-running tool executions. Introduce asynchronous jobs for operations exceeding ordinary HTTP deadlines.

## 28. Cell architecture

Cells limit blast radius.

A cell owns:
- gateway replicas;
- execution workers;
- cache/idempotency;
- egress controls;
- connector quotas.

Global services should be minimal: identity, configuration distribution and routing.

A bad connector rollout then damages one cell instead of the fleet.

## 29. High availability

Use:
- 3+ gateway replicas;
- multi-AZ orchestration;
- managed HA Redis/Postgres where required;
- PodDisruptionBudgets;
- topology spread;
- graceful termination;
- connection draining;
- immutable configuration versions.

## 30. Data architecture

The sample does not require PostgreSQL to run its in-memory catalog, even though Compose includes Postgres as the natural production metadata store.

Suggested tables:

```text
tools
tool_versions
tenant_tool_bindings
credential_refs
approval_requests
idempotency_records
audit_events
connector_health
```

Use an outbox when a database mutation and an audit/event publication must be coordinated.

## 31. Deployment

### Prerequisites

Fastest path:
- Docker 24+
- Docker Compose v2+

Native path:
- Python 3.11+
- Redis 7+
- optional PostgreSQL 16+

### Clone/unzip

```bash
unzip connector-gateway-production.zip
cd connector-gateway
```

### Configure

```bash
cp .env.example .env
```

For local Docker execution the defaults are sufficient. **Change `JWT_SECRET` before any shared or production deployment.**

## 32. Local run instructions

### Option A — Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Gateway:

```text
http://localhost:8080
```

OpenAPI:

```text
http://localhost:8080/docs
```

Check:

```bash
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready
curl http://localhost:8080/v1/tools
```

Stop:

```bash
docker compose down
```

Delete local volumes too:

```bash
docker compose down -v
```

### Option B — native Python

Start Redis:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

Create environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Override Docker hostnames:

```bash
export REDIS_URL=redis://localhost:6379/0
export DATABASE_URL=postgresql+asyncpg://gateway:gateway@localhost:5432/gateway
export ENV=dev
```

Run:

```bash
uvicorn app.main:app --reload --port 8080
```

## 33. API examples

### Discover tools

```bash
curl -s http://localhost:8080/v1/tools | python -m json.tool
```

### CLI invocation

```bash
curl -s http://localhost:8080/v1/invoke \
  -H 'content-type: application/json' \
  -d '{
    "tool":"cli.git_version",
    "arguments":{},
    "idempotency_key":"demo-1"
  }'
```

### GraphQL invocation

```bash
curl -s http://localhost:8080/v1/invoke \
  -H 'content-type: application/json' \
  -d '{
    "tool":"graphql.query",
    "arguments":{
      "query":"query { country(code: \"IN\") { name capital } }"
    }
  }'
```

### REST invocation

```bash
curl -s http://localhost:8080/v1/invoke \
  -H 'content-type: application/json' \
  -d '{
    "tool":"http.echo",
    "arguments":{"message":"hello from connector gateway"}
  }'
```

### Metrics

```bash
curl http://localhost:8080/metrics
```

## 34. Adding a REST connector

Register a narrowly defined tool rather than an arbitrary HTTP proxy:

```json
{
  "name": "orders.lookup",
  "connector": "rest",
  "description": "Look up an order",
  "risk": "read",
  "endpoint": "https://api.example.com/orders/lookup",
  "method": "POST",
  "input_schema": {
    "type": "object",
    "required": ["order_id"],
    "properties": {
      "order_id": {"type": "string", "maxLength": 64}
    },
    "additionalProperties": false
  },
  "enabled": true
}
```

In production the registry API itself must be admin-only and endpoint domains must pass egress policy.

## 35. Adding a GraphQL connector

Define the provider endpoint and restrict query shapes. For sensitive systems, prefer a tool implementation that generates a known query internally from typed arguments rather than accepting arbitrary GraphQL from the agent.

## 36. Adding an MCP connector

Set `MCP_SERVER_URL`, then invoke `mcp.call` with:

```json
{
  "tool": "mcp.call",
  "arguments": {
    "name": "search",
    "arguments": {"query": "connector gateway"}
  }
}
```

The upstream must expose the expected MCP-compatible JSON-RPC transport. A production adapter should implement the complete lifecycle required by the upstream transport/version.

## 37. Adding a CLI connector

Do not let the agent construct the executable.

Define a fixed command in the registry:

```python
ToolDefinition(
    name="cluster.version",
    connector="cli",
    command=["kubectl","version","--client"],
    ...
)
```

If arguments are needed, build them from validated structured fields with explicit allowlists.

## 38. Testing

Install dev dependencies:

```bash
pip install -e '.[dev]'
```

Run:

```bash
pytest -q
```

Lint:

```bash
ruff check .
```

The included tests verify policy semantics and that all four connector classes are represented in the registry.

Production test suites should add:
- connector contract tests;
- malicious schema inputs;
- SSRF tests;
- JWT negative cases;
- retry/idempotency race tests;
- approval replay tests;
- provider fault injection;
- sandbox escape regression tests;
- load tests;
- chaos tests.

## 39. Kubernetes

A baseline deployment is in `k8s/deployment.yaml`.

Build/push:

```bash
docker build -t YOUR_REGISTRY/connector-gateway:1.0.0 .
docker push YOUR_REGISTRY/connector-gateway:1.0.0
```

Update the image and apply:

```bash
kubectl apply -f k8s/deployment.yaml
```

Before production add:
- Secret/ExternalSecret integration;
- ConfigMap or configuration service;
- NetworkPolicy;
- HPA;
- PDB;
- topology spread;
- ServiceAccount/workload identity;
- ingress/gateway TLS;
- non-root and read-only filesystem;
- seccomp;
- egress proxy.

## 40. Applications

### Enterprise agent platform
Give every internal agent a governed tool plane rather than embedding credentials and SDKs in each agent.

### Developer copilot
Expose repository, CI, issue tracker, documentation and deployment capabilities behind approval-aware tools.

### SRE agent
Read metrics/logs freely while requiring approval for rollback, restart, scaling and configuration changes.

### Customer-support agent
Unify CRM REST, order GraphQL, knowledge MCP and constrained operational commands.

### Data/analytics agent
Expose read-only warehouse/query tools with quotas, schema constraints and audit.

### Muse-style persistent agent
A persistent agent can discover a stable catalog while the gateway owns access to external systems and risky effects.

### Workflow automation
LangGraph, Temporal or an internal workflow engine can call the same gateway used by interactive agents.

## 41. AI-agent integration

The agent should receive a curated subset of tools, not the whole enterprise catalog.

Recommended flow:

```text
User goal
  │
  ▼
Agent planner
  │
  ▼
Tool discovery filtered by tenant + capability
  │
  ▼
Gateway invocation
  │
  ▼
Policy / approval / execution
  │
  ▼
Structured result
  │
  ▼
Agent reasoning
```

The gateway is not the planner. This separation lets agent models change independently from governance.

## 42. LangGraph integration

Treat gateway calls as graph nodes/tools.

Pseudo-flow:

```text
START
  │
  ▼
plan
  │
  ▼
select_tool
  │
  ▼
invoke_gateway
  │
  ├── approval required ─► human node ─┐
  │                                    │
  └────────────────────────────────────┘
  │
  ▼
observe
  │
  ▼
END
```

LangGraph checkpointing persists workflow state; the Connector Gateway governs external capabilities. Neither should impersonate the other.

## 43. Muse-style integration

For a persistent Muse-like agent, use three separate planes:

```text
                 Persistent Agent
                 /      |       \
                /       |        \
        Memory Server  Planner   Connector Gateway
                                      │
                          ┌───────────┼───────────┐
                          MCP        REST      GraphQL/CLI
```

Memory answers *what should I remember?*  
Planner answers *what should I do?*  
Gateway answers *what am I allowed to execute, and how?*

This separation is valuable because memory content must never itself become authorization.

## 44. Governance

Every tool should have:
- owner;
- purpose;
- data classification;
- risk;
- allowed tenants;
- allowed environments;
- credential scope;
- approval rule;
- retention/audit policy;
- SLO;
- version;
- deprecation date where applicable.

Treat tool registration like deploying an API, not like adding a prompt snippet.

## 45. Production hardening

Before calling an organization-specific deployment production-ready, complete at least:

- [ ] external persistent registry;
- [ ] JWKS/OIDC validation;
- [ ] Vault/KMS-backed secret references;
- [ ] cryptographically bound approvals;
- [ ] provider-aware retry policy;
- [ ] durable idempotency for writes;
- [ ] egress proxy and SSRF controls;
- [ ] CLI microVM/container sandbox;
- [ ] circuit breakers and concurrency bulkheads;
- [ ] distributed tracing;
- [ ] durable audit pipeline;
- [ ] tenant quotas;
- [ ] rate limiting;
- [ ] response-size limits;
- [ ] tool/version rollout controls;
- [ ] dependency and image scanning;
- [ ] signed images/SBOM;
- [ ] threat model;
- [ ] load/chaos tests;
- [ ] on-call dashboards/runbooks.

The repository provides concrete seams for each of these rather than pretending a single generic implementation can encode every company's IAM, network and compliance model.

## 46. Principal-level design tradeoffs

### Gateway vs direct SDK
Gateway adds a network hop but centralizes policy and dramatically reduces duplicated security logic.

### Synchronous vs asynchronous
Interactive reads fit synchronous HTTP. Long jobs should return an operation ID and execute asynchronously.

### Centralized vs cell-based
One global gateway is simpler; cells reduce blast radius, improve residency control and scale independently.

### Generic tools vs domain tools
Generic HTTP/SQL/shell tools maximize flexibility but also maximize blast radius. Domain-specific tools are safer and easier for models to use correctly.

### Registry consistency
Strongly consistent registry writes with eventually distributed immutable snapshots are often preferable to making every invocation depend on a global database.

### Credentials
Delegated end-user credentials preserve user authorization semantics. Service credentials simplify operations but can over-privilege agents. Support both intentionally.

### Streaming
Streaming is useful for long tool output but complicates cancellation, audit and retries. Keep side-effect state explicit.

### Exactly-once
Do not promise exactly-once execution over arbitrary external systems. Use idempotency, provider request IDs, reconciliation and compensating actions.

### Control plane / data plane split
The control plane changes comparatively slowly and needs governance. The data plane needs low latency and isolation. Scaling them independently is a major architectural advantage.

## 47. Roadmap

### Phase 1 — supplied implementation
- FastAPI gateway
- MCP/REST/GraphQL/CLI adapters
- registry
- schema validation
- JWT/scopes
- risk policy
- approval seam
- Redis idempotency
- retries/timeouts
- Prometheus
- Docker/Kubernetes
- tests

### Phase 2
- PostgreSQL registry/versioning
- OIDC/JWKS
- Vault
- audit outbox
- rate limiting
- egress policy
- OpenTelemetry

### Phase 3
- sandbox worker service
- approval service/UI
- connector health controller
- circuit breaker/bulkhead framework
- asynchronous operation API

### Phase 4
- multi-region cells
- policy-as-code
- connector marketplace
- signed connector manifests
- automated connector conformance tests
- semantic tool discovery

## 48. Repository map

```text
connector-gateway/
├── app/
│   ├── main.py                 HTTP surface
│   ├── config.py               environment configuration
│   ├── models.py               canonical tool/invocation models
│   ├── security.py             JWT principal and scopes
│   ├── policy.py               risk-aware authorization
│   ├── registry.py             tool catalog
│   ├── service.py              execution orchestration
│   ├── observability.py        Prometheus instrumentation
│   └── connectors/
│       ├── base.py             connector SPI
│       ├── mcp.py              MCP JSON-RPC adapter
│       ├── rest.py             REST adapter
│       ├── graphql.py          GraphQL adapter
│       └── cli.py              constrained subprocess adapter
├── tests/
│   ├── test_policy.py
│   └── test_registry.py
├── k8s/
│   └── deployment.yaml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── .env.example
└── README.md
```

## Final architectural principle

The Connector Gateway should be viewed as a **capability firewall for agents**, not merely an API proxy.

A conventional API gateway asks:

> Which HTTP request may this client send?

An agent connector gateway asks:

> Which real-world capability may this principal delegate to this agent, under which policy, with what arguments, credentials, approvals, isolation, observability and recovery semantics?

That is the key design shift that makes this infrastructure useful for production autonomous systems.
# 49. Executive summary

Connector Gateway is an infrastructure layer for exposing heterogeneous capabilities to autonomous and semi-autonomous software through one governed contract. It is designed for environments in which an LLM or workflow may decide *which* tool to invoke, but infrastructure—not model text—must decide whether the invocation is authorized and how it is safely executed.

The gateway supports four integration families:

| Family | Typical use | Runtime model |
|---|---|---|
| MCP | Agent-native tool servers | JSON-RPC/tool protocol adapter |
| REST | SaaS/internal HTTP APIs | HTTP request/response |
| GraphQL | Graph APIs | Query + variables |
| CLI | Infrastructure/developer tools | Restricted process execution |

The architecture is intentionally transport-neutral above the connector layer.

# 50. Design goals and non-goals

## Goals

1. Stable tool contract for multiple agent frameworks.
2. Central authorization and governance.
3. Strong separation between planning and execution.
4. Explicit handling of side effects.
5. Tenant-aware isolation.
6. Protocol-independent telemetry.
7. Horizontal scalability.
8. Extensible connector SPI.
9. Safe degradation when providers fail.
10. Auditable execution.

## Non-goals

The gateway is not:
- an LLM;
- an agent planner;
- a vector database;
- a durable workflow engine;
- an identity provider;
- a secrets manager;
- a replacement for provider-specific authorization.

It integrates with those systems.

# 51. Code walkthrough

## `app/main.py`

Defines the external HTTP contract. Routes remain intentionally thin. Business logic belongs in `GatewayService`, preventing HTTP concerns from contaminating policy and execution logic.

Endpoints:

```text
GET  /health/live
GET  /health/ready
GET  /v1/tools
PUT  /v1/tools/{name}
POST /v1/invoke
GET  /metrics
```

## `app/models.py`

Defines the canonical language shared by every connector.

`ConnectorKind` prevents free-form protocol names.

`Risk` expresses coarse effect semantics:

```text
read
write
destructive
```

`ToolDefinition` describes a capability. `Invocation` describes a requested execution. `InvocationResult` normalizes transport-specific results.

This normalization is important because an agent should not need one result parser for REST and another for CLI.

## `app/security.py`

Converts an authenticated request into a `Principal`:

```text
Principal
├── subject
├── tenant
└── scopes
```

Downstream code consumes the principal rather than parsing bearer tokens repeatedly.

## `app/policy.py`

Transforms:

```text
Principal + ToolDefinition
```

into:

```text
Decision
├── allowed
├── reason
└── approval_required
```

This is deliberately replaceable by an external policy engine.

## `app/registry.py`

Provides the tool catalog. The built-in entries demonstrate all connector types.

In a production control plane, replace in-memory mutation with versioned durable configuration.

## `app/service.py`

This is the orchestration core:

```text
resolve
→ authorize
→ approval gate
→ validate
→ idempotency lookup
→ dispatch
→ normalize
→ cache result
→ metric
```

Keeping this sequence centralized makes policy bypass harder.

## `app/connectors/base.py`

Defines the connector SPI. Transport implementations do not make authorization decisions. This prevents security semantics from diverging between protocols.

## `app/connectors/rest.py`

Provides asynchronous REST execution with deadline, status checking and response normalization.

## `app/connectors/graphql.py`

Maps structured gateway arguments into GraphQL query/variables and treats GraphQL `errors` as execution failures.

## `app/connectors/mcp.py`

Maps the canonical invocation into an MCP-style JSON-RPC `tools/call`.

## `app/connectors/cli.py`

Executes fixed, allowlisted commands without a shell. This is a constrained local adapter, not a security sandbox.

## `app/observability.py`

Defines protocol-independent metrics. Observability is intentionally outside individual adapters so dashboards can compare all tool types.

# 52. End-to-end invocation example

Suppose an agent invokes:

```json
{
  "tool": "cli.git_version",
  "arguments": {},
  "idempotency_key": "run-123"
}
```

Execution becomes:

```text
HTTP
 │
 ▼
FastAPI
 │
 ▼
JWT → Principal
 │
 ▼
ToolRegistry["cli.git_version"]
 │
 ▼
PolicyEngine
 │
 ▼
JSON Schema
 │
 ▼
Redis idempotency lookup
 │
 ▼
Connector router
 │
 ▼
CliConnector
 │
 ▼
create_subprocess_exec("git", "--version")
 │
 ▼
Normalized result
 │
 ▼
Redis + Prometheus
 │
 ▼
HTTP response
```

The planner never receives arbitrary shell access.

# 53. Control plane architecture

At large scale, separate configuration from invocation.

```text
                 CONTROL PLANE

 Admin UI / GitOps / API
           │
           ▼
 Tool Definition Service
           │
     ┌─────┼──────┐
     ▼     ▼      ▼
 Registry Policy Secrets refs
     │
     ▼
 Version publisher
     │
     ▼
 Signed snapshots

────────────────────────────────────

                  DATA PLANE

 Agent
   │
   ▼
 Gateway workers
   │
   ├── local registry snapshot
   ├── policy client/cache
   └── connector executors
```

This avoids putting a global control-plane database in every request's critical path.

# 54. Recommended production services

A mature deployment can evolve into:

```text
gateway-api
registry-service
policy-service
approval-service
audit-service
sandbox-scheduler
connector-health-controller
async-operation-service
configuration-distributor
```

Do not split services merely for architecture aesthetics. Extract them when scaling, ownership, isolation or availability requirements justify the operational cost.

# 55. Tool discovery architecture

With thousands of tools, injecting the entire catalog into an LLM context is inefficient.

Recommended pipeline:

```text
Agent intent
    │
    ▼
Capability search
    │
    ├─ lexical
    ├─ metadata filters
    └─ semantic retrieval
    │
    ▼
Policy visibility filter
    │
    ▼
Top candidate tools
    │
    ▼
LLM selection
```

Authorization still occurs again at invocation time. Discovery filtering improves UX; it is not a security boundary.

# 56. Connector lifecycle

Recommended states:

```text
DRAFT
  ↓
VALIDATING
  ↓
ACTIVE
  ↓
DEPRECATED
  ↓
DISABLED
```

A connector version should not mutate after activation. Publish a new version instead.

Validation can include:
- schema linting;
- ownership;
- endpoint policy;
- credential scope;
- contract tests;
- security review;
- health probe;
- sample invocation;
- rollback metadata.

# 57. Connector versioning

Use immutable identities such as:

```text
github.pr.comment@3
jira.issue.create@7
```

The human-friendly alias can point to a selected version.

This enables:
- canary rollout;
- rollback;
- agent pinning;
- reproducibility;
- forensic reconstruction.

# 58. Authentication production pattern

Recommended:

```text
Caller
  │
  ▼
API Gateway / Service Mesh
  │
  ▼
OIDC JWT
  │
  ▼
Connector Gateway
  │
  ▼
JWKS verification
  │
  ▼
Principal
```

Validate:
- signature;
- issuer;
- audience;
- expiry;
- not-before;
- key rotation;
- tenant/workload claims.

The development fallback identity must be disabled outside development.

# 59. Delegated authorization

A production agent may act:
- as itself;
- as a user;
- as a service;
- with explicitly delegated authority.

Preserve the delegation chain:

```text
Human
  ↓ delegates
Agent
  ↓ invokes
Gateway
  ↓ exchanges
Provider credential
```

Audit records should preserve both initiating user and executing workload where applicable.

# 60. Approval object design

A secure approval should authorize an exact effect.

Illustrative payload:

```json
{
  "tenant": "acme",
  "subject": "agent-17",
  "tool": "deployment.rollback",
  "tool_version": 4,
  "arguments_sha256": "...",
  "expires_at": "...",
  "nonce": "...",
  "approver": "user-42"
}
```

The approval service signs it. The gateway verifies signature, expiry, nonce, identity and argument hash before execution.

# 61. Idempotency state machine

For consequential writes, a stronger model than simple cached responses is:

```text
ABSENT
  │
  ▼
IN_PROGRESS
  ├──── failure before known effect ──► RETRYABLE
  ├──── success ──────────────────────► SUCCEEDED
  └──── unknown provider outcome ─────► INDETERMINATE
```

`INDETERMINATE` matters. If the network fails after a provider commits a payment, blindly retrying can duplicate the effect.

Use provider reconciliation APIs when available.

# 62. Retry matrix

| Failure | Read | Idempotent write | Non-idempotent write |
|---|---|---|---|
| DNS/connect timeout | Retry | Retry with key | Usually no |
| HTTP 429 | Backoff | Backoff | Provider-specific |
| HTTP 500/503 | Retry bounded | Retry bounded | Usually no |
| HTTP 400 | No | No | No |
| HTTP 401/403 | No | No | No |
| Schema error | No | No | No |
| Unknown outcome | Retry/reconcile | Reconcile | Reconcile |

Add jitter to avoid synchronized retry storms.

# 63. Rate limiting

Apply limits at several dimensions:

```text
tenant
principal
agent
tool
provider
credential
destination
```

Token buckets work well for ordinary rate limiting.

Provider quotas should be modeled independently from gateway ingress quotas.

# 64. Backpressure

When an upstream becomes slow:

1. cap concurrent requests;
2. bound queues;
3. reject excess work early;
4. expose retry-after guidance;
5. avoid allowing HTTP workers to accumulate indefinitely.

For long work, enqueue an asynchronous operation.

# 65. Async operation API

Recommended extension:

```text
POST /v1/operations
GET  /v1/operations/{id}
POST /v1/operations/{id}/cancel
```

Lifecycle:

```text
PENDING
  ↓
RUNNING
  ├─► SUCCEEDED
  ├─► FAILED
  ├─► CANCELLED
  └─► INDETERMINATE
```

This is better than holding an HTTP connection for a 20-minute deployment.

# 66. MCP production considerations

An MCP adapter should eventually support the protocol lifecycle required by the selected MCP transport and version.

Conceptual responsibilities:

```text
initialize
capability negotiation
tool discovery
tool call
progress/stream handling
cancellation
session cleanup
```

Do not automatically trust tool metadata supplied by arbitrary remote MCP servers. Registry governance remains authoritative.

# 67. REST production considerations

A mature REST connector needs:
- URI templates;
- query/path/header mapping;
- auth injection;
- content-type controls;
- pagination;
- response schemas;
- maximum body size;
- destination policy;
- TLS policy;
- provider error translation.

Never let a model inject arbitrary authorization headers.

# 68. GraphQL production considerations

GraphQL introduces unique resource-exhaustion risks.

Protect with:
- maximum query depth;
- maximum complexity;
- field allowlists;
- persisted operations;
- response limits;
- timeout;
- provider cost/quota tracking.

For high-risk APIs, expose domain tools rather than arbitrary query strings.

# 69. CLI production architecture

The included adapter is suitable for demonstrating controlled subprocess execution.

For production privileged execution:

```text
Gateway
  │
  ▼
Job request
  │
  ▼
Sandbox scheduler
  │
  ▼
Ephemeral microVM/container
  │
  ├─ read-only image
  ├─ temp workspace
  ├─ limited CPU/RAM/PIDs
  ├─ seccomp
  ├─ network policy
  ├─ short-lived identity
  └─ deadline
```

Destroy the environment after each task or trusted batch.

# 70. Network security

Recommended layers:

```text
Internet
  │
WAF/API Gateway
  │
mTLS/service mesh
  │
Gateway
  │
Egress proxy
  │
Approved providers
```

Block:
- cloud metadata endpoints;
- loopback;
- link-local;
- unintended RFC1918 ranges;
- unapproved ports/protocols.

# 71. Secrets architecture

```text
Tool Definition
     │
 credential_ref
     ▼
Secret Broker / Vault
     │
 short-lived secret
     ▼
Connector invocation
```

Secrets should never be part of:
- prompts;
- tool descriptions;
- ordinary logs;
- trace attributes;
- model-visible errors.

# 72. Logging model

Recommended structured event:

```json
{
  "timestamp": "...",
  "request_id": "...",
  "trace_id": "...",
  "tenant": "...",
  "principal": "...",
  "tool": "...",
  "tool_version": 3,
  "risk": "write",
  "policy": "allow",
  "approval_id": "...",
  "connector": "rest",
  "destination": "jira",
  "latency_ms": 142,
  "status": "ok"
}
```

Arguments and outputs require field-level redaction/classification.

# 73. Distributed tracing

Recommended spans:

```text
gateway.invoke
├── registry.lookup
├── policy.evaluate
├── approval.verify
├── idempotency.lookup
└── connector.invoke
    └── upstream.http / sandbox.execute
```

This makes latency attribution straightforward.

# 74. Metrics

Useful RED metrics:

```text
Rate
Errors
Duration
```

Plus:
- active invocations;
- queue depth;
- retries;
- timeouts;
- approval waits;
- circuit state;
- provider quota remaining where available;
- sandbox allocation failures.

# 75. Alerting

Examples:
- gateway 5xx above threshold;
- policy service unavailable;
- audit pipeline lag;
- provider error spike;
- abnormal destructive-tool volume;
- sandbox escape/security event;
- credential failures;
- idempotency conflicts;
- latency SLO burn.

Prefer SLO burn-rate alerts over static CPU-only alerts.

# 76. Capacity planning

Model:

```text
RPS × average gateway CPU
RPS × upstream latency
concurrent requests ≈ RPS × latency
```

Example: 2,000 RPS at 500 ms average external latency implies roughly 1,000 concurrent in-flight requests.

Async I/O handles waiting efficiently, but memory, connection pools, file descriptors and provider quotas still matter.

CLI jobs need a separate capacity model because each consumes isolated execution resources.

# 77. Connection management

Use long-lived client pools in production rather than constructing a new HTTP client for every request.

Tune:
- maximum connections;
- keep-alive connections;
- DNS behavior;
- TLS session reuse;
- idle timeout.

The compact implementation favors readability; refactor clients into lifecycle-managed shared pools for high throughput.

# 78. Caching

Safe candidates:
- tool metadata;
- policy metadata with bounded TTL;
- discovery results;
- read-only provider responses where semantics permit.

Do not cache sensitive or mutable results merely for performance.

Cache keys must include all authorization dimensions that affect the result.

# 79. Data residency

Route tenants according to policy:

```text
tenant → residency metadata → regional cell
```

Keep audit, secrets and connector execution within required regions when necessary.

# 80. Disaster recovery

Define RPO/RTO separately for:
- registry;
- approval records;
- audit;
- idempotency;
- configuration;
- async operations.

Tool definitions and audit history usually deserve durable backup. Ephemeral read caches generally do not.

# 81. Zero-downtime deployment

Use:
- immutable images;
- readiness before traffic;
- connection draining;
- rolling/canary deployment;
- backward-compatible schemas;
- versioned connector contracts.

Do not terminate a pod in the middle of a consequential unknown-outcome write without reconciliation semantics.

# 82. Kubernetes production checklist

Add:

```text
Deployment
Service
HPA
PDB
NetworkPolicy
ServiceAccount
ExternalSecret
Ingress/Gateway
Pod securityContext
readOnlyRootFilesystem
seccompProfile
topologySpreadConstraints
resource requests/limits
```

CLI sandboxes should be a separate worker pool with stronger isolation than ordinary API pods.

# 83. CI/CD

Recommended pipeline:

```text
format/lint
  ↓
unit tests
  ↓
contract tests
  ↓
security tests
  ↓
dependency scan
  ↓
container build
  ↓
SBOM
  ↓
image signing
  ↓
integration tests
  ↓
staging
  ↓
canary
  ↓
production
```

Connector definitions should pass conformance tests independently.

# 84. Local development workflow

```bash
cp .env.example .env
docker compose up -d redis postgres

python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export ENV=dev
export REDIS_URL=redis://localhost:6379/0

uvicorn app.main:app --reload --port 8080
```

In another terminal:

```bash
curl http://localhost:8080/health/live
curl http://localhost:8080/v1/tools
pytest -q
```

# 85. Docker debugging

List containers:

```bash
docker compose ps
```

Gateway logs:

```bash
docker compose logs -f gateway
```

Redis:

```bash
docker compose exec redis redis-cli ping
```

Postgres:

```bash
docker compose exec postgres psql -U gateway -d gateway
```

Rebuild:

```bash
docker compose build --no-cache gateway
docker compose up -d gateway
```

# 86. Common troubleshooting

## `/health/ready` returns 503

Check `REDIS_URL`, DNS and Redis availability.

## REST example fails

Public demo endpoints require internet access. Replace the endpoint with an accessible internal/test service if egress is restricted.

## MCP call fails

The project does not ship an upstream MCP server. Configure `MCP_SERVER_URL` to an appropriate compatible server.

## CLI executable denied

Add only a reviewed executable to `CLI_ALLOWLIST`. Do not use `*`.

## JWT requests fail

For development, omit the Authorization header with `ENV=dev`. For production, configure real JWT validation and remove development fallback.

# 87. Test strategy

Testing pyramid:

```text
                E2E
              /     \
         integration
        /             \
     contract        security
      \               /
          unit tests
```

Unit-test:
- policy;
- schemas;
- routing;
- normalization.

Contract-test:
- each provider;
- MCP compatibility;
- GraphQL error mapping.

Security-test:
- SSRF;
- command injection;
- cross-tenant access;
- token tampering;
- approval replay.

# 88. Fault injection

Test:
- provider 500;
- provider timeout;
- partial response;
- Redis failure;
- DNS failure;
- connection reset after write;
- sandbox crash;
- policy timeout;
- stale registry snapshot.

The most important question is not merely *does it retry?* but *can it determine whether a side effect occurred?*

# 89. Performance testing

Measure:
- gateway-added p50/p95/p99;
- maximum sustainable RPS;
- connection-pool saturation;
- event-loop lag;
- memory per in-flight invocation;
- Redis latency;
- connector-specific concurrency.

Separate synthetic gateway latency from upstream latency.

# 90. Security testing

Include:
- dependency scanning;
- container scanning;
- SAST;
- secret scanning;
- API fuzzing;
- SSRF regression suite;
- malicious MCP response corpus;
- GraphQL complexity attacks;
- CLI argument fuzzing;
- tenant isolation tests.

# 91. Application: SRE incident agent

Tool classes:

```text
metrics.query          read
logs.search            read
deployment.status      read
deployment.rollback    destructive
service.restart        destructive
```

The agent can investigate automatically but must cross an approval boundary before production mutation.

# 92. Application: software engineering agent

```text
repo.read
code.search
ci.status
issue.create
pr.comment
branch.create
test.run
```

The gateway centralizes repository credentials and provides a consistent audit trail across coding agents.

# 93. Application: customer support

```text
customer.lookup
order.lookup
refund.quote
refund.execute
ticket.comment
```

`refund.execute` can require an approval or policy threshold based on amount.

# 94. Application: enterprise research agent

```text
knowledge.search
web.fetch_approved
crm.lookup
document.retrieve
```

Use read-only tools by default and keep retrieved text untrusted.

# 95. Application: data agent

```text
catalog.search
warehouse.query_readonly
dashboard.lookup
report.publish
```

Query execution should have row/byte/time quotas and read-only credentials.

# 96. Application: cloud operations agent

```text
resource.describe
cost.query
k8s.get
k8s.logs
deployment.scale
deployment.rollback
```

Do not expose unrestricted cloud CLI credentials to the model.

# 97. Application: MCP federation

The gateway can present a curated catalog assembled from several MCP servers:

```text
Agent
  │
Gateway
  ├── MCP server: engineering
  ├── MCP server: analytics
  └── MCP server: support
```

The gateway remains the policy boundary even when upstream MCP servers have their own tool catalogs.

# 98. Application: multi-agent platform

Multiple specialized agents can share the same execution plane:

```text
Planner Agent ──┐
Coder Agent ────┤
SRE Agent ──────┼── Connector Gateway
Research Agent ─┤
Support Agent ──┘
```

Each receives different policy-visible tools despite sharing infrastructure.

# 99. Memory-server integration

A memory system and connector gateway should remain independent.

```text
Agent
 ├── Memory Server
 │     └── historical/contextual knowledge
 │
 └── Connector Gateway
       └── external capabilities
```

Never infer execution permission from a memory record. Memory is data, not authority.

# 100. Workflow-engine integration

For Temporal/LangGraph/etc.:

```text
Workflow
  │
  ▼
Gateway client
  │
  ▼
Connector Gateway
  │
  ▼
External effect
```

Workflow retry policy and gateway retry policy must be coordinated to avoid retry multiplication.

# 101. Preventing retry multiplication

If workflow layer retries 3× and gateway retries 3×, an upstream might receive up to 9 attempts.

Define ownership:
- gateway handles short transient network retries;
- workflow handles task-level retry/reconciliation.

Propagate attempt metadata where possible.

# 102. Output normalization

A common result envelope enables generic orchestration:

```json
{
  "request_id": "...",
  "tool": "...",
  "status": "ok",
  "output": {},
  "error": null,
  "latency_ms": 42.1
}
```

At larger scale add:
- connector version;
- provider request ID;
- retry count;
- cache status;
- warnings;
- output classification;
- pagination cursor.

# 103. Error taxonomy

Prefer typed errors:

```text
AUTHENTICATION_FAILED
AUTHORIZATION_DENIED
APPROVAL_REQUIRED
INVALID_ARGUMENT
TOOL_NOT_FOUND
TOOL_DISABLED
RATE_LIMITED
UPSTREAM_TIMEOUT
UPSTREAM_ERROR
SANDBOX_ERROR
INDETERMINATE
INTERNAL_ERROR
```

Agents can reason about typed failures more reliably than arbitrary exception strings.

# 104. Cancellation semantics

Cancellation is not equivalent to rollback.

If a client cancels:
- stop work that has not begun;
- propagate cancellation where the protocol supports it;
- do not claim a side effect was reversed;
- reconcile unknown outcomes.

# 105. Compensation

Some workflows need compensating actions:

```text
create_resource
  ↓
configure_resource fails
  ↓
delete_resource compensation
```

Compensation belongs primarily in the workflow/domain layer, while the gateway safely exposes both capabilities.

# 106. Audit architecture

Recommended:

```text
Invocation
  │
  ▼
Gateway DB transaction
  ├── invocation state
  └── outbox event
           │
           ▼
      event publisher
           │
           ▼
   immutable audit store
```

This avoids losing audit events between database commit and message publication.

# 107. Privacy

Minimize recorded data.

Classify:
- tool metadata;
- arguments;
- outputs;
- identity;
- provider IDs.

Apply:
- redaction;
- encryption;
- retention;
- deletion policy where legally permitted;
- access controls.

Audit integrity requirements may conflict with deletion requirements; design retention with legal/security teams.

# 108. Compliance readiness

Depending on the organization, useful controls include:
- access reviews;
- separation of duties;
- immutable audit;
- key rotation;
- connector ownership;
- change approvals;
- data residency;
- incident response;
- retention schedules.

The gateway provides enforcement points but does not itself make a deployment compliant.

# 109. Cost controls

Tool calls can incur external cost.

Attach metadata:

```text
estimated_cost_class
quota_group
provider_budget
```

Policy can deny or require approval above thresholds.

Track cost by tenant/tool/provider.

# 110. Tool quality scoring

Operationally track:
- success rate;
- p95 latency;
- schema failure rate;
- retry rate;
- user correction rate;
- approval rejection rate.

These metrics can improve discovery ranking without changing authorization.

# 111. Safe tool deprecation

1. mark deprecated;
2. emit discovery warning;
3. identify active consumers;
4. provide replacement;
5. block new bindings;
6. disable after migration;
7. retain historical version metadata for audit.

# 112. Schema evolution

Backward-compatible changes:
- optional fields;
- broader non-security response metadata.

Potentially breaking:
- renamed required field;
- changed semantics;
- broader permissions;
- changed side effects.

Publish a new tool version for breaking changes.

# 113. Principal-engineer interview discussion

Key topics this project demonstrates:

- abstraction boundaries;
- heterogeneous protocol federation;
- control/data plane separation;
- authorization vs authentication;
- side-effect semantics;
- distributed idempotency;
- retries and unknown outcomes;
- sandboxing;
- SSRF;
- multi-tenancy;
- blast-radius reduction;
- cell architecture;
- observability/SLOs;
- configuration distribution;
- versioning;
- supply-chain governance;
- agent-specific prompt injection threats.

# 114. Design question: why not just MCP?

MCP provides an agent-oriented protocol, but enterprises still have REST, GraphQL, CLI and proprietary systems. More importantly, a protocol alone does not define the organization's cross-provider policy, approvals, credential brokerage, tenant quotas, audit, egress or sandbox strategy.

The gateway can use MCP without requiring every backend to become MCP-native.

# 115. Design question: why not an API gateway?

Traditional API gateways excel at HTTP routing, authentication, rate limiting and edge policy.

Agent tool execution additionally needs:
- tool semantics;
- read/write/destructive classification;
- human approval;
- MCP;
- CLI sandboxing;
- tool discovery;
- model-safe schemas;
- agent delegation;
- prompt-injection-aware trust boundaries.

A Connector Gateway can sit behind or alongside a conventional API gateway.

# 116. Design question: why not put policy in the agent?

Because model output is not an authorization boundary.

An agent can propose an action. Trusted infrastructure must decide whether it may execute.

# 117. Design question: why schemas matter

Schemas reduce:
- hallucinated parameters;
- ambiguous commands;
- accidental privilege expansion;
- connector parsing complexity.

But schema validity does not imply authorization. Both are required.

# 118. Design question: how to scale to 100k tools

Do not send 100k definitions to the model.

Use:
1. tenant/role filtering;
2. capability indexing;
3. semantic/lexical retrieval;
4. top-K candidate selection;
5. invocation-time authorization.

Cache immutable registry snapshots regionally.

# 119. Design question: how to scale to millions of calls

- stateless async gateway workers;
- connection pooling;
- regional/cell partitioning;
- provider bulkheads;
- Redis/local metadata caches;
- asynchronous long operations;
- horizontally partitioned audit;
- quota-aware scheduling.

# 120. Design question: what is the hardest correctness problem?

Consequential external side effects with ambiguous outcomes.

Example:

```text
Gateway → provider: create payment
Provider commits
Connection breaks before response
Gateway does not know whether payment exists
```

Correct handling requires idempotency keys, provider request IDs and reconciliation—not merely retries.

# 121. Design question: what is the hardest security problem?

The agent consumes untrusted content while also possessing capabilities.

The architecture must prevent retrieved content from becoming authorization. Policy, approval, identity and sandbox boundaries must remain outside model control.

# 122. Recommended next implementation milestones

To evolve this repository into an organization-specific production deployment:

**Milestone A**
- PostgreSQL tool registry;
- Alembic migrations;
- versioned tools;
- OIDC/JWKS;
- pooled HTTP clients.

**Milestone B**
- Vault integration;
- OPA/Cedar;
- durable audit outbox;
- tenant rate limits;
- typed errors.

**Milestone C**
- sandbox workers;
- async operations;
- signed approvals;
- egress proxy;
- circuit breakers.

**Milestone D**
- multi-region cells;
- semantic discovery;
- signed connector manifests;
- automated conformance framework.

# 123. Complete quick-start checklist

```bash
# 1. Extract
unzip connector-gateway-professional.zip
cd connector-gateway-professional

# 2. Configure
cp .env.example .env

# 3. Start
docker compose up --build

# 4. Health
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready

# 5. Discover
curl http://localhost:8080/v1/tools

# 6. Invoke local CLI demo
curl -X POST http://localhost:8080/v1/invoke \
  -H 'content-type: application/json' \
  -d '{"tool":"cli.git_version","arguments":{}}'

# 7. Metrics
curl http://localhost:8080/metrics

# 8. Tests
docker compose exec gateway pytest -q || true

# 9. Stop
docker compose down
```

For local source tests, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

# 124. Final system view

```text
                               ┌────────────────────────────┐
                               │       CONTROL PLANE        │
                               │ Registry / Policy / IAM    │
                               │ Secrets / Approvals        │
                               │ Versions / Governance      │
                               └─────────────┬──────────────┘
                                             │
                                             ▼
┌─────────────┐                    ┌─────────────────────────┐
│ AI Agents   │                    │    CONNECTOR GATEWAY    │
│ LangGraph   │ ─────────────────► │                         │
│ Workflows   │                    │ Auth → Policy → Schema  │
│ Copilots    │ ◄───────────────── │ → Approval → Execute    │
└─────────────┘                    └────────────┬────────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
              ┌──────────┐               ┌──────────┐              ┌──────────┐
              │   MCP    │               │ REST /   │              │   CLI    │
              │ Servers  │               │ GraphQL  │              │ Sandbox  │
              └──────────┘               └──────────┘              └──────────┘
                    │                          │                          │
                    └──────────────────────────┼──────────────────────────┘
                                               ▼
                                      Enterprise Systems
```

The architectural objective is simple:

> **Give agents broad usefulness without giving model output unchecked authority.**

The Connector Gateway is the infrastructure boundary that turns arbitrary integrations into governed, observable, versioned and operationally manageable capabilities.
