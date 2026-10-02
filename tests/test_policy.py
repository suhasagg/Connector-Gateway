from app.policy import PolicyEngine
from app.models import ToolDefinition, ConnectorKind, Risk
from app.security import Principal

def test_destructive_requires_approval():
    p = Principal("u","t",frozenset({"tools:invoke","tools:write"}))
    t = ToolDefinition(name="x",connector=ConnectorKind.rest,description="x",risk=Risk.destructive)
    d = PolicyEngine().decide(p,t)
    assert d.allowed and d.approval_required

def test_write_scope():
    p = Principal("u","t",frozenset({"tools:invoke"}))
    t = ToolDefinition(name="x",connector=ConnectorKind.rest,description="x",risk=Risk.write)
    assert not PolicyEngine().decide(p,t).allowed
