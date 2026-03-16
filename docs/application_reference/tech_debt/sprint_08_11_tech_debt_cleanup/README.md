# Tech Debt Cleanup — Sprints 08–11

**Created**: March 16, 2026
**Source audit**: [sprint_08_11_tech_debt.md](../sprint_08_11_tech_debt.md) (TD-43 through TD-137)
**Test baseline**: 683 passing, 1 pre-existing failure (`test_list_providers`)
**Goal**: Resolve all identified tech debt before proceeding to Sprint 12 (Plugins I)

---

## Purpose

This directory contains **7 tech-debt cleanup sub-sprints** that address every issue discovered in the Sprint 08–11 audit. The sub-sprints are executed sequentially between Sprint 11 (complete) and Sprint 12 (not started). No new features are added — only fixes, hardening, and quality improvements to the existing codebase.

---

## Sub-Sprint Overview

| Sub-Sprint | Focus | Items | Severity Coverage | Status |
|------------|-------|-------|-------------------|--------|
| **[TD-S1](td_s1_security.md)** | Security Hardening | 9 | 4 Critical, 3 High, 2 Medium | ✅ Complete |
| **[TD-S2](td_s2_correctness.md)** | Correctness Bugs | 11 | 3 Critical, 6 High, 2 Medium | ✅ Complete |
| **[TD-S3](td_s3_performance.md)** | Performance & Async | 13 | 3 High, 7 Medium, 3 Low | ✅ Complete |
| **[TD-S4](td_s4_concurrency.md)** | Concurrency & Resource Management | 11 | 2 Critical, 3 High, 6 Medium | ✅ Complete |
| **[TD-S5](td_s5_validation.md)** | Validation & Data Integrity | 14 | 1 High, 8 Medium, 5 Low | ✅ Complete |
| **[TD-S6](td_s6_observability.md)** | Observability & Error Handling | 14 | 12 Medium, 2 Low | ✅ Complete |
| **[TD-S7](td_s7_design.md)** | Design & Code Quality | 23 | 8 Medium, 15 Low | ✅ Complete |

**Total**: 95 items across 7 sub-sprints

---

## Execution Order

Sub-sprints **must** be executed in order (TD-S1 → TD-S2 → ... → TD-S7):

1. **TD-S1 Security** — fixes the most dangerous issues (attack chain in knowledge sources)
2. **TD-S2 Correctness** — fixes silent data corruption and wrong-result bugs
3. **TD-S3 Performance** — wraps blocking I/O, fixes scans and N+1 patterns
4. **TD-S4 Concurrency** — adds locks, OCC, cancellation tokens, fixes resource leaks
5. **TD-S5 Validation** — adds enum constraints, schema validation, type safety
6. **TD-S6 Observability** — replaces silent error swallowing with proper logging
7. **TD-S7 Design** — code quality, dead code removal, design improvements

**Dependencies between sub-sprints:**
- TD-S4 depends on TD-S2 (TD-62 splits `get()`/`touch()`, which TD-90 in S7 relies on)
- TD-S6 depends on TD-S5 (some observability improvements reference validation types)
- TD-S7 depends on all prior sub-sprints (final cleanup pass)

---

## Instruction Manual

### How to implement a tech-debt sub-sprint

Follow this workflow for each sub-sprint. It mirrors the main sprint workflow from `docs/application_reference/sprints/README.md` but is adapted for fix-only work.

#### Step 1 — Read the sub-sprint document in full

Each `td_sN_*.md` file contains:
- **Goal**: one-sentence objective
- **Items**: table of all TD items with file paths, line numbers, and severity
- **Tasks**: detailed fix descriptions grouped by file, with exact code changes
- **Testing**: what tests to run/write to verify fixes
- **Definition of Done**: checklist that gates sub-sprint completion

Read the entire document before writing any code.

#### Step 2 — Read the audit document for full context

Each task references a TD item by ID (e.g., TD-43). The full description, code samples, and root cause analysis are in [sprint_08_11_tech_debt.md](../sprint_08_11_tech_debt.md). Read the referenced TD entries for any item where the sub-sprint's task description isn't sufficient.

#### Step 3 — Audit the code before changing it

Before modifying any file:
1. Read the file in full (or the relevant section)
2. Check how the function/class is used by searching for imports and call sites
3. If the fix changes a public interface, find all callers and update them in the same sub-sprint

#### Step 4 — Implement fixes

- Make changes file-by-file, following the task order in the sub-sprint doc
- Group related changes (e.g., all fixes to one file) into a single editing pass
- After each file is modified, run that file's existing tests to catch regressions immediately
- Write new tests only when the sub-sprint doc explicitly calls for them

#### Step 5 — Run the full test suite

After all fixes in the sub-sprint are applied:

```powershell
cd c:\Users\aiang\PycharmProjects\AtanasAngelov\tequila
.venv\Scripts\python.exe -m pytest tests/ --tb=short -q
```

**Expected**: 683+ passing (fixes may enable previously-failing paths), 1 pre-existing failure (`test_list_providers`). Zero new failures.

#### Step 6 — Update the sub-sprint document

- Mark all tasks as `[x]` complete
- Set status to `✅ Complete`
- Record the final test count

#### Step 7 — Update this README

- Mark the sub-sprint row as `✅ Complete` in the Sub-Sprint Overview table
- Update the progress counter

#### Step 8 — Move to the next sub-sprint

Do not start the next sub-sprint until the current one is fully complete and all tests pass.

---

### Key rules for tech-debt fixes

These rules supplement the main coding standards in `docs/application_reference/sprints/README.md`.

1. **No feature additions.** These sub-sprints fix existing code only. Do not add new endpoints, new tools, new models, or new UI components.

2. **No interface changes without caller updates.** If a fix changes a function signature (e.g., splitting `get()` into `get()` and `touch()`), update every caller in the same sub-sprint.

3. **Preserve test count.** Fixes should not delete existing tests. If a test was testing broken behavior, update it to test the corrected behavior.

4. **New tests are additions.** When a fix adds validation (e.g., rejecting invalid input), add a test for the new validation. When a fix changes error-handling behavior, add a test for the new behavior.

5. **Follow existing patterns.** Use the same logging, error handling, and validation patterns already established in the codebase. Check how similar fixes were done in nearby code.

6. **One sub-sprint at a time.** Complete each sub-sprint fully before starting the next. Do not cherry-pick items across sub-sprints.

7. **Migration files.** If a fix requires a schema change (e.g., adding CHECK constraints), create a new Alembic migration. Use the next sequential number after the latest existing migration.

8. **Mark the audit document.** After completing all 7 sub-sprints, the tech debt audit document should be considered fully resolved.

---

### Testing strategy

| Sub-Sprint | Testing approach |
|------------|------------------|
| TD-S1 (Security) | Add validation tests for rejected inputs; verify auth on endpoints |
| TD-S2 (Correctness) | Update existing tests that tested broken behavior; add regression tests |
| TD-S3 (Performance) | Existing tests should still pass (wrapping in `to_thread` doesn't change behavior) |
| TD-S4 (Concurrency) | Add tests for lock contention, OCC retry, cancellation |
| TD-S5 (Validation) | Add tests for invalid input rejection; migration tests |
| TD-S6 (Observability) | Verify log output; test error response shapes |
| TD-S7 (Design) | Existing tests cover most changes; minor additions for new behavior |

---

### Estimated effort

| Sub-Sprint | Items | Estimated Time |
|------------|-------|----------------|
| TD-S1 | 9 | ~40 min |
| TD-S2 | 11 | ~55 min |
| TD-S3 | 13 | ~45 min |
| TD-S4 | 11 | ~45 min |
| TD-S5 | 14 | ~40 min |
| TD-S6 | 14 | ~30 min |
| TD-S7 | 23 | ~40 min |
| **Total** | **95** | **~5 hours** |

---

## Progress Tracking

| Milestone | Status |
|-----------|--------|
| Audit complete (TD-43 through TD-137) | ✅ Done |
| Sub-sprint documents created | ✅ Done |
| TD-S1 Security Hardening | ✅ Complete |
| TD-S2 Correctness Bugs | ✅ Complete |
| TD-S3 Performance & Async | ✅ Complete |
| TD-S4 Concurrency & Resources | ✅ Complete |
| TD-S5 Validation & Data Integrity | ⬜ Not Started |
| TD-S6 Observability & Error Handling | ✅ Complete |
| TD-S7 Design & Code Quality | ⬜ Not Started |
| Full test suite green (683+, 1 pre-existing) | ⬜ Not Started |
| Ready to proceed to Sprint 12 | ⬜ Not Started |
