import httpx, uuid
from app.config import settings
from app.connectors.base import Connector

class McpConnector(Connector):
    async def invoke(self, tool, args):
        payload = {
            "jsonrpc":"2.0", "id":str(uuid.uuid4()), "method":"tools/call",
            "params":{"name":args["name"],"arguments":args.get("arguments",{})}
        }
        base = settings.mcp_server_url.rstrip("/")
        path = tool.endpoint or "/"
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as c:
            r = await c.post(base + path, json=payload)
            r.raise_for_status()
            body = r.json()
            if "error" in body: raise RuntimeError(str(body["error"]))
            return body.get("result")
