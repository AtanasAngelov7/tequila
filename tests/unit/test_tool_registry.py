"""Unit tests for app/tools/registry.py — registration, @tool decorator, safety."""
import pytest

from app.tools.registry import ToolDefinition, ToolRegistry, SafetyLevel, tool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_registry() -> ToolRegistry:
    """Return a fresh, isolated ToolRegistry for each test."""
    return ToolRegistry()


# ── ToolDefinition ────────────────────────────────────────────────────────────


def test_tool_definition_defaults() -> None:
    td = ToolDefinition(
        name="echo",
        description="Echo the input.",
        parameters={"type": "object", "properties": {}},
    )
    assert td.safety == "side_effect"
    assert td.name == "echo"


def test_tool_definition_to_provider_tool_def() -> None:
    td = ToolDefinition(
        name="read_file",
        description="Read a file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        safety="read_only",
    )
    d = td.to_provider_tool_def()
    assert d["name"] == "read_file"
    assert d["safety"] == "read_only"


# ── ToolRegistry ──────────────────────────────────────────────────────────────


def test_register_and_get() -> None:
    registry = _make_registry()
    td = ToolDefinition(name="ping", description="Ping.", parameters={})
    fn = lambda: "pong"  # noqa: E731
    registry.register(td, fn)

    result = registry.get("ping")
    assert result is not None
    got_td, got_fn = result
    assert got_td.name == "ping"
    assert got_fn() == "pong"


def test_get_returns_none_for_unknown() -> None:
    registry = _make_registry()
    assert registry.get("nonexistent") is None


def test_list_sorted_by_name() -> None:
    registry = _make_registry()
    for name in ["zzz", "aaa", "mmm"]:
        registry.register(ToolDefinition(name=name, description="", parameters={}), lambda: None)
    names = [td.name for td in registry.list()]
    assert names == sorted(names)


def test_by_safety_filter() -> None:
    registry = _make_registry()
    for name, safety in [("r", "read_only"), ("s", "side_effect"), ("d", "destructive")]:
        registry.register(
            ToolDefinition(name=name, description="", parameters={}, safety=safety),  # type: ignore[arg-type]
            lambda: None,
        )
    destructive = registry.by_safety("destructive")
    assert len(destructive) == 1
    assert destructive[0].name == "d"


def test_names_set() -> None:
    registry = _make_registry()
    registry.register(ToolDefinition(name="a", description="", parameters={}), lambda: None)
    registry.register(ToolDefinition(name="b", description="", parameters={}), lambda: None)
    assert registry.names() == {"a", "b"}


def test_len() -> None:
    registry = _make_registry()
    assert len(registry) == 0
    registry.register(ToolDefinition(name="x", description="", parameters={}), lambda: None)
    assert len(registry) == 1


def test_overwrite_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    registry = _make_registry()
    td = ToolDefinition(name="dup", description="", parameters={})
    registry.register(td, lambda: "v1")
    # Use root-level capture to reliably intercept child logger messages
    with caplog.at_level(logging.WARNING):
        registry.register(td, lambda: "v2")
    assert "already registered" in caplog.text


# ── @tool decorator ───────────────────────────────────────────────────────────


def test_tool_decorator_registers_in_provided_registry() -> None:
    registry = _make_registry()

    @tool(description="Return hello.", safety="read_only", registry=registry)
    def say_hello() -> str:
        """Say hello."""
        return "hello"

    entry = registry.get("say_hello")
    assert entry is not None
    td, fn = entry
    assert td.name == "say_hello"
    assert td.safety == "read_only"
    assert fn() == "hello"


def test_tool_decorator_uses_docstring_as_description() -> None:
    registry = _make_registry()

    @tool(registry=registry)
    def documented() -> str:
        """This is the docstring."""
        return "ok"

    td, _ = registry.get("documented")  # type: ignore[misc]
    assert td.description == "This is the docstring."


def test_tool_decorator_infers_parameters_from_signature() -> None:
    registry = _make_registry()

    @tool(registry=registry)
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    td, _ = registry.get("add")  # type: ignore[misc]
    props = td.parameters["properties"]
    assert "a" in props
    assert props["a"]["type"] == "integer"
    assert "b" in props
    assert "a" in td.parameters["required"]
    assert "b" in td.parameters["required"]


def test_tool_decorator_name_override() -> None:
    registry = _make_registry()

    @tool(name="custom_name", description="Custom.", registry=registry)
    def original_name() -> str:
        return "ok"

    assert registry.get("custom_name") is not None
    assert registry.get("original_name") is None
