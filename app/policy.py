from dataclasses import dataclass
from app.models import ToolDefinition, Risk
from app.security import Principal

@dataclass
class Decision:
    allowed: bool
    reason: str
    approval_required: bool = False

class PolicyEngine:
    def decide(self, principal: Principal, tool: ToolDefinition) -> Decision:
        if not tool.enabled:
            return Decision(False, "tool disabled")
        if "tools:invoke" not in principal.scopes:
            return Decision(False, "principal cannot invoke tools")
        if tool.risk in {Risk.write, Risk.destructive} and "tools:write" not in principal.scopes:
            return Decision(False, "write scope required")
        if tool.risk == Risk.destructive:
            return Decision(True, "destructive action requires approval", True)
        return Decision(True, "policy allowed")
