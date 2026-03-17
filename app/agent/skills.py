"""Sprint 14a — Skills System with three-level progressive disclosure (§4.5).

Architecture
------------
Three levels of skill content:
  Level 1 — Index     : always injected in system prompt (``## Available Skills``)
  Level 2 — Instructions: injected for active skills only (``## Active Skills``)
  Level 3 — Resources : fetched on-demand via tool, never auto-loaded

Activation modes
----------------
  ``always``   — skill is always active
  ``trigger``  — activated when user message matches trigger_patterns (regex)
  ``manual``   — only activated via agent tool call or user request

Public API
----------
  SkillDef, SkillResource, SessionSkillState  — data models
  SkillStore                                   — async DB CRUD
  SkillEngine                                  — per-turn resolution logic
  init_skill_store / get_skill_store           — singleton lifecycle
  BUILTIN_SKILLS, BUILTIN_RESOURCES            — 7 built-in skill definitions
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Data Models (§4.5.1) ──────────────────────────────────────────────────────


class SkillDef(BaseModel):
    """Full skill definition stored in the ``skills`` table."""

    skill_id: str = Field(default_factory=lambda: f"skill:{uuid.uuid4().hex[:12]}")
    name: str
    description: str
    version: str = "1.0.0"
    summary: str = ""
    """Level 1: short summary (~20-50 tokens) always shown in skill index."""
    instructions: str = ""
    """Level 2: detailed instructions injected for active skills."""
    required_tools: list[str] = []
    """Tools that must be available for this skill to activate."""
    recommended_tools: list[str] = []
    activation_mode: Literal["always", "trigger", "manual"] = "trigger"
    trigger_patterns: list[str] = []
    """Regex patterns matched against user message (re.IGNORECASE)."""
    trigger_tool_presence: list[str] = []
    """Auto-suggest when one of these tool IDs is enabled on the agent."""
    priority: int = 100
    """Lower = higher priority; used for budget fitting (sorted ascending)."""
    tags: list[str] = []
    author: str = "user"
    is_builtin: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "summary": self.summary,
            "instructions": self.instructions,
            "required_tools": json.dumps(self.required_tools),
            "recommended_tools": json.dumps(self.recommended_tools),
            "activation_mode": self.activation_mode,
            "trigger_patterns": json.dumps(self.trigger_patterns),
            "trigger_tool_presence": json.dumps(self.trigger_tool_presence),
            "priority": self.priority,
            "tags": json.dumps(self.tags),
            "author": self.author,
            "is_builtin": int(self.is_builtin),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SkillDef":
        def _j(key: str, default: Any) -> Any:
            raw = row.get(key)
            if raw is None:
                return default
            if isinstance(raw, (list, dict)):
                return raw
            try:
                return json.loads(raw)
            except Exception:
                return default

        return cls(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            version=row.get("version", "1.0.0"),
            summary=row.get("summary", ""),
            instructions=row.get("instructions", ""),
            required_tools=_j("required_tools", []),
            recommended_tools=_j("recommended_tools", []),
            activation_mode=row.get("activation_mode", "trigger"),
            trigger_patterns=_j("trigger_patterns", []),
            trigger_tool_presence=_j("trigger_tool_presence", []),
            priority=row.get("priority", 100),
            tags=_j("tags", []),
            author=row.get("author", "user"),
            is_builtin=bool(row.get("is_builtin", False)),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else datetime.now(timezone.utc),
        )


class SkillResource(BaseModel):
    """Level 3 reference material for a skill (fetched on-demand)."""

    resource_id: str = Field(default_factory=lambda: f"res:{uuid.uuid4().hex[:12]}")
    skill_id: str
    name: str
    description: str = ""
    content: str
    content_tokens: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "content_tokens": self.content_tokens,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SkillResource":
        return cls(
            resource_id=row["resource_id"],
            skill_id=row["skill_id"],
            name=row["name"],
            description=row.get("description", ""),
            content=row["content"],
            content_tokens=row.get("content_tokens"),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else datetime.now(timezone.utc),
        )


class SessionSkillState(BaseModel):
    """Per-session manual override tracking for skill activation."""

    manually_activated: list[str] = []
    """skill_ids activated by agent or user within session."""
    manually_deactivated: list[str] = []
    """skill_ids deactivated by agent or user within session."""
    last_triggered: dict[str, str] = {}
    """skill_id → ISO datetime of last trigger match."""


# ── Built-in Skill Definitions (§4.5.4) ───────────────────────────────────────

_NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)

BUILTIN_SKILLS: list[SkillDef] = [
    SkillDef(
        skill_id="skill:code_review",
        name="Code Review",
        description="Perform thorough code reviews: identify bugs, security issues, style violations, and suggest improvements.",
        summary="Code review: analyze code for bugs, security issues, style, and correctness. Reads files and provides structured feedback.",
        instructions="""## Code Review Skill

When asked to review code, follow this process:
1. Read the file(s) using `fs_read_file`
2. Analyze for: bugs, security vulnerabilities, performance issues, style violations, missing error handling
3. Structure feedback as: **Summary** → **Critical Issues** → **Suggestions** → **Positives**
4. Be specific: cite line numbers, explain why each issue matters
5. Suggest concrete fixes for every issue identified
6. Rate overall code quality (1-10) with brief justification

Focus on actionable, constructive feedback.""",
        required_tools=["fs_read_file"],
        activation_mode="trigger",
        trigger_patterns=[r"review.*code", r"code.*review", r"PR\s+review", r"pull\s+request.*review", r"check.*code", r"audit.*code"],
        priority=10,
        tags=["development", "quality"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:meeting_notes",
        name="Meeting Notes",
        description="Capture, structure, and store meeting notes with action items and key decisions.",
        summary="Meeting notes: extract key decisions, action items, and attendees from meeting transcripts. Saves structured notes to memory.",
        instructions="""## Meeting Notes Skill

When processing meeting notes or transcripts:
1. Extract: **Attendees**, **Date/Time**, **Agenda Items**, **Key Decisions**, **Action Items** (with owners and deadlines), **Next Meeting**
2. Format as structured markdown with clear sections
3. Highlight action items with owner and deadline
4. Save to memory using `memory_save` with type='task' for action items
5. Ask for clarification on any unclear assignments or deadlines

Always confirm the notes were saved successfully.""",
        required_tools=["memory_save"],
        activation_mode="trigger",
        trigger_patterns=[r"meeting.*notes", r"summarize.*meeting", r"minutes", r"action.*items.*meeting", r"meeting.*summary"],
        priority=20,
        tags=["productivity", "meetings"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:email_drafting",
        name="Email Drafting",
        description="Draft professional emails with proper tone, structure, and etiquette for various contexts.",
        summary="Email drafting: compose professional emails with appropriate tone, structure, subject lines, and follow-up prompts.",
        instructions="""## Email Drafting Skill

When drafting emails:
1. Clarify: recipient relationship, purpose, desired tone (formal/informal), any deadline
2. Structure: Subject line → Greeting → Opening (purpose) → Body → Call to action → Closing
3. Tone guide: formal for clients/executives, semi-formal for colleagues, friendly for close contacts
4. Subject line: specific and action-oriented (avoid vague subjects)
5. Proofread for: grammar, clarity, appropriate length (concise > verbose)
6. Offer alternatives for subject line and closing if appropriate

Ask before sending if `gmail_send` or `email_send` is available.""",
        required_tools=[],
        recommended_tools=["gmail_send", "email_send"],
        activation_mode="trigger",
        trigger_patterns=[r"draft.*email", r"write.*email", r"compose.*email", r"email.*to\s+\w+", r"send.*email"],
        priority=30,
        tags=["communication", "email"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:research",
        name="Research",
        description="Conduct systematic research on topics using web search and content fetching.",
        summary="Research: systematic information gathering via web search and content retrieval. Synthesizes findings into structured reports.",
        instructions="""## Research Skill

When conducting research:
1. Understand the research question — clarify scope if ambiguous
2. Search strategy: use `web_search` with 3-5 diverse queries targeting different aspects
3. Fetch promising sources with `web_fetch` for full content
4. Evaluate sources: recency, credibility, relevance
5. Synthesize findings: **Summary** → **Key Findings** (with citations) → **Conflicting Views** → **Gaps** → **Conclusion**
6. Use inline citations [Source: URL]
7. Distinguish facts from opinions; note confidence levels

Always acknowledge limitations and suggest further research directions.""",
        required_tools=["web_search", "web_fetch"],
        activation_mode="trigger",
        trigger_patterns=[r"research\b", r"find\s+out\s+about", r"investigate\b", r"look\s+into\b", r"what\s+do\s+you\s+know\s+about"],
        priority=40,
        tags=["research", "information"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:data_analysis",
        name="Data Analysis",
        description="Analyze CSV and tabular data: statistics, trends, anomaly detection, and visualization recommendations.",
        summary="Data analysis: open CSV files, run queries, compute statistics, identify trends and anomalies, recommend visualizations.",
        instructions="""## Data Analysis Skill

When analyzing data:
1. Open file with `csv_open` and inspect structure (shape, columns, types)
2. Initial exploration: `csv_query` for head, describe (min/max/mean/std), null counts
3. Analysis plan: what questions does the data answer?
4. Run targeted queries for: distributions, correlations, outliers, time trends
5. Report structure: **Dataset Overview** → **Key Statistics** → **Findings** → **Anomalies** → **Visualization Recommendations** → **Next Steps**
6. Always state assumptions and data limitations

Suggest appropriate chart types for each finding.""",
        required_tools=["csv_open", "csv_query"],
        activation_mode="trigger",
        trigger_patterns=[r"analyze.*data", r"csv.*quer", r"data.*analysis", r"statistics.*on\b", r"summarize.*csv", r"trends.*in\b"],
        priority=50,
        tags=["data", "analytics"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:document_creation",
        name="Document Creation",
        description="Create structured documents, reports, PDFs, and presentations.",
        summary="Document creation: generate structured PDFs, reports, and presentations. Handles formatting, outlines, and multi-section documents.",
        instructions="""## Document Creation Skill

When creating documents:
1. Clarify: document type (report/presentation/PDF), audience, key sections, tone
2. Create a clear outline before writing body content
3. Structure: Title Page → Executive Summary → Table of Contents → Body Sections → Conclusion → Appendix
4. Writing style: clear headings, concise paragraphs, bullet points for lists
5. Use `pdf_create` for PDF documents or `pptx_create` for presentations
6. Include: page numbers, consistent formatting, proper citations if research-based

Always preview structure with user before generating the final document.""",
        required_tools=[],
        recommended_tools=["pdf_create", "pptx_create"],
        activation_mode="trigger",
        trigger_patterns=[r"create.*document", r"generate.*pdf", r"write.*report", r"make.*presentation", r"draft.*report"],
        priority=60,
        tags=["productivity", "documents"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillDef(
        skill_id="skill:task_management",
        name="Task Management",
        description="Manage tasks, todos, deadlines, and reminders using memory tools.",
        summary="Task management: create, track, update, and prioritize tasks and deadlines. Uses memory to persist and recall todos.",
        instructions="""## Task Management Skill

When managing tasks:
1. Capture tasks with: description, deadline (if given), priority (high/medium/low), owner
2. Save to memory: `memory_save` with type='task', include deadline in content
3. Search existing tasks: `memory_search` with 'task' keyword before creating duplicates
4. Prioritization: use Eisenhower matrix (urgent/important) for task ordering
5. Status updates: when marking done, update the memory record
6. Reminders: if deadline within 24h, proactively mention when user returns

Format task lists as: [ ] Pending  [x] Done  [!] Overdue""",
        required_tools=["memory_save", "memory_search"],
        activation_mode="trigger",
        trigger_patterns=[r"\btask\b", r"\btodo\b", r"\bdeadline\b", r"remind\s+me", r"don't\s+forget", r"schedule\b"],
        priority=70,
        tags=["productivity", "tasks"],
        author="system",
        is_builtin=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
]

# Level 3 resources for built-in skills
BUILTIN_RESOURCES: list[SkillResource] = [
    SkillResource(
        resource_id="res:code_review_checklist",
        skill_id="skill:code_review",
        name="Code Review Checklist",
        description="Comprehensive checklist of items to check during code review",
        content="""# Code Review Checklist

## Security
- [ ] No hardcoded credentials/secrets
- [ ] Input validation present
- [ ] No SQL injection vulnerabilities
- [ ] Authentication/authorization checks
- [ ] Sensitive data not logged

## Correctness
- [ ] Edge cases handled (null, empty, boundary values)
- [ ] Error handling for all failure paths
- [ ] Return values checked
- [ ] Async/await used correctly

## Performance
- [ ] No N+1 queries
- [ ] Appropriate data structures
- [ ] Expensive operations cached or deferred
- [ ] Large data sets paginated

## Maintainability
- [ ] Functions have single responsibility
- [ ] Variable names descriptive
- [ ] Complex logic commented
- [ ] No dead code
- [ ] Tests present for new logic
""",
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillResource(
        resource_id="res:research_templates",
        skill_id="skill:research",
        name="Research Report Templates",
        description="Standard templates for research output formatting",
        content="""# Research Report Templates

## Quick Summary Template
**Topic**: [Research Topic]
**Date**: [Date]
**Key Finding**: [1-2 sentence answer]
**Sources**: [3-5 citations]

## Full Report Template
# Research Report: [Topic]

## Executive Summary
[2-3 paragraph overview of findings]

## Background
[Context and why this matters]

## Methodology
[Search strategy, sources used, date range]

## Key Findings
### Finding 1: [Title]
[Details + citation]

### Finding 2: [Title]
[Details + citation]

## Analysis
[Synthesis, patterns, contradictions]

## Conclusion
[Answer to the research question]

## Limitations
[Data gaps, recency issues, bias risks]

## Sources
1. [URL] - [Brief description]
""",
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillResource(
        resource_id="res:email_templates",
        skill_id="skill:email_drafting",
        name="Email Templates",
        description="Templates for common email types",
        content="""# Email Templates

## Follow-up Email
Subject: Following up on [Topic] - [Your Name]

Hi [Name],

I hope this email finds you well. I wanted to follow up on [specific topic/meeting/request].

[1-2 sentences with what you're following up on and any relevant context]

Could you let me know [specific ask or question] by [deadline if applicable]?

Thank you for your time.

Best regards,
[Your Name]

## Meeting Request
Subject: [Topic] - Meeting Request - [Proposed Date]

Hi [Name],

I'd like to discuss [topic] and was hoping we could connect.

I'm available [time slots]. Please let me know what works best for you, or feel free to suggest an alternative time.

Meeting agenda:
- [Item 1] (~X mins)
- [Item 2] (~X mins)

Looking forward to connecting.

Best,
[Your Name]

## Decline / Cannot Attend
Subject: Re: [Original Subject]

Hi [Name],

Thank you for the invitation. Unfortunately, I won't be able to [attend/participate] due to [brief reason].

[If applicable: Could we reschedule to [alternative]? / I'll make sure to review the notes afterward.]

Apologies for any inconvenience.

Best regards,
[Your Name]
""",
        created_at=_NOW,
        updated_at=_NOW,
    ),
    SkillResource(
        resource_id="res:task_management_guide",
        skill_id="skill:task_management",
        name="Task Management Guide",
        description="Prioritization frameworks and best practices",
        content="""# Task Management Guide

## Eisenhower Matrix
Categorize tasks by Urgency × Importance:

| | Urgent | Not Urgent |
|---|---|---|
| **Important** | DO NOW (quadrant 1) | PLAN (quadrant 2) |
| **Not Important** | DELEGATE (quadrant 3) | ELIMINATE (quadrant 4) |

## Task Format Standard
```
Task: [Clear, action-oriented description]
Due: [ISO date or relative: today/tomorrow/this week]
Priority: high | medium | low
Status: pending | in-progress | done | blocked
Tags: [comma-separated]
Notes: [any context]
```

## Productivity Tips
- Break large tasks into subtasks (< 2 hours each)
- Time-box: assign specific time slots
- Daily review: check tasks at start and end of day
- Weekly review: clear backlog, update priorities
- "Two-minute rule": if < 2 min, do it now

## Common Task Types
- **Task**: one-off action
- **Project**: multi-step work towards a goal
- **Recurring**: daily/weekly/monthly repeating
- **Waiting**: blocked on someone else
""",
        created_at=_NOW,
        updated_at=_NOW,
    ),
]


# ── Skill Store (§4.5.7) ──────────────────────────────────────────────────────


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(zip(row.keys(), row))


class SkillStore:
    """Async SQLite CRUD for skills and skill_resources."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── SkillDef CRUD ─────────────────────────────────────────────────────────

    async def create_skill(self, skill: SkillDef) -> SkillDef:
        row = skill.to_row()
        await self._db.execute(
            """
            INSERT INTO skills (
                skill_id, name, description, version, summary,
                instructions, required_tools, recommended_tools,
                activation_mode, trigger_patterns, trigger_tool_presence,
                priority, tags, author, is_builtin, created_at, updated_at
            ) VALUES (
                :skill_id, :name, :description, :version, :summary,
                :instructions, :required_tools, :recommended_tools,
                :activation_mode, :trigger_patterns, :trigger_tool_presence,
                :priority, :tags, :author, :is_builtin, :created_at, :updated_at
            )
            """,
            row,
        )
        await self._db.commit()
        return await self.get_skill(skill.skill_id)

    async def get_skill(self, skill_id: str) -> SkillDef:
        async with self._db.execute(
            "SELECT * FROM skills WHERE skill_id = ?", (skill_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Skill not found: {skill_id}")
        return SkillDef.from_row(_row_to_dict(row))

    async def list_skills(
        self,
        *,
        tags: list[str] | None = None,
        author: str | None = None,
        is_builtin: bool | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SkillDef]:
        clauses: list[str] = []
        params: list[Any] = []
        if is_builtin is not None:
            clauses.append("is_builtin = ?")
            params.append(int(is_builtin))
        if author:
            clauses.append("author = ?")
            params.append(author)
        if q:
            clauses.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        async with self._db.execute(
            f"SELECT * FROM skills {where} ORDER BY priority ASC, name ASC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        skills = [SkillDef.from_row(_row_to_dict(r)) for r in rows]
        # Filter by tags in Python (SQLite JSON array filtering is verbose)
        if tags:
            skills = [s for s in skills if any(t in s.tags for t in tags)]
        return skills

    async def update_skill(self, skill_id: str, updates: dict[str, Any]) -> SkillDef:
        existing = await self.get_skill(skill_id)
        now = datetime.now(timezone.utc).isoformat()
        # Build SET clause from allowed fields
        allowed = {
            "name", "description", "version", "summary", "instructions",
            "required_tools", "recommended_tools", "activation_mode",
            "trigger_patterns", "trigger_tool_presence", "priority", "tags",
            "author",
        }
        set_parts: list[str] = ["updated_at = :updated_at"]
        params: dict[str, Any] = {"skill_id": skill_id, "updated_at": now}
        for key, val in updates.items():
            if key not in allowed:
                continue
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            set_parts.append(f"{key} = :{key}")
            params[key] = val
        if len(set_parts) == 1:
            return existing  # nothing to update
        await self._db.execute(
            f"UPDATE skills SET {', '.join(set_parts)} WHERE skill_id = :skill_id",
            params,
        )
        await self._db.commit()
        return await self.get_skill(skill_id)

    async def delete_skill(self, skill_id: str) -> None:
        await self._db.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
        await self._db.commit()

    async def get_skills_for_agent(self, skill_ids: list[str]) -> list[SkillDef]:
        """Fetch skills by a list of IDs, preserving order."""
        if not skill_ids:
            return []
        placeholders = ",".join("?" * len(skill_ids))
        async with self._db.execute(
            f"SELECT * FROM skills WHERE skill_id IN ({placeholders})",
            skill_ids,
        ) as cur:
            rows = await cur.fetchall()
        by_id = {r["skill_id"]: SkillDef.from_row(_row_to_dict(r)) for r in rows}
        return [by_id[sid] for sid in skill_ids if sid in by_id]

    # ── SkillResource CRUD ────────────────────────────────────────────────────

    async def create_resource(self, resource: SkillResource) -> SkillResource:
        row = resource.to_row()
        await self._db.execute(
            """
            INSERT INTO skill_resources (
                resource_id, skill_id, name, description, content,
                content_tokens, created_at, updated_at
            ) VALUES (
                :resource_id, :skill_id, :name, :description, :content,
                :content_tokens, :created_at, :updated_at
            )
            """,
            row,
        )
        await self._db.commit()
        return await self.get_resource(resource.resource_id)

    async def get_resource(self, resource_id: str) -> SkillResource:
        async with self._db.execute(
            "SELECT * FROM skill_resources WHERE resource_id = ?", (resource_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise KeyError(f"SkillResource not found: {resource_id}")
        return SkillResource.from_row(_row_to_dict(row))

    async def list_resources(self, skill_id: str) -> list[SkillResource]:
        async with self._db.execute(
            "SELECT * FROM skill_resources WHERE skill_id = ? ORDER BY name ASC",
            (skill_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [SkillResource.from_row(_row_to_dict(r)) for r in rows]

    async def update_resource(self, resource_id: str, updates: dict[str, Any]) -> SkillResource:
        now = datetime.now(timezone.utc).isoformat()
        allowed = {"name", "description", "content", "content_tokens"}
        set_parts: list[str] = ["updated_at = :updated_at"]
        params: dict[str, Any] = {"resource_id": resource_id, "updated_at": now}
        for key, val in updates.items():
            if key not in allowed:
                continue
            set_parts.append(f"{key} = :{key}")
            params[key] = val
        if len(set_parts) > 1:
            await self._db.execute(
                f"UPDATE skill_resources SET {', '.join(set_parts)} WHERE resource_id = :resource_id",
                params,
            )
            await self._db.commit()
        return await self.get_resource(resource_id)

    async def delete_resource(self, resource_id: str) -> None:
        await self._db.execute("DELETE FROM skill_resources WHERE resource_id = ?", (resource_id,))
        await self._db.commit()

    # ── init helpers ──────────────────────────────────────────────────────────

    async def seed_builtins(self) -> None:
        """Insert built-in skills/resources if not already present."""
        for skill in BUILTIN_SKILLS:
            async with self._db.execute(
                "SELECT 1 FROM skills WHERE skill_id = ?", (skill.skill_id,)
            ) as cur:
                exists = await cur.fetchone()
            if not exists:
                await self._db.execute(
                    """
                    INSERT INTO skills (
                        skill_id, name, description, version, summary,
                        instructions, required_tools, recommended_tools,
                        activation_mode, trigger_patterns, trigger_tool_presence,
                        priority, tags, author, is_builtin, created_at, updated_at
                    ) VALUES (
                        :skill_id, :name, :description, :version, :summary,
                        :instructions, :required_tools, :recommended_tools,
                        :activation_mode, :trigger_patterns, :trigger_tool_presence,
                        :priority, :tags, :author, :is_builtin, :created_at, :updated_at
                    )
                    """,
                    skill.to_row(),
                )
        for res in BUILTIN_RESOURCES:
            async with self._db.execute(
                "SELECT 1 FROM skill_resources WHERE resource_id = ?", (res.resource_id,)
            ) as cur:
                exists = await cur.fetchone()
            if not exists:
                await self._db.execute(
                    """
                    INSERT INTO skill_resources (
                        resource_id, skill_id, name, description, content,
                        content_tokens, created_at, updated_at
                    ) VALUES (
                        :resource_id, :skill_id, :name, :description, :content,
                        :content_tokens, :created_at, :updated_at
                    )
                    """,
                    res.to_row(),
                )
        await self._db.commit()
        logger.info("Built-in skills seeded")


# ── Skill Engine (§4.5.2) ─────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Fast O(n) token estimate (whitespace split × 1.3)."""
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


class SkillEngine:
    """Per-turn skill resolution: Level 1 index + Level 2 active instructions."""

    def render_skill_index(
        self,
        skills: list[SkillDef],
        budget: int = 500,
    ) -> str:
        """Build Level 1 skill index block (step 4a).

        Returns a ``## Available Skills`` markdown block with all assigned
        skill summaries that fit within ``budget`` tokens.  Skills are
        sorted by priority (ascending = higher priority first).
        """
        if not skills:
            return ""
        sorted_skills = sorted(skills, key=lambda s: s.priority)
        lines: list[str] = ["## Available Skills\n"]
        tokens_used = _estimate_tokens(lines[0])
        included = 0
        for skill in sorted_skills:
            summary_line = f"- **{skill.name}** (`{skill.skill_id}`): {skill.summary}"
            line_tokens = _estimate_tokens(summary_line)
            if tokens_used + line_tokens > budget:
                logger.debug(
                    "Skill index budget reached at %d tokens; dropped %s",
                    tokens_used,
                    skill.skill_id,
                )
                break
            lines.append(summary_line)
            tokens_used += line_tokens
            included += 1
        if included == 0:
            return ""
        return "\n".join(lines)

    def resolve_active_skills(
        self,
        skills: list[SkillDef],
        user_message: str,
        session_state: SessionSkillState,
        agent_tools: list[str],
        budget: int = 1500,
    ) -> tuple[str, list[str]]:
        """Build Level 2 active skill instructions block (step 4b).

        Activation pipeline (in priority order):
          1. ``always`` mode skills
          2. ``trigger`` mode skills with a matching regex pattern
          3. ``trigger_tool_presence`` match (tool enabled on agent)
          4. Manually activated by agent/user within session
        Manually deactivated skills are excluded.
        Required tools check: skip if a required tool is absent.
        Budget fitting: sort by priority, accumulate until budget exceeded.

        Returns
        -------
        (instructions_block: str, active_skill_ids: list[str])
        """
        if not skills:
            return "", []

        manually_deactivated = set(session_state.manually_deactivated)
        manually_activated = set(session_state.manually_activated)

        candidates: list[SkillDef] = []
        seen: set[str] = set()

        def _add(skill: SkillDef) -> None:
            if skill.skill_id not in seen and skill.skill_id not in manually_deactivated:
                seen.add(skill.skill_id)
                candidates.append(skill)

        # Pass 1: always-on
        for skill in skills:
            if skill.activation_mode == "always":
                _add(skill)

        # Pass 2: trigger-match (regex on user message)
        for skill in skills:
            if skill.activation_mode == "trigger":
                for pattern in skill.trigger_patterns:
                    try:
                        if re.search(pattern, user_message, re.IGNORECASE):
                            _add(skill)
                            break
                    except re.error:
                        logger.warning("Invalid trigger regex for %s: %r", skill.skill_id, pattern)

        # Pass 3: trigger_tool_presence — skill suggests itself when enabled tool present
        for skill in skills:
            if skill.trigger_tool_presence:
                if any(t in agent_tools for t in skill.trigger_tool_presence):
                    _add(skill)

        # Pass 4: manually activated in session
        for skill in skills:
            if skill.skill_id in manually_activated:
                _add(skill)

        # Filter: required tools available
        active_tool_set = set(agent_tools)
        filtered = [
            s for s in candidates
            if not s.required_tools or all(t in active_tool_set for t in s.required_tools)
        ]

        # Budget fitting: sort by priority desc, fill until budget
        filtered.sort(key=lambda s: s.priority)
        lines: list[str] = ["## Active Skills\n"]
        header_tokens = _estimate_tokens(lines[0])
        tokens_used = header_tokens
        active_ids: list[str] = []
        included = 0

        for skill in filtered:
            if not skill.instructions:
                continue
            block = f"### {skill.name}\n{skill.instructions}"
            block_tokens = _estimate_tokens(block)
            if tokens_used + block_tokens > budget:
                logger.debug(
                    "Skill instruction budget reached; dropped %s (%d tokens)",
                    skill.skill_id,
                    block_tokens,
                )
                continue  # Try lower-priority skills that might fit
            lines.append(block)
            tokens_used += block_tokens
            active_ids.append(skill.skill_id)
            included += 1

        if included == 0:
            return "", []
        return "\n\n".join(lines), active_ids


# ── Import / Export (§4.5.5) ──────────────────────────────────────────────────


def skill_to_export_dict(skill: SkillDef, resources: list[SkillResource]) -> dict[str, Any]:
    """Serialise a skill to the v1.1 export format."""
    return {
        "version": "1.1",
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "skill_version": skill.version,
        "summary": skill.summary,
        "instructions": skill.instructions,
        "required_tools": skill.required_tools,
        "recommended_tools": skill.recommended_tools,
        "activation_mode": skill.activation_mode,
        "trigger_patterns": skill.trigger_patterns,
        "trigger_tool_presence": skill.trigger_tool_presence,
        "priority": skill.priority,
        "tags": skill.tags,
        "author": skill.author,
        "resources": [
            {
                "resource_id": r.resource_id,
                "name": r.name,
                "description": r.description,
                "content": r.content,
            }
            for r in resources
        ],
    }


def skill_from_import_dict(data: dict[str, Any]) -> tuple[SkillDef, list[SkillResource]]:
    """Parse a v1.0 or v1.1 import payload into (SkillDef, resources).

    v1.0 backward compat: ``prompt_fragment`` → ``instructions`` + ``summary``.
    """
    fmt_version = data.get("version", "1.0")
    now = datetime.now(timezone.utc)

    # v1.0 → v1.1 migration
    if fmt_version == "1.0":
        prompt_fragment = data.get("prompt_fragment", "")
        instructions = data.get("instructions", prompt_fragment)
        summary = data.get("summary", prompt_fragment[:200] if prompt_fragment else "")
    else:
        instructions = data.get("instructions", "")
        summary = data.get("summary", "")

    skill_id = data.get("skill_id") or f"skill:{uuid.uuid4().hex[:12]}"
    skill = SkillDef(
        skill_id=skill_id,
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("skill_version", "1.0.0"),
        summary=summary,
        instructions=instructions,
        required_tools=data.get("required_tools", []),
        recommended_tools=data.get("recommended_tools", []),
        activation_mode=data.get("activation_mode", "trigger"),
        trigger_patterns=data.get("trigger_patterns", []),
        trigger_tool_presence=data.get("trigger_tool_presence", []),
        priority=data.get("priority", 100),
        tags=data.get("tags", []),
        author=data.get("author", "user"),
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )

    resources: list[SkillResource] = []
    for r in data.get("resources", []):
        resources.append(SkillResource(
            resource_id=r.get("resource_id") or f"res:{uuid.uuid4().hex[:12]}",
            skill_id=skill_id,
            name=r["name"],
            description=r.get("description", ""),
            content=r["content"],
            created_at=now,
            updated_at=now,
        ))

    return skill, resources


# ── Tool Groups (§4.5.8) ──────────────────────────────────────────────────────


TOOL_GROUPS: dict[str, dict[str, Any]] = {
    "file_tools": {
        "group_id": "file_tools",
        "name": "File Tools",
        "description": "Read, write, and manage local files and directories",
        "tools": ["fs_read_file", "fs_write_file", "fs_list_dir", "fs_delete_file", "fs_move_file"],
    },
    "web_tools": {
        "group_id": "web_tools",
        "name": "Web Tools",
        "description": "Search the web and fetch web page content",
        "tools": ["web_search", "web_fetch"],
    },
    "code_tools": {
        "group_id": "code_tools",
        "name": "Code Execution",
        "description": "Execute Python and shell code in a sandboxed environment",
        "tools": ["code_exec_python", "code_exec_shell"],
    },
    "vision_tools": {
        "group_id": "vision_tools",
        "name": "Vision Tools",
        "description": "Analyze and process images",
        "tools": ["vision_describe", "vision_ocr"],
    },
    "memory_tools": {
        "group_id": "memory_tools",
        "name": "Memory Tools",
        "description": "Save, search, and manage long-term memories",
        "tools": ["memory_save", "memory_search", "memory_list", "memory_update", "memory_forget", "memory_pin", "memory_unpin"],
    },
    "entity_tools": {
        "group_id": "entity_tools",
        "name": "Entity Tools",
        "description": "Create and manage people, places, organizations, and other entities",
        "tools": ["entity_create", "entity_update", "entity_search", "entity_merge"],
    },
    "session_tools": {
        "group_id": "session_tools",
        "name": "Session Tools",
        "description": "Create and manage sub-agent sessions and branches",
        "tools": ["session_create", "session_send", "session_branch"],
    },
    "knowledge_tools": {
        "group_id": "knowledge_tools",
        "name": "Knowledge Tools",
        "description": "Query knowledge vaults and knowledge sources",
        "tools": ["knowledge_search", "knowledge_list_sources"],
    },
    "skill_tools": {
        "group_id": "skill_tools",
        "name": "Skill Tools",
        "description": "List, activate, and use agent skills",
        "tools": ["skill_list", "skill_search", "skill_activate", "skill_deactivate", "skill_get_instructions", "skill_list_resources", "skill_read_resource"],
    },
}


# ── Singleton lifecycle ───────────────────────────────────────────────────────

_skill_store: SkillStore | None = None
_skill_engine: SkillEngine | None = None


def init_skill_store(db: aiosqlite.Connection) -> SkillStore:
    global _skill_store, _skill_engine
    _skill_store = SkillStore(db)
    _skill_engine = SkillEngine()
    return _skill_store


def get_skill_store() -> SkillStore:
    if _skill_store is None:
        raise RuntimeError("SkillStore not initialised — call init_skill_store() first")
    return _skill_store


def get_skill_engine() -> SkillEngine:
    if _skill_engine is None:
        raise RuntimeError("SkillEngine not initialised — call init_skill_store() first")
    return _skill_engine
