# Changelog

All notable changes to Yukiyasha are documented here.

## [Unreleased]

### Added
- **AI assistant** (`ai` module, "Помощник" page): a streamed chat with any OpenAI-compatible API
  by your own key (DeepSeek, Cloud.ru, OpenAI, local Ollama, ...). Address, model and key come from
  `YUKIYASHA_AI_*` variables or `~/.yukiyasha/ai.env`; the key is never stored on the disk module,
  logged, returned by the API or shown in the UI, and is scrubbed from provider error texts.
  - persona (`ai/persona.md`, editable on the page) and conversations (`ai/chats/*.json`) are
    plain files on the disk; a failed request saves nothing;
  - cost and safety limits: `max_tokens`, a context budget that trims old history, 8 000
    characters per message, two concurrent answers, `https://` required except for `localhost`;
  - API: `GET /api/ai/status`, `GET/PUT /api/ai/persona`, `GET /api/ai/conversations[/{id}]`,
    `DELETE /api/ai/conversations/{id}`, `POST /api/ai/chat` (server-sent events);
  - the assistant sees none of the Yukiyasha data yet; read-only tools come next.

### Fixed
- a streamed response to a POST/PUT request froze the server: after the request body was used up,
  the body-limit middleware kept answering `receive()` with empty request messages, so a
  streaming response waiting for the client to disconnect spun the event loop forever. It now
  hands the connection back to the real `receive()`; covered by a regression test.

### Added
- **Summer and winter fuel norms.** Every vehicle has two norms (`norm_summer`, `norm_winter`,
  l per 100 km) instead of one. A single **Лето / Зима switch** (in the headers of the module
  page and of every record page) changes everything at once:
  - the "Действует" norm shown for every vehicle;
  - the season of every **open** waybill (closed waybills keep the season they were issued in, so
    switching never rewrites history or the deviation of finished trips);
  - the default season of new waybills.
  Each waybill stores its own season, shown as a badge and editable in the form; its norm,
  deviation and overrun warning are computed with the norm of that season. A vehicle without a
  norm for the season is reported ("Для машины не задана норма на сезон …") instead of silently
  using the other season's value.
- The season is stored in `Примавтодор/settings.json` and survives restarts. Until someone
  switches it by hand it follows the calendar (November–March = winter), marked as
  `source: "calendar"`. API: `GET /api/primavtodor/settings`, `PUT /api/primavtodor/settings/season`.

### Changed
- vehicle records written by the previous version (one `norm_per_100km`) are upgraded on read:
  both seasonal norms get the old value; waybills without a season count as summer.

### Added
- **Путевые листы** — a new Примавтодор section (10 sections now) and, together with
  **ГСМ**, **Сотрудники**, **Гараж** and **Табель**, real linked data instead of plain folders:
  - a driver (employee) has a **fuel card with a number** and an **assigned vehicle**;
  - a waybill references a driver and a vehicle (the driver's car is suggested, odometer starts
    from the vehicle's last reading) and computes distance, fuel issued, actual consumption,
    norm by mileage and the deviation; it warns about another car, an overrun above 10 % and a
    driver without a card;
  - a fuel record (ГСМ) references a waybill; driver, vehicle and the **card number** are taken
    from it and cannot be forged by the client; a driver without a card cannot be fuelled;
  - the **timesheet** is built from waybills (a day with a waybill is a working day) plus manual
    marks (Я, В, ОТ, Б, К, ПР) that override the automatic ones; conflicts are flagged;
  - relations are checked: unknown or wrong references are rejected, unique plate / card /
    personnel number / waybill number, and records that other records refer to cannot be deleted
    (driver, vehicle, waybill) — delete in the order fuel → waybill → driver → vehicle;
- records are plain readable JSON files, one per record, in the section folders on the disk
  (e.g. `Путевые листы/wb-1a2b3c4d.json`); unreadable files are reported, not fatal;
- REST API `/api/primavtodor/schema`, `/records/{kind}[/{id}]`, `/timesheet`,
  `/timesheet/mark`; validation errors are `422` with a message per field;
- UI pages: list with search, create/edit/delete forms generated from the schema (selects for
  references, auto-fill, live fuel-card preview), computed details, and the timesheet grid with
  month navigation and a mark dialog; deep links `#m=primavtodor&s=<section>`.

### Security
- every API call that changes data now requires a same-origin `Origin` (previously only the
  disk API did); reads stay open.

### Added
- own icon and colour for each Примавтодор section (calendar, people, garage, drop, contract,
  receipt, envelope, seal, megaphone): a tinted tile on the module cards and a coloured icon on
  the section folders in the file list; colours are tuned separately for dark and light themes;
  icons and hues are derived from the stable section id (`i-sec-<id>`, `[data-sec="<id>"]`) and
  a test checks that every backend section has both;
- module **Примавтодор** (`primavtodor`): registered after the disk, it creates and owns
  `projects/work/Примавтодор` with section folders — Путевые листы, Горюче-смазочные материалы,
  Сотрудники, Гараж, Табель (group "Учёт"); Договора, Счёт-оферта, Служебные записки,
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
