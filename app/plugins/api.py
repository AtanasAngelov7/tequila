"""FastAPI router for plugin management (Sprint 12, §8.8).

Endpoints
---------
GET    /api/plugins                       — list all plugins
POST   /api/plugins                       — install/register a plugin
GET    /api/plugins/{plugin_id}           — get detail
PATCH  /api/plugins/{plugin_id}           — update config
DELETE /api/plugins/{plugin_id}           — uninstall
POST   /api/plugins/{plugin_id}/activate  — start/activate
POST   /api/plugins/{plugin_id}/deactivate — stop/deactivate
POST   /api/plugins/{plugin_id}/test      — test connectivity
GET    /api/plugins/{plugin_id}/tools     — list tools provided
POST   /api/plugins/refresh               — reload all states from DB
GET    /api/plugins/{plugin_id}/health    — on-demand health check
GET    /api/plugins/{plugin_id}/dependencies      — list deps + installed status
POST   /api/plugins/{plugin_id}/dependencies/install — install missing deps
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import logging
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import get_db_dep, get_write_db_dep, require_gateway_token
from app.plugins.models import PluginRecord
from app.plugins.registry import PluginRegistry, get_plugin_registry
from app.plugins.store import save_credential

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/plugins",
    tags=["plugins"],
    dependencies=[Depends(require_gateway_token)],
)

# ── Request / response schemas ────────────────────────────────────────────────


class InstallRequest(BaseModel):
    plugin_id: str
    """ID of the built-in plugin to install, e.g. ``"telegram"``."""


class PatchConfigRequest(BaseModel):
    config: dict[str, Any] = {}
    """Plugin-specific configuration dict."""


class SaveCredentialRequest(BaseModel):
    credential_key: str
    """Credential key, e.g. ``"bot_token"``."""
    value: str
    """Raw (plaintext) credential value."""


# ── Dependency ────────────────────────────────────────────────────────────────


def _registry() -> PluginRegistry:
    try:
        return get_plugin_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[PluginRecord])
async def list_plugins(
    registry: PluginRegistry = Depends(_registry),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PluginRecord]:
    """Return all registered plugins and their current status (TD-183: with pagination)."""
    records = registry.list_records()
    return records[offset : offset + limit]


@router.post("", response_model=PluginRecord, status_code=status.HTTP_201_CREATED)
async def install_plugin(
    body: InstallRequest,
    registry: PluginRegistry = Depends(_registry),
) -> PluginRecord:
    """Install a built-in plugin by its ``plugin_id``.

    The plugin class must already be registered with the registry (i.e. it is
    in the builtins list).  This just persists the record and returns it;
    call ``/activate`` to start it.
    """
    existing = registry.get_record(body.plugin_id)
    if existing is not None:
        return existing  # idempotent

    instance = registry.get_instance(body.plugin_id)
    if instance is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plugin {body.plugin_id!r} is not available. "
                   "Check that the built-in plugin is registered.",
        )
    record = await registry.install(type(instance))
    return record


@router.get("/refresh", status_code=status.HTTP_200_OK)
async def refresh_plugins(
    registry: PluginRegistry = Depends(_registry),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict[str, Any]:
    """Reload plugin records from the database."""
    from app.plugins.store import load_all_plugins

    records = await load_all_plugins(db)
    # TD-173: Use public method instead of accessing private _records
    registry.refresh_records(records)
    return {"reloaded": len(records)}


@router.get("/{plugin_id}", response_model=PluginRecord)
async def get_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> PluginRecord:
    rec = registry.get_record(plugin_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    return rec


@router.patch("/{plugin_id}", response_model=PluginRecord)
async def update_plugin_config(
    plugin_id: str,
    body: PatchConfigRequest,
    registry: PluginRegistry = Depends(_registry),
) -> PluginRecord:
    """Update the plugin's config and trigger a fresh configure() cycle."""
    if registry.get_record(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        return await registry.configure_plugin(plugin_id, body.config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> None:
    if registry.get_record(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    await registry.uninstall(plugin_id)


@router.post("/{plugin_id}/activate", response_model=PluginRecord)
async def activate_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> PluginRecord:
    if registry.get_record(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        return await registry.activate_plugin(plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{plugin_id}/deactivate", response_model=PluginRecord)
async def deactivate_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> PluginRecord:
    if registry.get_record(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        return await registry.deactivate_plugin(plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{plugin_id}/test")
async def test_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> dict[str, Any]:
    instance = registry.get_instance(plugin_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        result = await instance.test()
        return result.model_dump()
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.get("/{plugin_id}/health")
async def health_check(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> dict[str, Any]:
    instance = registry.get_instance(plugin_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        result = await instance.health_check()
        return result.model_dump()
    except Exception as exc:
        return {"healthy": False, "message": str(exc)}


@router.get("/{plugin_id}/tools")
async def list_plugin_tools(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> list[Any]:
    instance = registry.get_instance(plugin_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    try:
        tools = await instance.get_tools()
        # Return serialisable summaries
        result = []
        for t in tools:
            if hasattr(t, "model_dump"):
                result.append(t.model_dump())
            elif hasattr(t, "__dict__"):
                result.append({"name": getattr(t, "name", str(t))})
            else:
                result.append({"name": str(t)})
        return result
    except Exception as exc:
        # TD-177: Don't leak internal error details to client
        logger.exception("Error getting tools for plugin %r", plugin_id)
        raise HTTPException(status_code=500, detail="Internal plugin error.") from exc


@router.get("/{plugin_id}/dependencies")
async def get_dependencies(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> dict[str, Any]:
    instance = registry.get_instance(plugin_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    deps = instance.get_dependencies()
    installed: dict[str, bool] = {}
    for pkg_spec in deps.python_packages:
        pkg_name = pkg_spec.split(">=")[0].split("==")[0].split("[")[0].strip()
        try:
            importlib.import_module(pkg_name.replace("-", "_"))
            installed[pkg_spec] = True
        except ImportError:
            installed[pkg_spec] = False
    return {
        "python_packages": deps.python_packages,
        "system_commands": deps.system_commands,
        "optional": deps.optional,
        "installed": installed,
    }


@router.post("/{plugin_id}/dependencies/install", status_code=status.HTTP_202_ACCEPTED)
async def install_dependencies(
    plugin_id: str,
    registry: PluginRegistry = Depends(_registry),
) -> dict[str, Any]:
    """Trigger pip install for missing plugin dependencies (async, best-effort)."""
    instance = registry.get_instance(plugin_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    deps = instance.get_dependencies()
    if not deps.python_packages:
        return {"installed": [], "message": "No Python packages to install."}

    results = []
    for pkg_spec in deps.python_packages:
        # TD-143: Basic package name validation
        import re as _re
        pkg_name_only = _re.split(r'[>=<\[!;]', pkg_spec)[0].strip()
        if not _re.match(r'^[a-zA-Z0-9_.-]+$', pkg_name_only):
            results.append({"package": pkg_spec, "success": False, "output": "Invalid package name"})
            continue
        # TD-332: Reject specs that could inject pip arguments (e.g. --index-url)
        if pkg_spec.startswith("-") or " -" in pkg_spec or any(
            c in pkg_spec for c in (";", "|", "&", "`", "$", "\n")
        ):
            results.append({"package": pkg_spec, "success": False, "output": "Suspicious package spec rejected"})
            continue
        # Only allow name[extras]<version_constraints> — no URLs or paths
        if not _re.match(r'^[a-zA-Z0-9_.-]+(\[[a-zA-Z0-9_,.-]+\])?(([><=!~]+[a-zA-Z0-9_.*]+)(,[><=!~]+[a-zA-Z0-9_.*]+)*)?$', pkg_spec.strip()):
            results.append({"package": pkg_spec, "success": False, "output": "Package spec format not allowed"})
            continue
        try:
            # TD-148: Use asyncio.create_subprocess_exec instead of blocking subprocess.run
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", pkg_spec, "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            results.append({"package": pkg_spec, "success": proc.returncode == 0, "output": stderr.decode().strip()})
        except Exception as exc:  # noqa: BLE001
            results.append({"package": pkg_spec, "success": False, "output": str(exc)})

    return {"installed": results}


@router.post("/{plugin_id}/credentials")
async def save_plugin_credential(
    plugin_id: str,
    body: SaveCredentialRequest,
    db: aiosqlite.Connection = Depends(get_write_db_dep),  # TD-257: Use write dep
    registry: PluginRegistry = Depends(_registry),
) -> dict[str, str]:
    """Store an encrypted credential for a plugin (e.g. API token, bot token)."""
    if registry.get_record(plugin_id) is None and registry.get_instance(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found.")
    await save_credential(db, plugin_id, body.credential_key, body.value)
    return {"status": "saved", "plugin_id": plugin_id, "credential_key": body.credential_key}
