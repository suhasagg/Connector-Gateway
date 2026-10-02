from app.models import ToolDefinition, ConnectorKind, Risk

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._seed()

    def _seed(self):
        examples = [
            ToolDefinition(
                name="http.echo", connector=ConnectorKind.rest,
                description="POST JSON to a configured HTTP endpoint",
                endpoint="https://httpbin.org/anything", method="POST",
                risk=Risk.read,
                input_schema={"type":"object","additionalProperties":True}
            ),
            ToolDefinition(
                name="graphql.query", connector=ConnectorKind.graphql,
                description="Execute a parameterized GraphQL query",
                endpoint="https://countries.trevorblades.com/",
                method="POST", risk=Risk.read,
                input_schema={"type":"object","required":["query"],"properties":{"query":{"type":"string"},"variables":{"type":"object"}}}
            ),
            ToolDefinition(
                name="cli.git_version", connector=ConnectorKind.cli,
                description="Return installed git version", command=["git","--version"],
                risk=Risk.read, input_schema={"type":"object","additionalProperties":False}
            ),
            ToolDefinition(
                name="mcp.call", connector=ConnectorKind.mcp,
                description="Invoke a tool on an upstream MCP-compatible JSON-RPC endpoint",
                endpoint="/", method="POST", risk=Risk.read,
                input_schema={"type":"object","required":["name"],"properties":{"name":{"type":"string"},"arguments":{"type":"object"}}}
            ),
        ]
        for t in examples: self._tools[t.name] = t

    def list(self): return list(self._tools.values())
    def get(self, name: str): return self._tools.get(name)
    def put(self, tool: ToolDefinition): self._tools[tool.name] = tool
