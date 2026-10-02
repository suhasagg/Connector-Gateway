import json, uuid
import jsonschema
import redis.asyncio as redis
from app.config import settings
from app.models import Invocation, InvocationResult, ConnectorKind
from app.policy import PolicyEngine
from app.registry import ToolRegistry
from app.connectors.rest import RestConnector
from app.connectors.graphql import GraphQLConnector
from app.connectors.cli import CliConnector
from app.connectors.mcp import McpConnector
from app.observability import INVOCATIONS, LATENCY, Timer

class GatewayService:
    def __init__(self):
        self.registry = ToolRegistry()
        self.policy = PolicyEngine()
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.connectors = {
            ConnectorKind.rest: RestConnector(),
            ConnectorKind.graphql: GraphQLConnector(),
            ConnectorKind.cli: CliConnector(),
            ConnectorKind.mcp: McpConnector(),
        }

    async def invoke(self, principal, req: Invocation):
        timer = Timer()
        request_id = str(uuid.uuid4())
        tool = self.registry.get(req.tool)
        if not tool:
            return InvocationResult(request_id=request_id, tool=req.tool, status="error", error="unknown tool", latency_ms=timer.ms)
        decision = self.policy.decide(principal, tool)
        if not decision.allowed:
            INVOCATIONS.labels(req.tool,"denied").inc()
            return InvocationResult(request_id=request_id, tool=req.tool, status="denied", error=decision.reason, latency_ms=timer.ms)
        if decision.approval_required and not req.approval_token:
            INVOCATIONS.labels(req.tool,"denied").inc()
            return InvocationResult(request_id=request_id, tool=req.tool, status="denied", error="approval required", latency_ms=timer.ms)
        try:
            jsonschema.validate(req.arguments, tool.input_schema or {})
            cache_key = None
            if req.idempotency_key:
                cache_key = f"idem:{principal.tenant}:{req.tool}:{req.idempotency_key}"
                cached = await self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return InvocationResult(**data)
            with LATENCY.labels(req.tool).time():
                output = await self.connectors[tool.connector].invoke(tool, req.arguments)
            result = InvocationResult(request_id=request_id, tool=req.tool, status="ok", output=output, latency_ms=timer.ms)
            if cache_key:
                await self.redis.set(cache_key, result.model_dump_json(), ex=86400)
            INVOCATIONS.labels(req.tool,"ok").inc()
            return result
        except Exception as e:
            INVOCATIONS.labels(req.tool,"error").inc()
            return InvocationResult(request_id=request_id, tool=req.tool, status="error", error=str(e)[:4000], latency_ms=timer.ms)
