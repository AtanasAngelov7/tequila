# Tequila v2 — Tech Debt Cleanup Agent Prompt (Start)

You are executing a **tech-debt cleanup phase** for Tequila v2. A set of issues discovered in a systematic audit must be resolved across a series of sequential sub-sprints before the next feature sprint begins. Your job is to work through every sub-sprint in order, fix every item, verify tests, and leave the codebase clean.

---

### Step 1 — Orient yourself

Read these documents in order before touching any code:

1. `docs/application_reference/tech_debt/` — list this directory. Identify the **active cleanup folder**: the sub-directory whose `README.md` contains sub-sprints that are not yet all `✅ Complete`. Open that README now.
2. Read the **cleanup folder README** in full. It tells you:
   - Which audit document to reference (the root source of all TD item IDs)
   - The full list of sub-sprints, their execution order, and current status
   - The step-by-step workflow for each sub-sprint
   - Key rules and testing strategy specific to this cleanup
3. Read the **audit document** identified in the cleanup README — this is the root source of all issues. Every sub-sprint references items from here by ID.
4. `docs/application_reference/sprints/README.md` — the project's coding standards, async patterns, SQLite rules, and naming conventions. These apply to fixes just as they do to features.
5. `docs/architecture.md` and `docs/module-map.md` — understand the current structure of the codebase before modifying it.

---

### Step 2 — Confirm the test baseline

Before touching any code, run the full test suite and record the result:

```powershell
cd c:\Users\aiang\PycharmProjects\AtanasAngelov\tequila
.venv\Scripts\python.exe -m pytest tests/ --tb=line -q
```

Record the passing count and the names of any pre-existing failures. Any sub-sprint that introduces new failures must be fixed before proceeding to the next.

---

### Step 3 — Work through sub-sprints in order

The sub-sprint list, documents, and execution order are defined in the **cleanup folder README** (found in Step 1). Execute them **sequentially** — do not skip ahead or merge sub-sprints. Follow the workflow in the README for each one.

---

### Step 4 — Follow this workflow for each sub-sprint

1. **Read the sub-sprint document in full** before writing any code.
2. **Look up the audit entry** by TD-ID in the audit document (identified in Step 1) for any item where the task description needs more context.
3. **Read every file you will modify** — understand its current shape before changing anything.
4. **Apply all fixes** in the sub-sprint, grouping changes to the same file into a single editing pass.
5. **Run the test suite** after completing the sub-sprint:
   ```powershell
   .venv\Scripts\python.exe -m pytest tests/ --tb=short -q
   ```
6. **Write new tests** called out in the sub-sprint's Testing section.
7. **Mark all tasks `[x]` complete** in the sub-sprint document and set its status to `✅ Complete`.
8. **Update the cleanup README** — mark the sub-sprint row as `✅ Complete`.

---

### Step 5 — After all sub-sprints are complete

1. Run the full test suite one final time and record the result.
2. Update the cleanup folder README — mark all progress milestones as complete.
3. Report completion: total tests passing, list of any items that needed deviation from the plan.
4. Do **not** start the next feature sprint — stop and report. A separate session continues with feature work.

---

### Key rules for this cleanup phase

- **No feature additions.** Fix existing code only. Do not add new endpoints, tools, models, or UI components.
- **No interface changes without updating all callers.** If a fix changes a function signature, find every call site and update it in the same sub-sprint.
- **Preserve the test count.** Do not delete existing tests. Update tests that were testing broken behavior to test the corrected behavior.
- **Every blocking call in `async` code must be wrapped** in `await asyncio.to_thread(...)`. This is the most common performance fix pattern.
- **Never `except Exception: pass`.** Replace with `logger.warning("...", exc_info=True)`.
- **Parameterised SQL always.** Never build SQL strings with f-strings or `.format()` on user data.
- **Use `Literal[...]` for enum-like fields.** Not `str`.

---

### Workspace state

- `.venv` is at `.venv/`. Use it for all Python commands.
- Target OS: Windows. Use PowerShell for terminal commands.
- Tech-debt documents: `docs/application_reference/tech_debt/`
- Sprint standards: `docs/application_reference/sprints/README.md`
- Do not modify `docs/` except to update tech-debt sub-sprint status and checklist items as part of completing each sub-sprint.

Start by listing `docs/application_reference/tech_debt/`, reading the active cleanup README, then confirming the test baseline, then begin the first sub-sprint.
