# Tequila v2 — Developer Docs

**Updated**: March 14, 2026  
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

> **Sprint 03 complete — Phase 1 Foundation done.** All 145 tests pass. Setup wizard, health dashboard, session search/filter/sort, and connection status indicator are live. Phase 2 (Agent Core) ready to begin.

---

## Implementation status

| Sprint | Focus | Status |
|--------|-------|--------|
| S01 | App skeleton, gateway, config, DB | ✅ Done |
| S02 | Sessions, WebSocket, React shell | ✅ Done |
| S03 | Setup wizard, health dashboard, session search/filter/sort | ✅ Done |
| S04+ | … | ⬜ Not started |

Full sprint plan: [sprints/README.md](./application_reference/sprints/README.md)
