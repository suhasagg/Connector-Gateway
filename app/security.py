from dataclasses import dataclass
import jwt
from fastapi import Header, HTTPException
from app.config import settings

@dataclass(frozen=True)
class Principal:
    subject: str
    tenant: str
    scopes: frozenset[str]

async def principal_from_auth(authorization: str | None = Header(default=None)) -> Principal:
    if settings.env == "dev" and not authorization:
        return Principal("dev-user", "dev-tenant", frozenset({"tools:read","tools:invoke","tools:write","tools:approve"}))
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        payload = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return Principal(
            str(payload["sub"]),
            str(payload["tenant"]),
            frozenset(str(payload.get("scope","")).split())
        )
    except Exception as e:
        raise HTTPException(401, f"invalid token: {e}")

def require_scope(p: Principal, scope: str):
    if scope not in p.scopes:
        raise HTTPException(403, f"missing scope {scope}")
