"""Sprint 14a — Soul Editor: LLM-assisted soul generation + version history (§4.1a).

Public API
----------
  SoulVersion               — version history record
  SoulEditor                — async soul editing, generation, preview, history
  soul_config_from_description — LLM-assisted generation (uses active provider)
  init_soul_editor / get_soul_editor — singleton lifecycle

Soul Editor Endpoints (registered in skills.py router for §4.1a):
  POST /api/agents/{id}/soul/generate  — LLM-assisted generation
  POST /api/agents/{id}/soul/preview   — render full system prompt from soul
  GET  /api/agents/{id}/soul/history   — version history
  POST /api/agents/{id}/soul/restore/{version_num} — restore a version
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── SoulVersion model ─────────────────────────────────────────────────────────


class SoulVersion(BaseModel):
    """One entry in the soul version history table."""

    version_id: str = Field(default_factory=lambda: f"sv:{uuid.uuid4().hex[:12]}")
    agent_id: str
    version_num: int
    soul_json: str
    """JSON-serialised SoulConfig."""
    change_note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "agent_id": self.agent_id,
            "version_num": self.version_num,
            "soul_json": self.soul_json,
            "change_note": self.change_note,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SoulVersion":
        return cls(
            version_id=row["version_id"],
            agent_id=row["agent_id"],
            version_num=row["version_num"],
            soul_json=row["soul_json"],
            change_note=row.get("change_note", ""),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
        )


# ── SoulEditor ────────────────────────────────────────────────────────────────


class SoulEditor:
    """Manages soul configuration history and LLM-assisted generation."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Version history ───────────────────────────────────────────────────────

    async def save_version(
        self,
        agent_id: str,
        soul_json: str,
        change_note: str = "",
    ) -> SoulVersion:
        """Append a new soul version to history; returns the saved version."""
        # Get next version number
        async with self._db.execute(
            "SELECT COALESCE(MAX(version_num), 0) FROM soul_versions WHERE agent_id = ?",
            (agent_id,),
        ) as cur:
            row = await cur.fetchone()
        next_num = (row[0] or 0) + 1

        version = SoulVersion(
            agent_id=agent_id,
            version_num=next_num,
            soul_json=soul_json,
            change_note=change_note,
        )
        await self._db.execute(
            """
            INSERT INTO soul_versions (version_id, agent_id, version_num, soul_json, change_note, created_at)
            VALUES (:version_id, :agent_id, :version_num, :soul_json, :change_note, :created_at)
            """,
            version.to_row(),
        )
        await self._db.commit()
        return version

    async def list_versions(self, agent_id: str, limit: int = 50) -> list[SoulVersion]:
        """Return soul versions newest-first."""
        async with self._db.execute(
            "SELECT * FROM soul_versions WHERE agent_id = ? ORDER BY version_num DESC LIMIT ?",
            (agent_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [SoulVersion.from_row(dict(zip(r.keys(), r))) for r in rows]

    async def get_version(self, agent_id: str, version_num: int) -> SoulVersion:
        """Fetch a specific soul version."""
        async with self._db.execute(
            "SELECT * FROM soul_versions WHERE agent_id = ? AND version_num = ?",
            (agent_id, version_num),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Soul version {version_num} not found for agent {agent_id}")
        return SoulVersion.from_row(dict(zip(row.keys(), row)))

    # ── LLM-assisted generation ───────────────────────────────────────────────

    async def generate_soul(
        self,
        description: str,
        agent_id: str | None = None,
        *,
        provider_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Generate a SoulConfig using an LLM from a personality description.

        Returns a dict of SoulConfig field suggestions (not yet saved).
        Falls back to a structured template if no LLM provider is available.
        """
        prompt = _build_generation_prompt(description)
        try:
            soul_fields = await _call_llm_generate(prompt, provider_id=provider_id, model=model)
        except Exception as exc:
            logger.warning("LLM soul generation failed, using fallback: %s", exc)
            soul_fields = _fallback_generation(description)
        return soul_fields

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview_soul(self, soul_data: dict[str, Any]) -> str:
        """Render a full system prompt from soul field data (preview before saving)."""
        from app.agent.models import SoulConfig
        from app.agent.soul import render_soul_prompt
        soul = SoulConfig(**soul_data)
        return render_soul_prompt(soul, user_name="[user]", skill_index="", active_skills="", memory="", tools="[tools]")


# ── LLM helpers ───────────────────────────────────────────────────────────────


def _build_generation_prompt(description: str) -> str:
    # TD-176: Sanitize description to reduce prompt injection risk
    import re
    # Remove instruction-like patterns (lines starting with "ignore", "system:", etc.)
    sanitized = re.sub(
        r'(?mi)^(ignore|system:|assistant:|you must|override|forget).*$',
        '',
        description,
    ).strip()
    # Truncate to reasonable length
    sanitized = sanitized[:2000]
    return f"""You are a soul configuration generator for an AI assistant system.
Given a description of a desired AI personality, generate a structured configuration.

Personality description:
{sanitized}

Return ONLY a JSON object with these fields (no explanation, no markdown fences):
{{
  "persona": "<2-4 sentence description of the agent's identity, personality, and purpose>",
  "tone": "<one of: professional, casual, friendly, formal, custom>",
  "verbosity": "<one of: concise, balanced, detailed>",
  "language": "en",
  "emoji_usage": "<one of: none, minimal, normal>",
  "prefer_markdown": <true or false>,
  "prefer_lists": <true or false>,
  "instructions": ["<rule 1>", "<rule 2>", "<rule 3>"],
  "refuse_topics": ["<topic if any>"]
}}"""


async def _call_llm_generate(
    prompt: str,
    *,
    provider_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Call an LLM provider and parse the JSON response."""
    import json
    from app.providers.registry import get_registry
    from app.providers.base import Message

    registry = get_registry()
    if provider_id:
        provider = registry.get(provider_id)
    else:
        providers = registry.list_available()
        if not providers:
            raise RuntimeError("No LLM providers available")
        provider = providers[0]

    messages = [Message(role="user", content=prompt)]
    response_parts: list[str] = []

    target_model = model or ""
    async for chunk in provider.stream_completion(messages, model=target_model, tools=[]):
        if chunk.content:
            response_parts.append(chunk.content)

    raw = "".join(response_parts).strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    return json.loads(raw)


def _fallback_generation(description: str) -> dict[str, Any]:
    """Structured fallback when LLM is unavailable."""
    # Extract tone hints from description
    desc_lower = description.lower()
    tone = "friendly"
    if any(w in desc_lower for w in ["professional", "formal", "corporate", "business"]):
        tone = "professional"
    elif any(w in desc_lower for w in ["casual", "relaxed", "fun"]):
        tone = "casual"

    return {
        "persona": f"I am an AI assistant configured as: {description}",
        "tone": tone,
        "verbosity": "balanced",
        "language": "en",
        "emoji_usage": "minimal",
        "prefer_markdown": True,
        "prefer_lists": False,
        "instructions": [
            "Be helpful, accurate, and concise.",
            "Ask for clarification when the request is ambiguous.",
            "Acknowledge limitations honestly.",
        ],
        "refuse_topics": [],
    }


# ── Singleton lifecycle ───────────────────────────────────────────────────────

_soul_editor: SoulEditor | None = None


def init_soul_editor(db: aiosqlite.Connection) -> SoulEditor:
    global _soul_editor
    _soul_editor = SoulEditor(db)
    return _soul_editor


def get_soul_editor() -> SoulEditor:
    if _soul_editor is None:
        raise RuntimeError("SoulEditor not initialised — call init_soul_editor() first")
    return _soul_editor
