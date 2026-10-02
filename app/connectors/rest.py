import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings
from app.connectors.base import Connector

class RestConnector(Connector):
    @retry(stop=stop_after_attempt(settings.max_retries + 1), wait=wait_exponential(min=0.1, max=2), reraise=True)
    async def invoke(self, tool, args):
        method = (tool.method or "POST").upper()
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=False) as c:
            r = await c.request(method, tool.endpoint, json=args if method not in {"GET","DELETE"} else None,
                                params=args if method in {"GET","DELETE"} else None)
            r.raise_for_status()
            ctype = r.headers.get("content-type","")
            return r.json() if "json" in ctype else {"text": r.text[:100000]}
