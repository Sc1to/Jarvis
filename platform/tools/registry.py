from dataclasses import dataclass
from .base import Tool


@dataclass
class ToolInfo:
    name: str
    description: str


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered")
        return self._tools[name]

    def list(self) -> list[ToolInfo]:
        return [ToolInfo(t.name, t.description) for t in self._tools.values()]


registry = ToolRegistry()
