"""Unit tests for Sprint 13 D6 — Plugin Discovery."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# ── Fixture: fake plugin directory ────────────────────────────────────────────


MINIMAL_PLUGIN = '''\
from app.plugins.base import PluginBase
from app.plugins.models import PluginAuth, PluginDependencies


class Plugin(PluginBase):
    plugin_id = "testdisco"
    name = "Test Discovery Plugin"
    description = "Created by test"
    version = "1.0.0"
    plugin_type = "connector"
    auth = PluginAuth(type="none")
    dependencies = PluginDependencies()

    async def activate(self) -> None:
        pass

    async def deactivate(self) -> None:
        pass

    async def health_check(self):
        from app.plugins.models import PluginHealthResult
        return PluginHealthResult(healthy=True)
'''


def _make_plugin_dir(tmp_path: Path, pkg_name: str, plugin_code: str) -> Path:
    """Create a minimal plugin package under tmp_path/pkg_name/__plugin__.py."""
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__plugin__.py").write_text(plugin_code)
    return pkg


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_discover_plugins_finds_class(tmp_path: Path):
    """discover_plugins() should return the Plugin class from __plugin__.py."""
    _make_plugin_dir(tmp_path, "myplugin", MINIMAL_PLUGIN)

    # Add tmp_path to sys.path so the dynamic import works
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))

    try:
        from app.plugins.discovery import discover_plugins
        from app.plugins.base import PluginBase

        classes = discover_plugins(tmp_path)
        assert len(classes) == 1
        cls = classes[0]
        assert issubclass(cls, PluginBase)
        assert cls.plugin_id == "testdisco"
    finally:
        sys.path.remove(str(tmp_path))


def test_discover_plugins_empty_dir(tmp_path: Path):
    """Empty directory => empty list."""
    from app.plugins.discovery import discover_plugins

    classes = discover_plugins(tmp_path)
    assert classes == []


def test_discover_plugins_ignores_dir_without_plugin_file(tmp_path: Path):
    """A package without __plugin__.py must be silently skipped."""
    pkg = tmp_path / "noplugin"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("x = 1")

    from app.plugins.discovery import discover_plugins

    classes = discover_plugins(tmp_path)
    assert classes == []


def test_discover_plugins_tolerates_import_error(tmp_path: Path, capsys):
    """A plugin with a broken import must be skipped, not crash the process."""
    pkg = tmp_path / "brokenplug"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__plugin__.py").write_text("import nonexistent_module_xyz\nclass Plugin: pass\n")

    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))

    try:
        from app.plugins.discovery import discover_plugins

        classes = discover_plugins(tmp_path)
        # Should return empty without raising
        assert classes == []
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))


def test_discover_plugins_multiple_packages(tmp_path: Path):
    """Multiple valid plugin packages are all discovered."""
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))

    try:
        PLUGIN_A = MINIMAL_PLUGIN.replace("testdisco", "disco_a").replace("Test Discovery Plugin", "A")
        PLUGIN_B = MINIMAL_PLUGIN.replace("testdisco", "disco_b").replace("Test Discovery Plugin", "B")
        _make_plugin_dir(tmp_path, "plugin_a", PLUGIN_A)
        _make_plugin_dir(tmp_path, "plugin_b", PLUGIN_B)

        from app.plugins.discovery import discover_plugins

        classes = discover_plugins(tmp_path)
        ids = {cls.plugin_id for cls in classes}
        assert "disco_a" in ids
        assert "disco_b" in ids
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
