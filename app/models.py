from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

class ConnectorKind(str, Enum):
    mcp = "mcp"
    rest = "rest"
    graphql = "graphql"
    cli = "cli"

class Risk(str, Enum):
    read = "read"
    write = "write"
    destructive = "destructive"

class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    connector: ConnectorKind
    description: str
    risk: Risk = Risk.read
    endpoint: str | None = None
    method: str | None = None
    command: list[str] | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

class Invocation(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    approval_token: str | None = None

class InvocationResult(BaseModel):
    request_id: str
    tool: str
    status: Literal["ok","denied","error"]
    output: Any = None
    error: str | None = None
    latency_ms: float
