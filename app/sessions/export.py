"""Session transcript export (§13.4, Sprint 14b D6).

Supports Markdown, JSON, and PDF output.

Usage::

    exporter = SessionExporter(session_store, message_store)
    md = await exporter.export_markdown(session_id, opts)
    pdf_bytes = await exporter.export_pdf(session_id, opts)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Export options ────────────────────────────────────────────────────────────


@dataclass
class ExportOptions:
    """Query-parameter flags for transcript export (§13.4)."""

    include_tool_calls: bool = False
    include_system_messages: bool = False
    include_costs: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _role_label(role: str) -> str:
    return {"user": "User", "assistant": "Assistant", "system": "System", "tool": "Tool"}.get(
        role, role.capitalize()
    )


def _format_message_md(msg: Any, opts: ExportOptions) -> str:
    """Render one message as a Markdown block."""
    if msg.role == "system" and not opts.include_system_messages:
        return ""
    if msg.role == "tool" and not opts.include_tool_calls:
        return ""

    lines: list[str] = []
    ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(msg.created_at, "strftime") else str(msg.created_at)
    lines.append(f"### {_role_label(msg.role)}  *{ts}*")

    content = (msg.content or "").strip()
    if content:
        lines.append(content)

    if opts.include_tool_calls and msg.tool_calls:
        tc_json = msg.tool_calls if isinstance(msg.tool_calls, list) else []
        for tc in tc_json:
            lines.append(f"\n```json\n{json.dumps(tc, indent=2)}\n```")

    if opts.include_costs and (msg.input_tokens or msg.output_tokens):
        cost_parts: list[str] = []
        if msg.input_tokens is not None:
            cost_parts.append(f"in={msg.input_tokens}")
        if msg.output_tokens is not None:
            cost_parts.append(f"out={msg.output_tokens}")
        if msg.model:
            cost_parts.append(f"model={msg.model}")
        lines.append(f"\n*Tokens: {', '.join(cost_parts)}*")

    return "\n\n".join(part for part in lines if part) + "\n\n---\n"


# ── SessionExporter ───────────────────────────────────────────────────────────


class SessionExporter:
    """Generates Markdown, JSON, and PDF transcripts from session messages."""

    def __init__(self, session_store: Any, message_store: Any) -> None:
        self._ss = session_store
        self._ms = message_store

    # ── Markdown ──────────────────────────────────────────────────────────

    async def export_markdown(self, session_id: str, opts: ExportOptions) -> str:
        session = await self._ss.get(session_id)
        messages = await self._ms.list_by_session(
            session_id,
            limit=5000,
            active_only=True,
        )

        title = session.title or session.session_key
        lines: list[str] = [
            f"# {title}",
            "",
            f"**Session key:** `{session.session_key}`  ",
            f"**Agent:** `{session.agent_id}`  ",
            f"**Created:** {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**Messages:** {len(messages)}",
            "",
            "---",
            "",
        ]

        for msg in messages:
            block = _format_message_md(msg, opts)
            if block:
                lines.append(block)

        return "\n".join(lines)

    # ── JSON ──────────────────────────────────────────────────────────────

    async def export_json(self, session_id: str, opts: ExportOptions) -> dict[str, Any]:
        from app.sessions.models import Session

        session = await self._ss.get(session_id)
        messages = await self._ms.list_by_session(
            session_id,
            limit=5000,
            active_only=True,
        )

        def _msg_to_dict(msg: Any) -> dict[str, Any]:
            d: dict[str, Any] = {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if hasattr(msg.created_at, "isoformat") else str(msg.created_at),
            }
            if opts.include_tool_calls:
                d["tool_calls"] = msg.tool_calls
                d["tool_call_id"] = msg.tool_call_id
            if opts.include_costs:
                d["model"] = msg.model
                d["input_tokens"] = msg.input_tokens
                d["output_tokens"] = msg.output_tokens
            return d

        filtered = [
            _msg_to_dict(m) for m in messages
            if not (m.role == "system" and not opts.include_system_messages)
            and not (m.role == "tool" and not opts.include_tool_calls)
        ]

        return {
            "session_key": session.session_key,
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
            "message_count": len(filtered),
            "messages": filtered,
        }

    # ── PDF ───────────────────────────────────────────────────────────────

    async def export_pdf(self, session_id: str, opts: ExportOptions) -> bytes:
        """Generate a PDF transcript using fpdf2.

        Runs synchronous fpdf2 calls in a thread pool to avoid blocking.
        """
        md = await self.export_markdown(session_id, opts)
        return await asyncio.to_thread(self._render_pdf, md)

    def _render_pdf(self, markdown_text: str) -> bytes:
        """Synchronous PDF rendering via fpdf2."""
        try:
            from fpdf import FPDF
        except ImportError:
            logger.error("fpdf2 is not installed. Run: pip install fpdf2")
            raise RuntimeError("fpdf2 not installed")

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_margins(15, 15, 15)
        pdf.set_font("Helvetica", size=10)
        page_w = pdf.w - pdf.l_margin - pdf.r_margin

        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if line.startswith("### "):
                pdf.set_font("Helvetica", style="B", size=11)
                pdf.multi_cell(page_w, 6, text=line[4:])
                pdf.set_font("Helvetica", size=10)
            elif line.startswith("## "):
                pdf.set_font("Helvetica", style="B", size=13)
                pdf.multi_cell(page_w, 7, text=line[3:])
                pdf.set_font("Helvetica", size=10)
            elif line.startswith("# "):
                pdf.set_font("Helvetica", style="B", size=16)
                pdf.multi_cell(page_w, 9, text=line[2:])
                pdf.set_font("Helvetica", size=10)
            elif line == "---":
                pdf.ln(2)
                x0 = pdf.l_margin
                pdf.set_draw_color(180, 180, 180)
                pdf.line(x0, pdf.get_y(), x0 + page_w, pdf.get_y())
                pdf.ln(2)
            elif line == "":
                pdf.ln(3)
            else:
                # Strip basic markdown emphasis for plain rendering
                clean = line.replace("**", "").replace("*", "").replace("`", "")
                pdf.multi_cell(page_w, 5, text=clean)

        return bytes(pdf.output())
