"""Plugin system — connectors, pipeline hooks, audit sinks (Sprint 12, §8).

Public API:
    init_plugin_registry(db)  — call once at startup
    get_plugin_registry()     — returns the singleton PluginRegistry
"""
from __future__ import annotations
