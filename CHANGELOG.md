# Changelog

All notable changes to Yukiyasha are documented here.

## [Unreleased]

## [0.3.0] - 2026-10-07

Workspace UI, the **Примавтодор** module with linked data, and the first version of the
**AI assistant** (your own key, no Yukiyasha data yet).

### Upgrading from 0.2.1
- `Yukiyasha.bat` notices the new `pyproject.toml` and updates the environment by itself.
- Vehicles saved by 0.2.1 (one `norm_per_100km`) are upgraded on read: both seasonal norms get the
  old value, waybills without a season count as summer. Nothing is lost; records are written in
  the new shape the next time they are saved.
- The assistant is off until you create `ai.env` (see the README). Existing data is untouched.
- Every API call that changes data now refuses a browser `Origin` other than the page's own; the
  bundled UI is unaffected, a page served from another origin or port can no longer call the API.
  Requests without an `Origin` header (curl, scripts) work as before.

### Added
- **Browser workspace**: sidebar (work, home, whole disk, assistant, system), breadcrumbs, folder
  navigation, name filter, text editor with Ctrl+S, file creation with automatic sub-folders,
  deletion with confirmation, unsaved-changes guard, deep links (`#d=…`, `#f=…`, `#system`),
  system page with runtime state and module manifests, light theme through
  `prefers-color-scheme`, phone layout; skip link, focus rings, `aria-current`, live regions,
  native `<dialog>`, `prefers-reduced-motion`.
- **Модуль Примавтодор** (`primavtodor`), ten sections under `projects/work/Примавтодор`, each with
  its own icon and colour: Путевые листы, Горюче-смазочные материалы, Сотрудники, Гараж, Табель
  (group "Учёт"); Договора, Счёт-оферта, Служебные записки, Приказы, Распоряжения ("Документы").
  - **Linked data**: a driver has a **fuel card with a number** and an **assigned vehicle**; a
    waybill references a driver and a vehicle (the driver's car and the vehicle's last odometer
    reading are suggested) and computes distance, fuel issued, actual consumption, norm by
    mileage and deviation, with warnings (another car, overrun above 10 %, driver without a card);
    a fuel record references a waybill and takes driver, vehicle and **card number** from it
    (cannot be forged by the client; a driver without a card cannot be fuelled); the **timesheet**
    is built from waybills plus manual marks (Я, В, ОТ, Б, К, ПР) with conflicts flagged.
  - **Summer / winter fuel norms** with one **Лето / Зима switch** (module page and every record
    page): changes the active norm of every vehicle, the season of all *open* waybills and the
    default for new ones; closed waybills keep their own season, so history is never recalculated.
    The season lives in `Примавтодор/settings.json` and follows the calendar (Nov–Mar = winter)
    until switched by hand.
  - **Integrity**: validated references, unique plate / card / personnel number / waybill number,
    records that others refer to cannot be deleted (fuel → waybill → driver → vehicle).
  - Records are plain readable JSON files, one per record, in the section folders; unreadable
    files are reported, not fatal. Forms and tables are generated from one schema.
  - API: `/api/primavtodor/schema`, `/sections`, `/records/{kind}[/{id}]`, `/timesheet`,
    `/timesheet/mark`, `/settings`, `/settings/season`; validation errors are `422` with a message
    per field. Deep links `#m=primavtodor&s=<section>`.
- **AI assistant** (`ai` module, "Помощник" page): a streamed chat with any OpenAI-compatible API
  by your own key (DeepSeek, Cloud.ru, OpenAI, local Ollama, ...), configured through
  `YUKIYASHA_AI_*` variables or `~/.yukiyasha/ai.env`. The key is never stored on the disk module,
  logged, returned by the API or shown in the UI, and is scrubbed from provider error texts. The
  persona (`ai/persona.md`, editable on the page) and conversations (`ai/chats/*.json`) are plain
  files on the disk; a failed request saves nothing. Limits: `max_tokens`, a context budget that
  trims old history, 8 000 characters per message, two concurrent answers, `https://` required
  except for `localhost`. **The assistant sees none of the Yukiyasha data yet.**
- `DiskModule.make_dir()` — idempotent directory creation with the same validation as every other
  disk operation.
- `util.js` with the UI's pure helpers and `node --test` unit tests, run in Fast CI.

### Changed
- the UI is a work tool instead of a landing page; all interface text is Russian; sizes, counts
  and plurals are formatted; design tokens and AA-level contrast; API errors are shown as clear
  Russian messages.
- vehicles have `norm_summer` and `norm_winter` instead of one norm (see *Upgrading*).

### Fixed
- a streamed response to a POST/PUT froze the server: after the request body was used up, the
  body-limit middleware kept answering `receive()` with empty request messages, so a streaming
  response waiting for the client to disconnect spun the event loop forever.
- `pip install .` / wheel builds failed with a duplicate-file error (redundant hatch
  `force-include`); CI now builds the wheel and checks that every UI file is packaged.
- a user file named like `.yukiyasha-<anything>` was hidden and silently deleted at startup; only
  the exact internal temp-file shape is treated as internal and such names are rejected.
- built-in project directories are protected by file identity (case-insensitive filesystems could
  bypass the old check); NTFS junctions cannot lead out of the disk root; overwriting a file keeps
  its permission bits.
- `DiskNotReadyError` and directory conflicts map to consistent HTTP statuses (503/409) through
  one shared mapper; module ids must be ASCII; runtime start/stop failures are logged.
- UI: opening the system page no longer asks to discard unsaved text; two confirm dialogs cannot
  stack; "create file" is locked while pending; phones narrower than ~390 px no longer scroll the
  page sideways.

### Security
- browser `Origin` must match the request's own scheme and host:port (other local apps on other
  ports are rejected too), and this now covers **every** API call that changes data, not only the
  disk API.
- the `testserver` host is no longer accepted in production.
- security headers on every response: `Content-Security-Policy` (no inline code, no framing),
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`; API responses are `no-store`,
  UI files `no-cache`.

### Known limitations
- permissions are still declarations, not enforced; there is no authentication or audit log;
- documents (orders, memos, offers) are plain folders without templates, nothing is exported or
  printed, waybills use a standard field set rather than an official form;
- the assistant has no memory, tools or data access and was verified against a test server only,
  not against a live provider; every message goes to the provider, so it is not offline.

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
