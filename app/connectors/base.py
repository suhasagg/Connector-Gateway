from abc import ABC, abstractmethod
from typing import Any
from app.models import ToolDefinition

class Connector(ABC):
    @abstractmethod
    async def invoke(self, tool: ToolDefinition, args: dict[str, Any]) -> Any: ...
