# Tequila v2 — Developer Docs

**Updated**: March 15, 2026  
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

> **Sprint 08 complete — Phase 3 Multi-Agent backend done.** 49 new Sprint 08 tests (all passing). Session tools, sub-agent spawning, workflow pipeline + parallel modes, and full Workflow REST API are live. See [sprint_08.md](./application_reference/sprints/sprint_08.md) for details.

---

## Implementation status

| Sprint | Focus | Status |
|--------|-------|--------|
| S01 | App skeleton, gateway, config, DB | ✅ Done |
| S02 | Sessions, WebSocket, React shell | ✅ Done |
| S03 | Setup wizard, health dashboard, session search/filter/sort | ✅ Done |
| S04–S07 | Agent Core (models, turn loop, tools, policies) | ✅ Done |
| S08 | Multi-Agent: session tools, sub-agents, workflows | ✅ Done |
| S09+ | … | ⬜ Not started |

Full sprint plan: [sprints/README.md](./application_reference/sprints/README.md)
