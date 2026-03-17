"""Documents connector plugin (Sprint 13, §8.6).

Provides 32 tools across PDF, PPTX, HTML-presentation, DOCX, XLSX, CSV,
data analysis and chart domains.  No credentials required — tools operate on
local file paths.

Dependencies:
    PyMuPDF (fitz), pymupdf4llm, pypdf,
    python-pptx, python-docx,
    openpyxl, fpdf2, duckdb,
    matplotlib, Pillow
"""
from __future__ import annotations

import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.documents.tools import DOCUMENTS_TOOLS, TOOL_FN_MAP
from app.plugins.models import PluginDependencies

logger = logging.getLogger(__name__)


class DocumentsPlugin(PluginBase):
    """Document processing plugin — PDF, PPTX, DOCX, XLSX, CSV, charts."""

    plugin_id = "documents"
    name = "Documents"
    description = (
        "Create, read and transform PDF, PPTX, HTML presentations, DOCX, XLSX, CSV "
        "files and render charts.  Works on local file paths — no external API keys required."
    )
    version = "1.0.0"
    plugin_type = "connector"

    def __init__(self) -> None:
        self._active = False
        self._registered_names: list[str] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        """Documents plugin needs no credentials — no-op."""

    async def activate(self) -> None:
        """Register all document tools with the global ToolRegistry."""
        from app.tools.registry import ToolDefinition, get_tool_registry

        registry = get_tool_registry()
        self._registered_names = []
        for tool_def in DOCUMENTS_TOOLS:
            td = ToolDefinition(
                name=tool_def["name"],
                description=tool_def["description"],
                parameters=tool_def["parameters"],
                safety=tool_def.get("safety", "side_effect"),
            )
            fn = TOOL_FN_MAP[tool_def["name"]]
            registry.register(td, fn)
            self._registered_names.append(tool_def["name"])

        self._active = True
        logger.info(
            "DocumentsPlugin activated — %d tools registered.",
            len(self._registered_names),
        )

    async def deactivate(self) -> None:
        """No background tasks to stop; mark as inactive."""
        self._active = False
        logger.info("DocumentsPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        """Return the tool metadata dicts for all document tools."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in DOCUMENTS_TOOLS
        ]

    # ── Dependencies ──────────────────────────────────────────────────────────

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(
            python_packages=[
                "PyMuPDF>=1.23",
                "pymupdf4llm>=0.0.5",
                "pypdf>=3.0",
                "python-pptx>=0.6",
                "python-docx>=1.0",
                "openpyxl>=3.1",
                "fpdf2>=2.7",
                "duckdb>=0.10",
                "matplotlib>=3.5",
                "Pillow>=10.0",
            ]
        )

    def get_config_schema(self) -> dict[str, Any]:
        return {}

    def get_auth_spec(self) -> None:
        return None
