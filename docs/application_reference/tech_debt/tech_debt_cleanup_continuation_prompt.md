# Tequila v2 — Tech Debt Cleanup Agent Prompt (Continuation)

You are continuing the **tech-debt cleanup phase** for Tequila v2. Some sub-sprints have already been completed. Your job is to find exactly where work stopped, verify nothing is broken, and continue from that point without duplicating or undoing completed fixes.

---

### Step 1 — Orient yourself

Read these documents in order before touching any code:

1. `docs/application_reference/tech_debt/` — list this directory. Identify the **active cleanup folder**: the sub-directory whose `README.md` has sub-sprints that are not yet all `✅ Complete`. Open that README now.
2. Read the **cleanup folder README** in full. The Progress Tracking table shows which sub-sprints are ✅ Complete, 🔧 In Progress, or ⬜ Not Started. Note the execution order and any inter-sprint dependencies.
3. Read the **audit document** referenced in the cleanup README — this is the root source of all TD item IDs. Look up items here when you need detailed context.
4. `docs/application_reference/sprints/README.md` — coding standards, async patterns, SQLite rules, naming conventions.
5. `docs/architecture.md` and `docs/module-map.md` — current codebase structure.

---

### Step 2 — Find where work stopped

1. Open the **first sub-sprint marked 🔧 In Progress or ⬜ Not Started** in the cleanup README.
2. Open that sub-sprint's document.
3. Scan the task checklist — find the first unchecked `- [ ]` task.
4. Before proceeding, **read the actual source files** involved in that task. Do not assume the checklist reflects reality — verify the current code state before making any changes.

---

### Step 3 — Verify the test baseline

Run the full test suite before making any changes:

```powershell
cd c:\Users\aiang\PycharmProjects\AtanasAngelov\tequila
.venv\Scripts\python.exe -m pytest tests/ --tb=line -q
```

Record the passing count and names of any pre-existing failures. Completed sub-sprints may have increased the passing count from the original baseline — that is expected. If there are unexpected failures, diagnose and fix them before proceeding. Do not introduce new changes on a broken baseline.

---

### Step 4 — Continue the current sub-sprint

Resume from the first unchecked task. Follow the same 8-step workflow defined in the cleanup README:

1. Read the task description (and the audit TD entry for full context if needed).
2. Read the file(s) to be modified.
3. Apply the fix.
4. Run the test suite to verify no regressions after each logical group of changes.
5. Write any new tests called out in the sub-sprint's Testing section.
6. Mark completed tasks as `[x]` in the sub-sprint document.
7. When all tasks in the sub-sprint are done, set its status to `✅ Complete`.
8. Update the cleanup README progress table.

Then move to the next sub-sprint in sequence according to the cleanup README's execution order.

---

### Step 5 — After all sub-sprints are complete

1. Run the full test suite one final time.
2. Mark all progress milestones in the cleanup README as complete.
3. Report completion: total tests passing, any deviations from the plan.
4. Do **not** start the next feature sprint — stop and report. A separate session continues with feature work.

---

### Key rules for this cleanup phase

- **No feature additions.** Fix existing code only. Do not add new endpoints, tools, models, or UI components.
- **No interface changes without updating all callers.** If a fix changes a function signature, find every call site and update it in the same sub-sprint.
- **Preserve the test count.** Do not delete existing tests. Update tests that tested broken behavior to test the corrected behavior instead.
- **Never `except Exception: pass`.** Replace with `logger.warning("...", exc_info=True)`.
- **Parameterised SQL always.** Never build SQL strings with f-strings or `.format()` on user data.
- **Every blocking call in `async` code must be wrapped** in `await asyncio.to_thread(...)`.
- **Use `Literal[...]` for enum-like fields.** Not `str`.

---

### Workspace state

- `.venv` is at `.venv/`. Use it for all Python commands.
- Target OS: Windows. Use PowerShell for terminal commands.
- Tech-debt documents: `docs/application_reference/tech_debt/`
- Sprint standards: `docs/application_reference/sprints/README.md`
- Do not modify `docs/` except to update tech-debt sub-sprint status and checklist items.

Start by listing `docs/application_reference/tech_debt/`, reading the active cleanup README, then verifying the test baseline, then find and continue the first incomplete sub-sprint.
