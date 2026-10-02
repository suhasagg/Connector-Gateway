import httpx
from app.config import settings
from app.connectors.base import Connector

class GraphQLConnector(Connector):
    async def invoke(self, tool, args):
        payload = {"query": args["query"], "variables": args.get("variables", {})}
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as c:
            r = await c.post(tool.endpoint, json=payload)
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                raise RuntimeError(f"GraphQL errors: {body['errors']}")
            return body.get("data")
