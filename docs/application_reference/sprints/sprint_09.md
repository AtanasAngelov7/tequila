# Sprint 09 — Memory I: Vault, Embeddings & Memory Data Model

**Phase**: 4 – Memory & Knowledge (I)
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-23, BS-24, BS-25, BS-26

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Build the memory system's foundation: the vault (local knowledge base of markdown notes with wiki-links), the embedding engine for semantic similarity, and the structured memory data model (identity, preference, fact, experience, etc.) with entity linking. By sprint end, the vault is browsable, embeddings index all notes, and memory records can be created with structured types and entity references.

---

## Spec References

| Section | Topic |
|---------|-------|
| §5.10 | Vault (note CRUD, wiki-link parser, watcher, vault_dir) |
| §5.13 | Embedding engine (EmbeddingProvider ABC, SQLiteEmbeddingStore, sentence-transformers default, reindex) |
| §5.3 | Structured memory types (identity, preference, fact, experience, task, relationship, skill) |
| §5.4 | Entity model (entity store, NER extraction, alias resolution, entity-memory linking) |
| §5.1 | Memory architecture overview |
| §5.2 | Memory scope model (global, agent, session) |
| §20.3b | Optimistic concurrency (version columns on memory_extracts) |

---

## Prerequisites

- Requires Sprint 08 deliverables and the Phase 3 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Vault Storage
- `app/knowledge/vault.py` — vault implementation:
  - `vault_dir` configurable path (default: `data/vault/`)
  - Note CRUD: create, read, update, delete markdown notes
  - Wiki-link parser: extract `[[links]]` from markdown, build link graph
  - File watcher: detect external edits → re-index changed notes
  - Vault API:
    - `GET /api/vault/notes` — list notes (with search)
    - `GET /api/vault/notes/{id}` — note content
    - `POST /api/vault/notes` — create note
    - `PUT /api/vault/notes/{id}` — update note
    - `DELETE /api/vault/notes/{id}` — delete note
    - `GET /api/vault/graph` — link graph (nodes + edges from wiki-links)
- Notes stored as plain markdown files on disk; metadata in SQLite

**Acceptance**: CRUD notes via API. Wiki-links parsed and graph built. File watcher detects external changes.

### D2: Embedding Engine
- `app/knowledge/embeddings.py` — embedding system:
  - `EmbeddingProvider` ABC with `embed(texts) → list[list[float]]`
  - Default provider: `sentence-transformers` (local, no API key, model: `all-MiniLM-L6-v2`)
  - `SQLiteEmbeddingStore`: store vectors in SQLite (binary blob), cosine similarity search via numpy
  - Embedding dimensions: configurable (384 for default model)
  - Reindex triggers: note updated, new note created, embedding model changed
  - Batch embedding: process multiple texts in one call
- `POST /api/embeddings/reindex` — trigger full reindex

**Acceptance**: Notes are embedded on create/update. Semantic search returns similar notes. Reindex works.

### D3: Memory Data Model
- `app/memory/models.py` — structured memory types:
  - `MemoryRecord` base: `id, type, subject, content, confidence, source_session_id, source_message_id, created_at, updated_at, accessed_at, access_count, decay_at`
  - Types (enum): `identity`, `preference`, `fact`, `experience`, `task`, `relationship`, `skill`
  - Per-type fields: `preference.strength`, `relationship.entity_ids`, `task.status`, etc.
  - Provenance: `source_type` (extracted | user_stated | tool_observed | inferred)
  - Decay fields: `decay_at`, `importance_score`, `last_reinforced_at`
- `app/memory/store.py` — memory CRUD with type-specific validation
- Migration: `memories` table with all columns + indexes
- `GET/POST/PATCH/DELETE /api/memories` — memory CRUD API

**Acceptance**: Create memories of each type. Validation per type. CRUD operations. Decay fields populated.

### D4: Entity Model
- `app/memory/entities.py` — entity system:
  - `Entity` model: `id, name, type, aliases, metadata, created_at, updated_at`
  - Entity types: `person`, `organization`, `place`, `project`, `concept`, `other`
  - Alias resolution: map multiple names to same entity
  - Entity-memory linking: many-to-many relationship (memory references entity)
  - NER extraction: lightweight local NER (spaCy or regex-based) to identify entities in text
- `app/memory/entity_store.py` — entity CRUD
- `GET/POST/PATCH/DELETE /api/entities` — entity API
- `GET /api/entities/{id}/memories` — memories linked to entity

**Acceptance**: Entities created with aliases. NER extracts entities from text. Memories linked to entities.

---

## Tasks

### Backend — Vault
- [x] Create `app/knowledge/vault.py` — note CRUD on disk + SQLite metadata
- [x] Implement wiki-link parser (regex for `[[...]]`, build adjacency list)
- [x] Implement file watcher (`sync_from_disk()` polling — no external watchdog dependency)
- [x] Create vault API routes
- [x] Migration: vault_notes metadata table

### Backend — Embeddings
- [x] Create `app/knowledge/embeddings.py` — EmbeddingProvider ABC
- [x] Implement sentence-transformers provider (lazy-loaded, `all-MiniLM-L6-v2`, 384 dims)
- [x] Create SQLiteEmbeddingStore (binary blob storage, cosine similarity via numpy)
- [x] Implement reindex logic (full + incremental)
- [x] Hook embedding on note create/update
- [x] API: reindex endpoint

### Backend — Memory Model
- [x] Create `app/memory/models.py` — MemoryExtract + per-type defaults + OCC version field
- [x] Create `app/memory/store.py` — CRUD with OCC 3-retry
- [x] Migration: memory_extracts table
- [x] Memory CRUD API routes

### Backend — Entities
- [x] Create `app/memory/entities.py` — Entity model + regex-based NER + alias resolution
- [x] Create `app/memory/entity_store.py` — CRUD
- [x] Implement NER extraction (regex-based; heuristic type inference; no spaCy dependency)
- [x] Entity-memory linking (junction table + migration)
- [x] Entity API routes

### Frontend
- [ ] Vault browser: note list, note viewer (rendered markdown), note editor *(deferred)*
- [ ] Vault graph visualization (simple force-directed graph of wiki-links) *(deferred)*
- [ ] Memory explorer: list memories, filter by type, search *(deferred)*
- [ ] Entity list view *(deferred)*

### Tests
- [x] `tests/unit/test_vault.py` — CRUD, wiki-link parser, watcher (20 tests)
- [x] `tests/unit/test_embeddings.py` — embed, store, search, reindex (13 tests)
- [x] `tests/unit/test_memory_model.py` — create each type, validation (19 tests)
- [x] `tests/unit/test_entities.py` — CRUD, alias resolution, NER (19 tests)
- [x] `tests/integration/test_vault_embeddings.py` — vault/memory/entity API end-to-end (19 tests)

---

## Testing Requirements

- Vault: create note with wiki-links → links parsed → graph reflects connections. External edit detected.
- Embeddings: embed 10 notes → search "similar to X" → relevant notes ranked first.
- Memory: create each of 7 types with valid/invalid data → validation works.
- Entities: NER extracts "John Smith" → entity created → alias "John" resolves → memories linked.

---

## Definition of Done

- [x] Vault operational: CRUD notes, wiki-link graph, file watcher
- [x] Embedding engine indexes notes, semantic search works
- [x] Memory records of all 7 types can be created with validation
- [x] Entity model with aliases, NER extraction, memory linking
- [x] All APIs documented and tested
- [x] All tests pass (90 new tests: 71 unit + 19 integration; 1 pre-existing failure unrelated to S09)

---

## Risks & Notes

- **sentence-transformers size**: The default model is ~80 MB. First-time download required. Consider bundling or lazy download.
- **SQLite vector search performance**: Cosine similarity in Python over numpy is fine for <100k vectors. For larger scales, consider sqlite-vss extension.
- **NER quality**: Lightweight NER (spaCy `en_core_web_sm`) may miss domain-specific entities. Entity creation via tools (S11) will supplement.
- **Vault vs memory overlap**: Vault = user-curated notes (Obsidian-like). Memory = agent-extracted structured knowledge. They complement each other.
