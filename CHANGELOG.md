# Changelog

All notable changes to Yukiyasha are documented here.

## [Unreleased]

### Added
- own icon and colour for each Примавтодор section (calendar, people, garage, drop, contract,
  receipt, envelope, seal, megaphone): a tinted tile on the module cards and a coloured icon on
  the section folders in the file list; colours are tuned separately for dark and light themes;
  icons and hues are derived from the stable section id (`i-sec-<id>`, `[data-sec="<id>"]`) and
  a test checks that every backend section has both;
- module **Примавтодор** (`primavtodor`): registered after the disk, it creates and owns
  `projects/work/Примавтодор` with nine section folders — Табель, Сотрудники, Гараж,
  Горюче-смазочные материалы (group "Учёт"); Договора, Счёт-оферта, Служебные записки,
  Приказы, Распоряжения (group "Документы"). Folders deleted by the user are recreated on
  startup; existing files are never touched;
- module API on top of the disk: section summaries with file counts, and list/read/write/delete
  of documents per section (single plain file names, all disk validation still applies);
- `GET /api/primavtodor/sections` and a module page in the UI with a card per section that
  opens the folder in the file manager; the sidebar highlights the module for everything
  inside its folder; `#m=primavtodor` deep link;
- `DiskModule.make_dir()` — idempotent directory creation with the same path validation as
  every other disk operation.

### Fixed
- phones narrower than ~390 px no longer scroll the whole page sideways (the sidebar nav
  strip scrolls instead);
- `pip install .` / wheel build failed with a duplicate-file error (redundant hatch
  `force-include` of the static UI); CI now builds the wheel and checks the packaged UI;
- a user file named like `.yukiyasha-<anything>` was hidden and silently deleted at startup;
  only the exact internal temp-file shape (`.yukiyasha-` + 8 characters) is treated as internal,
  and such names are rejected for user files;
- built-in project directories are protected by file identity, so a differently spelled path
  (case-insensitive filesystems) can no longer delete them;
- NTFS junctions are no longer followed out of the disk root (resolved path is checked);
- overwriting a file keeps its permission bits;
- `DiskNotReadyError` and directory conflicts map to consistent HTTP statuses (503/409)
  through one shared mapper instead of four copies of the same `except` chain;
- module ids must be ASCII;
- runtime start/stop failures are logged instead of being swallowed silently;
- UI: visiting the system page no longer asks to discard unsaved text; returning to the same
  file keeps the sidebar highlight; two confirm dialogs can no longer be stacked; the
  "create file" button is locked while the request is running.

### Security
- browser Origin must match the request's own scheme and host:port (other local apps on
  different ports are rejected, not only other sites);
- the `testserver` host is no longer accepted in production (`extra_allowed_hosts` for tests);
- security headers on every response: `Content-Security-Policy` (no inline code, no framing),
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`;
- API responses are `Cache-Control: no-store`, UI files are `no-cache` (always revalidated).

### Added (workspace UI)
- `util.js` with the UI's pure helpers and `node --test` unit tests, run in Fast CI;
- browser workspace: sidebar navigation (work, home, whole disk, system), breadcrumbs,
  folder navigation, name filter, text editor with save (Ctrl+S), file creation with
  automatic sub-folders and deletion with confirmation;
- system page with runtime state and module manifests/permissions;
- light theme through `prefers-color-scheme`, responsive layout for phones;
- unsaved-changes guard, deep links through the URL hash (`#d=…`, `#f=…`, `#system`).

### Changed
- UI is now a work tool instead of a landing page: files first, diagnostics on a separate page;
- all interface text is Russian; sizes and counts are formatted and pluralised;
- design tokens (CSS variables) and AA-level text contrast;
- API errors are translated into clear Russian messages.

### Accessibility
- skip link, focus rings, `aria-current`, live regions for status and toasts,
  native `<dialog>` for modals, `prefers-reduced-motion` support.

## [0.2.1] - 2026-10-07

### Fixed
- atomic file replacement and race-safe `overwrite=false`;
- exact newline preservation on Windows and Linux;
- precise disk-domain errors and consistent HTTP status mapping;
- non-empty directory handling no longer masks unrelated OS errors;
- missing disk directories now return 404;
- module FAILED state, startup rollback and complete shutdown attempts;
- runtime start timestamp now reflects actual starts and restarts;
- disk endpoints no longer block the event loop;
- web tests no longer touch the real Yukiyasha disk;
- Windows launcher port fallback and paths containing `!`;
- launcher dependency synchronization after `pyproject.toml` changes.

### Security
- 2 MiB HTTP request-body cap before JSON parsing;
- Host validation against DNS rebinding;
- browser Origin validation for disk API requests;
- symlink escape protection is covered by tests.

### Changed
- default disk root is now `~/.yukiyasha/disk`;
- package version is read through `importlib.metadata`;
- Windows CI avoids installing the project twice.

## [0.2.0] - 2026-10-07

### Added
- explicit module manifests, registry and lifecycle;
- module health snapshots and `GET /api/modules`;
- first module: **Диск Yukiyasha**;
- sandboxed file listing, UTF-8 read/write and delete API;
- configurable disk root through `YUKIYASHA_DISK_DIR`;
- traversal, absolute-path and symlink-listing protections;
- 1 MiB text read/write safety limit;
- module and disk API tests.

## [0.1.0] - 2026-10-07

### Added
- modular Python core and runtime lifecycle;
- environment-driven configuration;
- FastAPI application and health/runtime API;
- responsive dark web dashboard;
- automated runtime and API tests;
- Ruff linting and cross-platform GitHub Actions CI;
- architecture and project-state documentation.
