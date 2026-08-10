from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry, ToolInfo


class _Echo(Tool):
    @property
    def name(self): return "echo"
    @property
    def description(self): return "Echoes input"
    def execute(self, params): return ToolResult(success=True, output=params.get("text", ""))


def test_tool_result_defaults():
    r = ToolResult(success=True, output="hi")
    assert r.error is None
    assert r.metadata == {}


def test_tool_result_failure():
    r = ToolResult(success=False, output="", error="oops")
    assert not r.success
    assert r.error == "oops"


def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(_Echo())
    tool = reg.get("echo")
    assert tool.name == "echo"


def test_registry_get_missing_raises():
    reg = ToolRegistry()
    try:
        reg.get("nope")
        assert False, "should raise"
    except KeyError:
        pass


def test_registry_list():
    reg = ToolRegistry()
    reg.register(_Echo())
    items = reg.list()
    assert len(items) == 1
    assert isinstance(items[0], ToolInfo)
    assert items[0].name == "echo"


def test_echo_tool():
    t = _Echo()
    r = t.execute({"text": "hello"})
    assert r.success
    assert r.output == "hello"
