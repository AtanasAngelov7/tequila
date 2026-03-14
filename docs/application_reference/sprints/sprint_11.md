# Sprint 11 — Memory III: Memory Tools, Lifecycle & Knowledge Graph

**Phase**: 4 – Memory & Knowledge (III) (**Phase Gate Sprint**)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-29, BS-30, BS-31, BS-32, BS-33

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Complete the memory system: give the agent explicit memory tools (save, update, forget, search, pin), implement memory lifecycle management (decay, consolidation, archival), memory audit trail, and the knowledge graph with visualization. By sprint end, the agent can deliberately manage its own memory, old memories decay naturally, and users can explore the entity graph visually.

---

## Spec References

| Section | Topic |
|---------|-------|
| §5.7 | Agent memory tools (memory_save, memory_update, memory_forget, memory_search, memory_list, memory_pin, entity_create, entity_merge, entity_update) |
| §5.8 | Memory lifecycle manager (decay calculation, consolidation: merge, summarize, archive, orphan report) |
| §5.9 | Memory audit trail (memory_events table, history API, UI timeline) |
| §5.11 | Knowledge graph (edge store, graph API, entity-centric edges, semantic similarity edge builder, visualization UI) |
| §5.12 | In-session compression (message summarization, token budget management) |
| §20.5 | Background task safety (timestamp-gated writes, chunked bulk operations) |

> **Note on §5.12 — In-Session Compression**: Sprint 07 built the core compression strategies (`summarize_old`, `drop_tool_results`, `trim_oldest`) in `app/agent/context.py` under §4.7. This sprint extends compression to be **memory-aware**: before summarizing old messages, run the extraction pipeline (S10) to preserve extractable information, and use memory importance scores to influence what gets preserved vs. trimmed during compression.

---

## Prerequisites

- Requires Sprint 10 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Agent Memory Tools
- `app/tools/builtin/memory.py` — tools for explicit memory management:
  - `memory_save(type, subject, content, confidence?, entities?)` → create memory record
  - `memory_update(memory_id, updates)` → modify existing memory
  - `memory_forget(memory_id, reason?)` → soft-delete (mark forgotten, keep audit trail)
  - `memory_search(query, type?, top_k?)` → semantic search over memories
  - `memory_list(type?, entity_id?, limit?)` → list memories with filters
  - `memory_pin(memory_id, pinned: bool)` → pin/unpin memory (pinned = always recalled)
  - `entity_create(name, type, aliases?)` → create new entity
  - `entity_merge(source_id, target_id)` → merge two entities (alias + relink memories)
  - `entity_update(entity_id, updates)` → update entity metadata
- Safety: `memory_save`, `memory_update`, `memory_pin`, `entity_create/merge/update` = `side_effect`; `memory_search`, `memory_list` = `read_only`; `memory_forget` = `destructive`

**Acceptance**: Agent saves, searches, updates, forgets, pins memories via tools. Entity management tools work.

### D2: Memory Lifecycle Manager
- `app/memory/lifecycle.py` — background lifecycle processes:
  - **Decay calculation**: run periodically (default: daily), reduce importance_score based on time since last access + initial confidence
  - **Consolidation**:
    - `merge`: detect near-duplicate memories (high embedding similarity) → merge into one
    - `summarize`: group related low-importance memories → LLM summarize into single higher-level memory
    - `archive`: move memories below importance threshold to archive (excluded from recall, visible in explorer)
    - `orphan report`: detect memories not linked to any entity → flag for review
  - Configurable: decay rate, consolidation threshold, archive threshold, run schedule
- Scheduler integration: register as periodic task (cron-like)

**Acceptance**: After time, low-importance memories decay. Similar memories merge. Very old → archived. Orphans flagged.

### D3: Memory Audit Trail
- `app/memory/audit.py` — track all memory changes:
  - `memory_events` table: `event_id, memory_id, event_type, before_snapshot, after_snapshot, source, timestamp`
  - Event types: `created`, `updated`, `forgotten`, `merged`, `archived`, `consolidated`, `pinned`, `unpinned`, `decayed`
  - Source tracking: which session/tool/pipeline triggered the change
- API:
  - `GET /api/memories/{id}/history` — event timeline for a memory
  - `GET /api/memory-events` — global event feed (paginated)
- Migration: `memory_events` table

**Acceptance**: Every memory change logged. History API returns full timeline. Source attribution correct.

### D4: Knowledge Graph
- `app/knowledge/graph.py` — knowledge graph implementation:
  - `Edge` model: `source_entity_id, target_entity_id, relation_type, weight, metadata, created_at`
  - Relation types: `mentioned_with`, `related_to`, `part_of`, `works_at`, `knows`, `similar_to`
  - Edge creation: from extraction pipeline (S10 step 6), entity tools, automatic similarity
  - **Semantic similarity edge builder**: periodically compute entity embedding similarity → create `similar_to` edges above threshold
  - Graph queries:
    - `GET /api/graph` — full graph (nodes + edges, paginated)
    - `GET /api/graph/entity/{id}` — ego graph (entity + N-hop neighbors)
    - `GET /api/graph/path/{from_id}/{to_id}` — shortest path between entities
  - Graph used by recall pipeline (S10): traverse entity neighbors to find related memories

**Acceptance**: Entities connected by typed edges. Ego graph returns entity's neighborhood. Similarity edges auto-generated.

### D5: Knowledge Graph UI
- Frontend graph visualization:
  - Force-directed graph (D3.js or vis.js) embedded in memory explorer
  - Entity nodes: sized by memory count, colored by type
  - Edge display: labeled by relation type, thickness by weight
  - Ego graph mode: click entity → show its neighborhood (configurable depth)
  - Filters: by entity type, relation type, minimum weight
  - Live updates: new entities/edges appear without page reload (WS events)
  - Click node → show entity detail + linked memories sidebar

**Acceptance**: Graph renders entities and edges. Click entity → ego graph + memories. Filters work. Live updates.

---

## Tasks

### Backend — Memory Tools
- [ ] Create `app/tools/builtin/memory.py` with all 9 tools
- [ ] Register tools with correct safety classifications
- [ ] Integrate with memory store and entity store from S09
- [ ] Entity merge: re-link all memories, merge aliases, delete source entity

### Backend — Lifecycle Manager
- [ ] Create `app/memory/lifecycle.py`
- [ ] Implement decay calculation (time-based, access-based)
- [ ] Implement consolidation: merge (embedding similarity threshold)
- [ ] Implement consolidation: summarize (LLM grouping)
- [ ] Implement consolidation: archive (below threshold → archive)
- [ ] Implement orphan detection and report
- [ ] Register as periodic task (scheduler integration)

### Backend — Audit Trail
- [ ] Create `app/memory/audit.py`
- [ ] Migration: memory_events table
- [ ] Hook all memory operations to emit events
- [ ] History API and global event feed endpoints

### Backend — Knowledge Graph
- [ ] Create `app/knowledge/graph.py` — Edge model + store
- [ ] Graph query endpoints (full, ego, path)
- [ ] Semantic similarity edge builder (periodic)
- [ ] Integration with recall pipeline (entity graph traversal)

### Frontend — Memory Explorer
- [ ] Memory list with type filters, search, sort by recency/importance
- [ ] Memory detail view with edit, pin, forget actions
- [ ] Memory timeline (audit trail visualization)

### Frontend — Knowledge Graph
- [ ] Force-directed graph visualization (D3.js or vis.js)
- [ ] Entity nodes: color by type, size by memory count
- [ ] Edge rendering: labels, thickness by weight
- [ ] Ego graph mode (click → zoom to neighborhood)
- [ ] Filter controls (entity type, relation type, weight)
- [ ] Live updates via WebSocket events
- [ ] Click node → entity detail + memories sidebar

### Tests
- [ ] `tests/unit/test_memory_tools.py` — all 9 tools
- [ ] `tests/unit/test_lifecycle.py` — decay, merge, summarize, archive, orphan
- [ ] `tests/unit/test_memory_audit.py` — event creation, history query
- [ ] `tests/unit/test_knowledge_graph.py` — edge CRUD, ego graph, path
- [ ] `tests/integration/test_memory_lifecycle.py` — create → decay → archive cycle
- [ ] `tests/integration/test_graph_recall.py` — entity graph traversal improves recall

---

## Testing Requirements

- Memory tools: agent saves memory → searches → finds it. Forgets → excluded from recall. Pin → always recalled.
- Lifecycle: create memories → wait/simulate time → decay runs → low-importance archived. Similar → merged.
- Audit: create/update/forget memory → history shows all events with correct types.
- Graph: 5 entities with edges → ego graph returns correct neighborhood. Similarity builder creates edges.

---

## Definition of Done

- [ ] All 9 memory tools operational for the agent
- [ ] Memory lifecycle: decay, merge, summarize, archive, orphan detection
- [ ] Memory audit trail: all changes logged with source attribution
- [ ] Knowledge graph: edge store, graph queries, similarity builder
- [ ] Knowledge graph UI: force-directed visualization with entity interaction
- [ ] Memory explorer UI: list, detail, timeline
- [ ] All tests pass
- [ ] **Phase 4 gate**: Full memory system operational — extraction, recall, tools, lifecycle, graph

---

## Risks & Notes

- **5 BS items in one sprint**: This sprint is dense. If behind, defer graph UI to early S12 (it's polish, not blocking).
- **LLM costs for consolidation**: Summarization consolidation triggers LLM calls. Run infrequently (weekly) and batch.
- **Graph visualization performance**: Large graphs (1000+ nodes) may be slow. Implement pagination and viewport culling.
- **Phase gate**: This sprint gates Phase 4. Full memory pipeline must work end-to-end: conversation → extraction → storage → recall → prompt injection → graph visualization.
