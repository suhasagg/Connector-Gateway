from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.models import Invocation, ToolDefinition
from app.security import principal_from_auth, require_scope
from app.service import GatewayService

app = FastAPI(title="Connector Gateway", version="1.0.0")
svc = GatewayService()

@app.get("/health/live")
async def live(): return {"status":"ok"}

@app.get("/health/ready")
async def ready():
    try:
        await svc.redis.ping()
        return {"status":"ready"}
    except Exception as e:
        raise HTTPException(503, str(e))

@app.get("/v1/tools")
async def tools(p=Depends(principal_from_auth)):
    require_scope(p, "tools:read")
    return svc.registry.list()

@app.put("/v1/tools/{name}")
async def register(name: str, tool: ToolDefinition, p=Depends(principal_from_auth)):
    require_scope(p, "tools:write")
    if name != tool.name: raise HTTPException(400, "name mismatch")
    svc.registry.put(tool)
    return tool

@app.post("/v1/invoke")
async def invoke(req: Invocation, p=Depends(principal_from_auth)):
    return await svc.invoke(p, req)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
