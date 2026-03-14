# Sprint 14a — Skills System & Soul Editor

**Phase**: 6 – Polish (I)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-48, BS-49

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Implement the skills system with three-level progressive disclosure (reusable agent capabilities with auto-attach and on-demand reference material) and the soul editor with LLM-assisted setup. By sprint end, agents can discover, activate, and use skills with intelligent prompt injection, and users can configure agent personality through an interactive editor.

---

## Spec References

| Section | Topic |
|---------|-------|
| §4.5.0 | Three-level progressive disclosure overview (Level 1 index, Level 2 instructions, Level 3 resources) |
| §4.5.1 | `SkillDef` data model (`summary`, `instructions`, `required_tools`, `trigger_patterns`, `priority`) + `SkillResource` model |
| §4.5.2 | Skill activation & loading (Step 4a: skill index, Step 4b: skill instructions, agent-initiated loading) |
| §4.5.3 | Skill assignment (agent ↔ skill binding, auto-suggest) |
| §4.5.4 | Built-in skills (7 starter skills with Level 1 summaries and Level 3 resources) |
| §4.5.5 | Skill CRUD API, import/export (JSON/YAML v1.1 format with resources) |
| §4.5.6 | Agent skill tools — 7 tools: `skill_list`, `skill_search`, `skill_activate`, `skill_deactivate`, `skill_get_instructions`, `skill_list_resources`, `skill_read_resource` |
| §4.5.7 | Skill store: `skills` + `skill_resources` SQLite tables |
| §4.5.8 | Tool groups table with enable/disable per agent |
| §4.1a | Soul editor + LLM-assisted soul generation |

---

## Prerequisites

- Requires Sprint 13 deliverables and the Phase 5 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Skills System (Three-Level Progressive Disclosure)
- `app/agent/skills.py` — full skill engine per §4.5:
  - **Data models** (§4.5.1):
    - `SkillDef` model: `skill_id, name, description, version, summary (Level 1), instructions (Level 2), required_tools, recommended_tools, activation_mode, trigger_patterns, trigger_tool_presence, priority, tags, author, is_builtin`
    - `SkillResource` model: `resource_id, skill_id, name, description, content, content_tokens` (Level 3 reference material)
    - `SessionSkillState` for per-session manual override tracking
  - **Three-level prompt injection** (§4.5.0, §4.5.2):
    - Level 1 — Skill Index: all assigned skill summaries always in system prompt (`## Available Skills`)
    - Level 2 — Instructions: loaded for active skills only (`## Active Skills`), via always/trigger/manual modes
    - Level 3 — Resources: fetched on-demand via `skill_read_resource` tool (never auto-loaded)
  - **Per-turn skill resolution** (§4.5.2):
    - Step 4a: render skill index for all assigned skills (budget: `skill_index_budget`, default 500 tokens)
    - Step 4b: collect always-on → trigger-match against user message → include manual/agent-requested → budget-fit (`skill_instruction_budget`, default 1500 tokens) → tool availability check
  - **Agent-initiated loading**: agent can call `skill_get_instructions` for one-off reference or `skill_activate` for session-wide injection
  - Auto-suggest: when tool group enabled, suggest matching skills (§4.5.3)
  - 7 built-in skills with Level 1 summaries and Level 3 resources where applicable (§4.5.4): code_review, meeting_notes, email_drafting, research, data_analysis, document_creation, task_management
  - Skill store: `skills` + `skill_resources` SQLite tables (§4.5.7)
  - Skill CRUD API + resource CRUD API + agent assignment API + import/export as JSON/YAML v1.1 (§4.5.5)
  - Agent tools — 7 tools (§4.5.6): `skill_list`, `skill_search`, `skill_activate`, `skill_deactivate`, `skill_get_instructions`, `skill_list_resources`, `skill_read_resource`
  - Tool groups table with enable/disable per agent (§4.5.8)
- Frontend: skill manager (list, create, edit with summary/instructions/resources tabs, assign to agents, import/export)

**Acceptance**: Create skill with summary + instructions + resources → assign to agent → Level 1 summary appears in every prompt → trigger pattern matches user message → Level 2 instructions injected within budget → agent calls `skill_read_resource` → Level 3 content returned as tool result → agent uses skill-specific instructions + reference material. Manual activate/deactivate works within session. Agent can proactively load instructions via `skill_get_instructions`. Import/export v1.1 round-trips correctly (including resources). Backward-compatible import of v1.0 payloads.

### D2: Soul Editor
- `app/agent/soul_editor.py` — LLM-assisted soul configuration:
  - Interactive soul setup: user describes desired personality → LLM generates SoulConfig
  - Soul preview: show generated system prompt before saving
  - Manual editor: direct editing of soul fields (personality, tone, expertise, boundaries)
  - Version history: track soul config changes over time
- Frontend: soul editor page with interactive setup wizard + manual editing

**Acceptance**: User describes personality → LLM generates soul → preview → save. Manual editing works. History tracked.

---

## Tasks

### Backend — Skills (Three-Level Progressive Disclosure)
- [ ] Create `app/agent/skills.py` — `SkillDef` model + `SkillResource` model + `SessionSkillState` model (§4.5.1)
- [ ] Level 1 skill index renderer: compile all assigned skill summaries into `## Available Skills` block (§4.5.2 step 4a)
- [ ] Level 2 instructions loader: always-on → trigger-match → manual/agent-requested → budget-fit → tool-check (§4.5.2 step 4b)
- [ ] Built-in skill definitions with Level 1 summaries and Level 3 resources (7 starter skills per §4.5.4)
- [ ] `skills` + `skill_resources` SQLite tables + Alembic migration (§4.5.7)
- [ ] Skill CRUD API + resource CRUD API + agent assignment API (§4.5.5)
- [ ] Import/export endpoints (JSON/YAML v1.1 format with resources) + clone endpoint + v1.0 backward compat (§4.5.5)
- [ ] Agent tools: `skill_list`, `skill_search`, `skill_activate`, `skill_deactivate`, `skill_get_instructions`, `skill_list_resources`, `skill_read_resource` (§4.5.6)
- [ ] Integration with prompt assembly step 4a (index) + step 4b (instructions): trigger matching + dual-budget fitting (§4.3a, §4.5.2)

### Backend — Soul Editor
- [ ] Create `app/agent/soul_editor.py` — LLM-assisted generation
- [ ] Soul version history
- [ ] Soul preview (render full system prompt from SoulConfig)

### Frontend
- [ ] Skill manager page (with summary/instructions/resources editor tabs)
- [ ] Soul editor page (interactive + manual)

### Tests
- [ ] `tests/unit/test_skills.py` — skill CRUD, three-level loading (Level 1 index always present, Level 2 on activation, Level 3 via tool), trigger matching (3 activation modes), dual-budget fitting (index + instructions), import/export v1.1 round-trip + v1.0 compat, agent tools (all 7), resource CRUD
- [ ] `tests/unit/test_soul_editor.py` — LLM generation, version history, preview

---

## Testing Requirements

- Skills: Level 1 summaries always present in prompt for all assigned skills. Trigger pattern matches → Level 2 instructions injected. No match → Level 1 summary only. Agent calls `skill_get_instructions` → instructions returned as tool result. Agent calls `skill_read_resource` → Level 3 content returned. Manual activate/deactivate works. Skill index budget exceeded → low-priority summaries dropped. Instruction budget exceeded → low-priority instructions dropped. Missing required tools → skill skipped. Import/export v1.1 round-trips with resources. v1.0 import backward-compatible.
- Soul editor: describe personality → LLM generates soul → preview correct → save → soul config updated. Version history shows changes.

---

## Definition of Done

- [ ] Skills system with three-level progressive disclosure: Level 1 index, Level 2 instructions, Level 3 resources, 3 activation modes, trigger matching, 7 built-in skills, 7 agent tools
- [ ] Soul editor with LLM-assisted setup + manual editing + version history
- [ ] All tests pass

---

## Risks & Notes

- **Skills system is the most complex deliverable in the Polish phase**: three-level loading, dual-budget fitting, trigger matching, 7 agent tools, import/export with backward compatibility. Allow extra time for edge cases in budget fitting and trigger resolution.
- **Soul editor LLM call**: needs a working agent/provider from Phase 2 to generate souls. If provider is down, manual editing still works.
