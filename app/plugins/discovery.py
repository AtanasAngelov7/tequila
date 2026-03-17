"""Custom plugin auto-discovery (Sprint 13, D6, §8.7).

Scans :func:`~app.paths.plugins_dir` for Python packages that contain a
``__plugin__.py`` file.  The ``__plugin__.py`` must export (at module level)
a ``PluginBase`` subclass named ``Plugin`` or a name matching the package name
in PascalCase.

Directory layout expected::

    data/plugins/
        my_plugin/
            __init__.py          # optional
            __plugin__.py        # required — exports Plugin class
            ...

Optionally the directory can also be watched for new plugins without restart
(file-watcher mode, enabled via :func:`start_watcher`).

Usage inside FastAPI lifespan::

    from app.plugins.discovery import discover_plugins
    from app.plugins.registry import get_plugin_registry

    extra = discover_plugins()
    registry = get_plugin_registry()
    for plugin_class in extra:
        registry.register_class(plugin_class)
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.plugins.base import PluginBase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core discovery
# ---------------------------------------------------------------------------


def discover_plugins(directory: Path | None = None) -> list[type["PluginBase"]]:
    """Scan *directory* for ``__plugin__.py`` packages and return plugin classes.

    Parameters
    ----------
    directory:
        Custom plugins directory to scan.  Defaults to
        :func:`~app.paths.plugins_dir`.

    Returns
    -------
    list[type[PluginBase]]
        All discovered (not yet instantiated) plugin classes, sorted by
        ``plugin_id``.
    """
    from app.paths import plugins_dir
    from app.plugins.base import PluginBase

    scan_dir = directory or plugins_dir()
    if not scan_dir.exists():
        logger.debug("Plugin discovery: directory %s does not exist — skipping.", scan_dir)
        return []

    discovered: list[type[PluginBase]] = []
    for pkg_path in sorted(scan_dir.iterdir()):
        if not pkg_path.is_dir():
            continue
        plugin_file = pkg_path / "__plugin__.py"
        if not plugin_file.exists():
            continue
        plugin_class = _load_plugin_class(pkg_path, plugin_file)
        if plugin_class is not None:
            discovered.append(plugin_class)

    logger.info(
        "Plugin discovery complete: %d custom plugin(s) found in %s.",
        len(discovered),
        scan_dir,
    )
    return discovered


def _load_plugin_class(
    pkg_path: Path,
    plugin_file: Path,
) -> type["PluginBase"] | None:
    """Import *plugin_file* and return the PluginBase subclass within it."""
    from app.plugins.base import PluginBase

    pkg_name = pkg_path.name
    module_name = f"_custom_plugin_{pkg_name}"

    # Add package root to sys.path so relative imports work inside the plugin.
    pkg_parent = str(pkg_path.parent)
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)

    try:
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for %s.", plugin_file)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load custom plugin %r: %s", pkg_name, exc)
        return None

    # Look for a PluginBase subclass in the module.
    plugin_class = getattr(module, "Plugin", None)
    if plugin_class is None:
        # Try PascalCase of package name
        pascal = _to_pascal(pkg_name)
        plugin_class = getattr(module, pascal, None)

    if plugin_class is None:
        # Search all module attributes
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if (
                attr is not None
                and isinstance(attr, type)
                and issubclass(attr, PluginBase)
                and attr is not PluginBase
            ):
                plugin_class = attr
                break

    if plugin_class is None:
        logger.warning(
            "Custom plugin %r loaded but no PluginBase subclass found.", pkg_name
        )
        return None

    if not hasattr(plugin_class, "plugin_id") or not plugin_class.plugin_id:
        logger.warning(
            "Custom plugin %r: class %r has no plugin_id — skipping.",
            pkg_name, plugin_class.__name__,
        )
        return None

    logger.info(
        "Discovered custom plugin %r → %r (plugin_id=%r).",
        pkg_name, plugin_class.__name__, plugin_class.plugin_id,
    )
    return plugin_class


# ---------------------------------------------------------------------------
# Optional file-watcher (hot reload)
# ---------------------------------------------------------------------------

_watcher_task = None


async def start_watcher(
    registry: "PluginRegistry",  # type: ignore[name-defined]  # noqa: F821
    poll_interval: float = 30.0,
    directory: Path | None = None,
) -> None:
    """Start a background asyncio task that polls for new plugin packages.

    New plugin packages have their class registered with *registry* if not
    already present.  Requires no external dependencies (poll, not inotify).
    """
    import asyncio

    from app.paths import plugins_dir

    async def _poll() -> None:
        scan_dir = directory or plugins_dir()
        seen: set[str] = set()
        while True:
            try:
                current = discover_plugins(scan_dir)
                for cls in current:
                    if cls.plugin_id not in seen:
                        registry.register_class(cls)
                        seen.add(cls.plugin_id)
                        logger.info(
                            "Hot-reloaded custom plugin %r.", cls.plugin_id
                        )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Plugin watcher error: %s", exc)
            await asyncio.sleep(poll_interval)

    global _watcher_task  # noqa: PLW0603
    import asyncio
    _watcher_task = asyncio.create_task(_poll(), name="plugin-discovery-watcher")


async def stop_watcher() -> None:
    """Cancel the discovery watcher task if running."""
    global _watcher_task  # noqa: PLW0603
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
        try:
            import asyncio
            await _watcher_task
        except Exception:  # noqa: BLE001
            pass
    _watcher_task = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_pascal(name: str) -> str:
    """Convert ``snake_case`` to ``PascalCase``."""
    return "".join(word.capitalize() for word in name.split("_"))
