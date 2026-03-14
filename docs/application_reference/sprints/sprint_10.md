# Sprint 10 — Memory II: Extraction, Recall & Knowledge Sources

**Phase**: 4 – Memory & Knowledge (II)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-27, BS-28, BS-28a

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Wire up the automatic memory pipelines: extraction (conversation → structured memories) and recall (memories → prompt context). Implement the Knowledge Source Registry for federating recall across external vector stores. By sprint end, the agent automatically extracts memories from conversations and recalls relevant context for every turn — including from external knowledge bases.

---

## Spec References

| Section | Topic |
|---------|-------|
| §5.5 | Extraction pipeline (6-step: classify → extract → dedup → conflict → entity-link → graph-edge) |
| §5.6 | Recall pipeline (3-stage: session init pre-load → per-turn foreground → background pre-fetch + entity graph traversal) |
| §5.14 | Knowledge Source Registry — includes: KnowledgeSourceAdapter ABC, built-in adapters (Chroma, pgvector, FAISS, HTTP), registry + recall integration (steps 4a–4b), agent tools (kb_search, kb_list_sources), API endpoints, database schema |
| §20.5 | Background task safety (timestamp-gated writes for extraction pipeline) |

---

## Prerequisites

- Requires Sprint 09 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Extraction Pipeline
- `app/memory/extraction.py` — 6-step pipeline runs post-turn:
  1. **Classify**: LLM determines if turn contains extractable information (skip small talk)
  2. **Extract**: LLM extracts structured memories (type, subject, content, confidence) from conversation
  3. **Deduplicate**: compare extracted memories against existing (embedding similarity > threshold → merge)
  4. **Conflict resolution**: detect contradictions (e.g., "prefers Python" vs "prefers Rust"), resolve by recency + confidence
  5. **Entity-link**: link extracted memories to entities (create new entities if needed)
  6. **Graph-edge**: create knowledge graph edges between entities mentioned together
- Configurable: extraction enabled/disabled per session, minimum confidence threshold
- Feedback influence: messages with thumbs-down reduce extraction confidence

**Acceptance**: After conversation about user preferences → memory records auto-created. Duplicates merged. Contradictions resolved.

### D2: Recall Pipeline
- `app/memory/recall.py` — 3-stage recall:
  1. **Session init pre-load**: when session opens, load identity memories + pinned memories + recent high-importance memories
  2. **Per-turn foreground**: embed user message → top-K semantic search → relevant memories injected into prompt (§4.3a step 3a)
  3. **Background pre-fetch**: after turn, predict next-turn context → pre-load into cache; entity graph traversal (related entities → their memories)
- Memory selection: ranked by `relevance_score * importance_score * recency_factor`
- Budget-aware: recall respects memory slot in ContextBudget (from S07)
- Access tracking: bump `access_count` and `accessed_at` on recall

**Acceptance**: Turn mentions "project Alpha" → memories about project Alpha injected into next prompt. Pre-fetch loads related entity memories.

### D3: Knowledge Source Registry
- `app/knowledge/sources/registry.py` — `KnowledgeSourceRegistry`:
  - Register, list, enable/disable, health-check external knowledge sources
  - `KnowledgeSourceAdapter` ABC: `search(query, top_k) → list[KnowledgeResult]`, `health() → HealthStatus`
- `app/knowledge/sources/adapters/`:
  - `chroma.py` — ChromaDB adapter (HTTP client to Chroma server)
  - `pgvector.py` — PostgreSQL + pgvector adapter (asyncpg)
  - `faiss.py` — FAISS local index adapter
  - `http.py` — Generic HTTP endpoint adapter (configurable URL, auth, response mapping)
- Each adapter: connection config, auth, timeout, retry

**Acceptance**: Register Chroma source → `kb_search` returns results from Chroma. Multiple sources federated.

### D4: Recall Federation
- Recall pipeline integration (steps 4a–4b from §5.14.3):
  - 4a: For each enabled knowledge source, issue parallel search with user query
  - 4b: Merge external results with local memory results, re-rank by relevance, deduplicate
- Configurable: max results per source, total budget for external results
- Timeout: per-source timeout (default 5s), don't block recall if source is slow

**Acceptance**: Recall returns mix of local memories + external KB results, properly ranked.

### D5: Knowledge Source Agent Tools
- `kb_search(query, sources?, top_k?)` — search knowledge sources (or all if unspecified)
- `kb_list_sources()` — list registered knowledge sources with health status
- Safety: `read_only`
- Tools registered in tool framework

**Acceptance**: Agent can explicitly search external KBs and list available sources.

### D6: Knowledge Source API & Health
- API endpoints:
  - `POST /api/knowledge-sources` — register new source
  - `GET /api/knowledge-sources` — list sources with status
  - `GET /api/knowledge-sources/{id}` — source detail
  - `PATCH /api/knowledge-sources/{id}` — update config
  - `DELETE /api/knowledge-sources/{id}` — remove source
  - `POST /api/knowledge-sources/{id}/test` — test connectivity
- Health monitoring: periodic health check, latency tracking, auto-disable on repeated failures

**Acceptance**: Full CRUD for knowledge sources. Health monitoring auto-disables unhealthy sources.

---

## Tasks

### Backend — Extraction Pipeline
- [ ] Create `app/memory/extraction.py`
- [ ] Step 1: classify (LLM call — "does this turn contain extractable info?")
- [ ] Step 2: extract (LLM call — structured memory extraction)
- [ ] Step 3: dedup (embedding similarity against existing memories)
- [ ] Step 4: conflict resolution (recency + confidence comparison)
- [ ] Step 5: entity-link (match/create entities for extracted memories)
- [ ] Step 6: graph-edge (create edges between co-occurring entities)
- [ ] Hook into post-turn pipeline (after turn completes)
- [ ] Configurable extraction per session

### Backend — Recall Pipeline
- [ ] Create `app/memory/recall.py`
- [ ] Stage 1: session init pre-load (identity + pinned + recent)
- [ ] Stage 2: per-turn foreground (embed query → semantic search → inject)
- [ ] Stage 3: background pre-fetch (predict, entity graph traversal)
- [ ] Ranking: relevance * importance * recency
- [ ] Budget-aware: respect ContextBudget memory slot
- [ ] Access tracking on recalled memories

### Backend — Knowledge Source Registry
- [ ] Create `app/knowledge/sources/registry.py`
- [ ] Create KnowledgeSourceAdapter ABC
- [ ] Implement Chroma adapter
- [ ] Implement pgvector adapter
- [ ] Implement FAISS adapter
- [ ] Implement HTTP adapter
- [ ] Recall federation (steps 4a-4b) with parallel search + merge

### Backend — Knowledge Source API
- [ ] CRUD endpoints for knowledge sources
- [ ] Test connectivity endpoint
- [ ] Health monitoring (periodic check, auto-disable)
- [ ] Agent tools: kb_search, kb_list_sources

### Frontend
- [ ] Memory injection indicator in chat (show which memories were recalled)
- [ ] Knowledge sources management page (list, add, configure, test, health status)

### Tests
- [ ] `tests/unit/test_extraction.py` — each step of 6-step pipeline
- [ ] `tests/unit/test_recall.py` — pre-load, foreground, background
- [ ] `tests/unit/test_knowledge_sources.py` — registry, adapters (mocked)
- [ ] `tests/integration/test_extraction_recall.py` — converse → extract → recall on next turn
- [ ] `tests/integration/test_federation.py` — local + external results merged

---

## Testing Requirements

- Extraction: 5-turn conversation about preferences → memories created with correct types. Duplicate → merged. Conflict → resolved.
- Recall: create 20 memories → ask question → top relevant memories in prompt. Pre-load works on session init.
- Federation: mock Chroma + local memories → kb_search returns merged results.
- Knowledge sources: register → test → health check → auto-disable on failure.

---

## Definition of Done

- [ ] Extraction pipeline runs post-turn, creates structured memories automatically
- [ ] Recall pipeline injects relevant memories into each turn's prompt
- [ ] Knowledge Source Registry with all 4 adapters (Chroma, pgvector, FAISS, HTTP)
- [ ] Federation merges local + external results with ranking
- [ ] Agent tools: kb_search and kb_list_sources operational
- [ ] Knowledge source API with health monitoring
- [ ] All tests pass

---

## Risks & Notes

- **LLM extraction cost**: Each turn may trigger 1-2 LLM calls for extraction. Consider batching or lightweight heuristics to skip extraction on trivial turns.
- **Recall latency**: External KB queries add latency. Enforce per-source timeouts strictly. Background pre-fetch helps.
- **Adapter reliability**: External services (Chroma, pgvector) may be unavailable. Health monitoring + auto-disable prevents recall pipeline from blocking.
- **Embedding model consistency**: External KBs may use different embedding models than local. Cross-model similarity may be poor. Document this limitation.
