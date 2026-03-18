# Sprint 15 — Polish II: Full UI, File Cleanup & Windows Packaging

**Phase**: 6 – Polish (II) (**Phase Gate Sprint**)
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-56, BS-57, BS-58, BS-59
> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.
---

## Goal

Complete the frontend build-out with all remaining UI surfaces, implement file management (download/export, cleanup/retention), and produce the Windows distributable package. By sprint end, the full application is usable end-to-end with a polished UI and can be installed on any Windows machine via a single `.exe` installer.

---

## Spec References

| Section | Topic |
|---------|-------|
| §21.6 | File download & export flow (file cards, preview endpoint, quick actions, local-app actions: open file / reveal in Explorer) |
| §9.2a | Inline media rendering (per-MIME-type rules: image lightbox, PDF side-panel viewer, code preview, audio player) |
| §9.2b | Session files panel (right sidebar, file list grouped by origin, search/filter, pin, quick actions) |
| §9.2 | Full React UI specification (all pages) |
| §9.1 | UI layout (sidebar, main area, panels) |
| §21.7 | File cleanup & retention (orphan detection, storage quota, soft-delete, cleanup task) |
| §29.1 | PyInstaller freeze (--onedir bundle) |
| §29.2 | Frozen-mode path resolution |
| §29.3 | Plugin venv isolation in frozen mode |
| §29.4 | Inno Setup installer |
| §29.5 | Auto-update (notification-only for now) |

---

## Prerequisites

- Requires Sprint 14a and Sprint 14b deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: File Download, Export & Inline Media
- `app/files/export.py` — file serving and download:
  - File cards in chat: when agent references/creates files, show interactive card with:
    - File name, size, type icon
    - Preview button (text files inline, images thumbnail, PDFs first page)
    - Download button
    - Quick actions (6 total — §21.6): **Download**, **Open file** (OS default app via `POST /api/files/{id}/open`), **Reveal in Explorer** (`POST /api/files/{id}/reveal`), **View** (inline viewer), **Copy path**, **Pin/Unpin** (overflow menu)
  - Preview endpoint: `GET /api/files/preview/{file_id}` — generate preview for file type
  - Download endpoint: `GET /api/files/{file_id}/download`
  - Local-app action endpoints (§21.6):
    - `POST /api/files/{id}/open` — `os.startfile()` / `xdg-open` / `open`
    - `POST /api/files/{id}/reveal` — `explorer /select,` / equivalent on other OS
  - Agent-generated files: track in `session_files` table (session_id, file_path, created_at, type)

- **Inline media rendering** (§9.2a) — per-MIME-type rendering rules inside chat messages:
  - **Images**: inline thumbnail (300px max width), multi-image grid (2-col, "+N more"). Click opens **image lightbox** (full-res overlay with zoom/pan/navigation, Esc to close).
  - **PDFs**: first-page thumbnail + filename + page count. Click opens **PDF side panel** (right rail, 40% width, browser-native `<iframe>` — provides zoom, search, page nav with zero dependencies).
  - **Code/text files**: syntax-highlighted 30-line collapsible preview. "View" opens side panel (shared with PDF viewer) with full content + line numbers.
  - **Audio**: inline `<audio>` player widget (play/pause, seek, speed selector 0.5x–2x, optional transcript toggle).
  - **Office docs / other**: file card (icon + name + size), "Open file" action launches OS default app.

- **Session files panel** (§9.2b):
  - Right sidebar tab toggled via 📎 icon or `Ctrl+Shift+F`
  - `GET /api/sessions/{id}/files` — returns all files for the session (uploaded + agent-generated)
  - Grouped by origin ("Uploads" / "Agent Generated"), collapsible sections
  - Search by filename, filter by MIME category (images, documents, audio, other)
  - Per-file `⋮` menu: same 6 quick actions as file cards
  - Click filename → scrolls chat to the referencing message
  - Sort by date (default) / name / size. Pin indicator (📌) for pinned files.

- Frontend: file card component, image lightbox, PDF side panel, code viewer, audio player, session files panel

**Acceptance**: Agent creates file → file card appears in chat with 6 quick actions. Images show inline thumbnail → click opens lightbox with zoom. PDFs show thumbnail → click opens side panel viewer. Code files show syntax-highlighted preview. Audio has inline player. Session files panel lists all files grouped by origin. Open/reveal actions invoke OS-level commands.

### D2: Full React UI Build-Out
- Complete all remaining UI pages and components (§9.2):
  - **Settings pages**: general, providers, agent management, plugins, web/browser/vision, memory, notifications, security (app lock), backup
  - **Plugin management**: plugin list, per-plugin config page, health indicators
  - **Workflow visualization**: visual workflow editor, run monitor
  - **Memory explorer**: full memory browser, entity explorer, audit timeline
  - **Web/browser settings**: web policy editor, cache admin, browser profile manager
  - **Sidebar polish**: session list with status indicators, pinned sessions, session groups
  - **Global search**: Cmd+K palette searching sessions, memories, vault notes, settings
  - **Keyboard shortcut overlay**: show all shortcuts on `?` press
  - **Responsive layout**: proper mobile/tablet breakpoints (though desktop-primary)
- Design system finalization: consistent spacing, animations, transitions, loading states, empty states

**Acceptance**: All settings accessible. All features have UI surfaces. Consistent design system. Global search works.

### D3: File Cleanup & Retention
- `app/files/cleanup.py` — file lifecycle management:
  - Orphan detection: find files in `data/files/` not referenced by any message or session
  - Storage quota: configurable maximum storage (default: no limit), warning at 80%
  - Soft-delete: files flagged for deletion → recoverable for 30 days → permanent delete
  - Cleanup task: periodic task (daily) — detect orphans, enforce quota, purge expired soft-deletes
  - API: `GET /api/files/stats`, `POST /api/files/cleanup`, `GET /api/files/orphans`
- Frontend: storage dashboard (usage chart, orphan list, cleanup trigger)

**Acceptance**: Orphan files detected. Storage quota warning at 80%. Soft-delete recoverable for 30 days. Cleanup task runs.

### D4: Windows Packaging
- `build/` — build scripts and configuration:
  - **PyInstaller spec**: `tequila.spec` — `--onedir` bundle including:
    - Python runtime, all pip packages
    - Frontend build output (`frontend/dist/`)
    - Alembic migrations
    - Default config template
    - `sentence-transformers` model (if bundled) or lazy download
  - **Frozen-mode path resolution**: `app/paths.py` detects `sys._MEIPASS` → adjust all paths
  - **Plugin venv isolation**: in frozen mode, create plugin venvs using bundled Python
  - **Inno Setup script**: `build/installer.iss`:
    - Single `.exe` installer (~150-300 MB)
    - Install to `%LOCALAPPDATA%\Tequila\`
    - Start menu shortcut, optional desktop shortcut
    - Uninstaller with data preservation option
    - Auto-run on startup (optional)
  - **Build script**: `build/build.ps1` — end-to-end build (npm build → PyInstaller → Inno Setup)
  - **Auto-update notification**: version check on startup → notification if new version available (no auto-download yet)

**Acceptance**: Run build script → produces installer .exe → install on clean Windows → app launches → all features work.

---

## Tasks

### Backend — File Export & Actions
- [ ] Create `app/files/export.py` — preview/download endpoints
- [ ] Create `session_files` table + migration
- [ ] File preview generation (text, image thumbnail, PDF first page)
- [ ] Download endpoint with content-type headers
- [ ] `POST /api/files/{id}/open` — open file with OS default app (`os.startfile` / `xdg-open`)
- [ ] `POST /api/files/{id}/reveal` — reveal in file manager (`explorer /select,` / equivalent)
- [ ] `GET /api/sessions/{id}/files` — session files list endpoint (grouped by origin, filterable)

### Backend — File Cleanup
- [ ] Create `app/files/cleanup.py`
- [ ] Orphan detection (scan data/files/ vs session_files)
- [ ] Storage quota tracking + warning
- [ ] Soft-delete lifecycle (flag → 30 days → purge)
- [ ] Periodic cleanup task
- [ ] File management API endpoints

### Backend — Packaging
- [ ] Create `tequila.spec` PyInstaller configuration
- [ ] Resolve all hidden imports and data files
- [ ] Update `app/paths.py` for frozen-mode detection
- [ ] Plugin venv creation with bundled Python
- [ ] Create `build/installer.iss` Inno Setup script
- [ ] Create `build/build.ps1` build automation script
- [ ] Auto-update version check endpoint

### Frontend — File UI & Inline Media (§9.2a, §9.2b)
- [ ] File card component (name, size, type icon, 6 quick actions: download, open, reveal, view, copy path, pin)
- [ ] Image lightbox (full-res overlay, zoom/pan, arrow-key navigation, Esc close)
- [ ] PDF side panel viewer (right rail, `<iframe>` embedding, header with download/open/close)
- [ ] Code/text side panel viewer (syntax-highlighted, line numbers, shared panel with PDF)
- [ ] Inline audio player (play/pause, seek, speed selector, transcript toggle)
- [ ] Per-MIME-type rendering rules in message bubbles (thumbnail, preview, grid, etc.)
- [ ] Session files panel (📎 sidebar tab, `Ctrl+Shift+F` toggle, grouped by origin, search/filter/sort)
- [ ] Right-click context menu on file cards (all quick actions + "Copy download URL")

### Frontend — Remaining Pages
- [ ] Settings: general, providers, agent, plugins, web, memory, notifications, security, backup
- [ ] Plugin management: per-plugin config pages
- [ ] Memory explorer: full browser, entity explorer, audit timeline
- [ ] Web/browser settings: policy editor, cache admin, profile manager
- [ ] Sidebar polish: status indicators, pinned sessions, groups
- [ ] Global search (Cmd+K palette)
- [ ] Keyboard shortcut overlay
- [ ] Loading states, empty states, error states for all pages
- [ ] Responsive breakpoints

### Frontend — File Cleanup
- [ ] Storage dashboard (usage chart, quota indicator)
- [ ] Orphan file list with bulk actions
- [ ] Cleanup trigger button

### Build & Packaging
- [ ] npm build → optimized frontend bundle
- [ ] PyInstaller freeze → test standalone launch
- [ ] Inno Setup compile → test installer on clean VM
- [ ] Full end-to-end test: install → first-run wizard → chat → tools

### Tests
- [ ] `tests/unit/test_file_export.py` — preview, download, file tracking, open/reveal actions
- [ ] `tests/unit/test_session_files.py` — session files list endpoint (filter, sort, grouping)
- [ ] `tests/unit/test_file_cleanup.py` — orphan detection, quota, soft-delete
- [ ] `tests/integration/test_packaging.py` — frozen-mode path resolution
- [ ] `tests/e2e/test_installer.py` — install, launch, basic operations (manual or scripted)

---

## Testing Requirements

- File export: create file via agent → card appears with 6 quick actions → preview works → download works → open/reveal invoke OS commands.
- Inline media: images show lightbox with zoom/pan/nav. PDFs open in side panel. Code shows syntax-highlighted preview. Audio plays inline.
- Session files panel: lists all files grouped by origin → search/filter works → click scrolls to message → pin/unpin works.
- File cleanup: create orphans → cleanup detects → soft-delete → quota warning.
- Packaging: build → install on clean Windows → wizard → chat → tools → browser works.
- UI: all pages accessible, no broken links, consistent design.

---

## Definition of Done

- [ ] File cards in chat with 6 quick actions (download, open, reveal, view, copy path, pin)
- [ ] Inline media rendering: image lightbox, PDF side panel, code preview, audio player
- [ ] Session files panel (📎 sidebar, grouped by origin, search/filter/sort)
- [ ] Local-app actions: open file + reveal in Explorer endpoints working
- [ ] All UI pages and settings complete
- [ ] Global search operational
- [ ] File cleanup: orphan detection, quota, soft-delete lifecycle
- [ ] PyInstaller builds standalone app
- [ ] Inno Setup produces Windows installer (.exe)
- [ ] Installer tested on clean Windows machine
- [ ] Auto-update version check notification
- [ ] All tests pass
- [ ] **Phase 6 gate**: Application is production-ready, installable, and polished

---

## Risks & Notes

- **UI scope**: "Full UI build-out" is broad. Many pages will have basic implementations from earlier sprints. This sprint focuses on completing gaps and polishing consistency.
- **PyInstaller challenges on Windows**: hidden imports, DLL dependencies, and antivirus false positives are common. Budget time for debugging.
- **Installer size**: Bundle may be 300+ MB with all dependencies. Consider lazy downloads for large optional components (sentence-transformers model, Playwright browsers).
- **Testing on clean VM**: Critical for packaging validation. Use a Windows VM snapshot for repeatable testing.
- **Phase gate**: This is the final major gate. After this sprint, core Tequila is distributable.
