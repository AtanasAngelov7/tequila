# Tequila v2 — Developer Docs

**Updated**: March 16, 2026  
**Spec**: [tequila_v2_specification.md](./application_reference/tequila_v2_specification.md)  
**Sprint guide**: [sprints/README.md](./application_reference/sprints/README.md)

This directory documents the *implementation* — what is built, how the pieces connect, and where to find things. The specification describes the target design; this directory describes what currently exists.

---

## Documents

| File | Contents |
|------|----------|
| [architecture.md](./architecture.md) | System architecture, module dependency graph, startup sequence, runtime data flow |
| [module-map.md](./module-map.md) | Every `app/` module — its responsibility, key exports, and spec reference |

---

## Quick orientation

> **Sprint 10 complete — Phase 4 Memory II done.** 58 new Sprint 10 tests (38 unit + 20 integration, all passing). Extraction pipeline, recursive recall (Stage 1/2/3), knowledge source registry with 4 adapters (ChromaDB, pgvector, FAISS, HTTP), federated search, `kb_search`/`kb_list_sources` agent tools, and full CRUD REST API for knowledge sources are live. See [sprint_10.md](./application_reference/sprints/sprint_10.md) for details.

---

## Implementation status

| Sprint | Focus | Status |
|--------|-------|--------|
| S01 | App skeleton, gateway, config, DB | ✅ Done |
| S02 | Sessions, WebSocket, React shell | ✅ Done |
| S03 | Setup wizard, health dashboard, session search/filter/sort | ✅ Done |
| S04–S07 | Agent Core (models, turn loop, tools, policies) | ✅ Done |
| S08 | Multi-Agent: session tools, sub-agents, workflows | ✅ Done |
| S09 | Memory I: vault, embeddings, memory data model, entities | ✅ Done |
| S10 | Memory II: extraction, recall, knowledge sources | ✅ Done |
| S11+ | … | ⬜ Not started |

Full sprint plan: [sprints/README.md](./application_reference/sprints/README.md)
