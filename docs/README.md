# Tequila v2 — Developer Docs

**Updated**: March 17, 2026  
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

> **Sprint 11 complete — Phase 4 Memory III (and Phase 4 gate) done.** 86 new Sprint 11 tests (+67 unit, +19 integration, all passing). Agent memory tools (13 tools: save/update/forget/search/list/pin/unpin/link + entity_*/extract_now), memory lifecycle manager (decay, archive, merge, orphan detection), memory audit trail (16 event types, history API, global feed), and knowledge graph (typed edge store, BFS neighbourhood, semantic similarity builder, full REST API at `/api/graph`) are live. Phase 4 Memory pipeline fully operational: extraction → recall → tools → lifecycle → graph. See [sprint_11.md](./application_reference/sprints/sprint_11.md) for details.

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
| S11 | Memory III: memory tools, lifecycle, knowledge graph | ✅ Done |
| S12+ | … | ⬜ Not started |

Full sprint plan: [sprints/README.md](./application_reference/sprints/README.md)
