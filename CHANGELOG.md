# Changelog

All notable changes to Yukiyasha are documented here.

## [Unreleased]

### Added
- **Quick booking from one line** in the schedule: type what you hear on the phone, «Веровский
  7-9 командировка Находка», «Игорь с 5 по 7», «хино 12-13 ремонт» or «завтра», and the line is
  read into a driver, a car, dates and a type. The car comes from the driver (and the driver from
  the car) when only one is named, declensions and Latin/Russian makes are understood, an
  ambiguous name is offered as choices and never guessed. A preview shows overlaps; Enter again
  books it. API: `POST /api/primavtodor/bookings/parse`.
- **Summary for today** at the top of the Примавтодор page: who is away, who leaves tomorrow,
  drivers on leave or sick (from the timesheet), overlaps, waybills left open, statements waiting
  in the inbox and the open findings of the month (the previous month too during its first ten
  days); each line opens the place to act. API: `GET /api/primavtodor/briefing`.
- **Statement inbox:** drop the provider's .xls/.xlsx into «ГСМ/Входящие» and it is loaded when
  the page opens (or from the summary). A file that loaded cleanly moves to «Обработано»; one with
  operations that could not be matched stays with the reasons. Nothing is created twice. The disk
  module gained `read_bytes` (20 MiB) and `move` (never overwrites) for it.
- **График машин** at the top of the Примавтодор page: a car × day grid showing who has which
  car and for how long. A booking is a driver, a car, *с … по …* and a type (business trip, car
  taken for the whole day, or repair/service); there is no "who asked" field. Drag over free days
  to book, click a bar to edit or delete, a strip shows who is away now and who leaves this week,
  weekends and holidays come from the production calendar, overlaps on a car or a driver are
  outlined in red (never forbidden), and the booking dialog lists the cars that are free on the
  chosen dates. Counters show trips under way and how many cars and drivers are free, and a
  **«Кто свободен»** panel lists the cars and drivers without work on a chosen day (today,
  tomorrow or any date, or click a day in the grid) with how long each stays free; a click on a
  card starts a booking for them. The schedule reads the timesheet: a driver marked *Б* (sick) or *ОТ* (leave) is not offered as free, appears in a «Табель» strip with the end date, and a booking over such days is flagged.
  API: `/api/primavtodor/bookings`.
- **Cars and cards move between drivers, the history is kept in the employee.** Change a
  driver's car or fuel card at any time (today the Hino, tomorrow the Lexus; a lost card is
  detached and another attached) with an optional *Смена … действует с* date; the employee shows
  the history of cars and cards. A statement fill-up is matched to the card holder *of that day*
  and to the car the driver had *that day*, so a change never rewrites the past. Existing
  employees keep working as before (one open interval).
- **Manual fill-ups:** *Оплата*: by fuel card (default), cash, or without a card. Cash and
  card-less fill-ups need no card and no driver, only a car; they count for the car in the month's
  calculations and are never mistaken for card operations of a statement.
- **The remainder stays with the car.** The fuel left after a car's last closed waybill is shown on
  the vehicle and becomes the starting remainder of the next waybill of that car, whoever drives
  (carried over by the server when the field is empty, and filled in by the form).
- **Diesel and petrol are never added together**: the calculations are totalled per fuel kind
  (diesel, petrol, gas) and show the kind per car.

### Changed
- **Fill-ups follow the fuel card, not the waybill.** A fuel record no longer needs a waybill:
  the card belongs to the driver and the driver to a car, so a statement fill-up with no waybill
  on that day is loaded against the driver's car (the car of that day's waybills, else the car
  assigned to the driver, else the only car of the driver's waybills that month). Only a fill-up
  whose driver or car cannot be told is left out, with the reason. The fuel form gets *Водитель*
  and *Машина* (the car is filled in from the driver); with a waybill both still come from it.
- The month calculations, the fuel card and the analysis count the month's fill-ups **per car**
  by the card operations (by date), with or without a waybill. A car with fill-ups but no
  waybills in the month is listed too, carrying over its last remainder, and the control flags it.

### Added
- **Month calculations per vehicle** (in *Закрытие месяца* and as `Расчёты по машинам <месяц>.csv`
  in the zip): fuel at the start (the first waybill of the month), fuel at the end (the last
  closed waybill), mileage by the waybills and by the odometer (first departure reading to last
  return reading, so mileage without a waybill shows), fill-ups, actual consumption
  (start + fill-ups - end), consumption by the norm (each waybill with its own season's rate),
  the deviation in litres and percent, and the same per driver. A note names what does not add
  up (mileage without waybills, remainders that do not chain, open waybills, a missing norm).
  API: `GET /api/primavtodor/month/{ГГГГ-ММ}/calculations`.
- **Closing of the month** (*Закрытие месяца* on the Примавтодор page): one screen with the steps
  (waybills closed, fill-ups loaded, control, timesheet norm), the findings and a single
  *Скачать всё за месяц (.zip)* with the Т-12 timesheet, the fuel analysis, a fuel card per
  vehicle and the findings as a spreadsheet-friendly CSV.
- **Control of fuel use** (rules, no guessing): overrun above 10% (error above 25%), suspiciously
  low or zero consumption, odometer going back or an unrecorded gap between waybills, fuel
  remainder not matching the previous waybill, wrong fuel type, a fill-up larger than the tank
  (new vehicle field *Объём бака*), fill-up date different from the waybill, probable duplicate
  fill-ups, unusual prices, a driver on two cars on one day, old unclosed waybills, work on a
  day off. A finding you have looked at can be *accepted* (and restored); accepted ones stop
  counting.
- The assistant can read the month's review (`primavtodor_month_review`, read only, audited).
- **Printable waybill** (form № 3, light vehicle): a *Печать* button in the waybill form
  downloads the organisation's own blank, filled (both the waybill and its copy). New fields:
  driver's licence number and class, vehicle garage number and waybill form kind, departure and
  return times. Organisation, signers and the control wording are set in *Данные для печати*.
  Other forms (№ 3 спец., № 4-П) are refused with a clear message until they are added.
- **Fuel-card statement import** (ГСМ → *Загрузить выписку*): reads the provider's `.xls`/`.xlsx`,
  matches every fill-up card -> driver -> that driver's waybill on the date, shows a preview with
  the reason for everything it cannot match, and never loads the same fill-up twice.
- **Monthly fuel card** (*Карточка расхода ГСМ*) from the vehicle form: a sheet per driver in the
  organisation's own card, formulas stay live.
- **Monthly «Анализ расхода ГСМ»** (ГСМ → *Анализ за месяц*): a row per vehicle, diesel and petrol
  columns, totals, notes for open waybills and overruns above 10%.
- **Production calendar of Russia for 2026 and 2027** (*Календарь* on the timesheet page; the year
  is selectable): days off, holidays, transfers and shortened days from the open xmlcalendar.ru
  data (government decrees), month norms in days and hours. The timesheet paints holidays and
  transfers, marks a waybill on a day off as **РВ** and shows the month norm. Other years fall
  back to plain weekends. Check the 2027 data against the final decree when it is published.
- **Timesheet on your form Т-12** (*Табель Т-12 (.xlsx)*): marks and hours per employee, days off
  painted from the calendar, the form's own totals stay live, more than 15 people repeat the
  block. Print settings gained «Структурное подразделение».
- Dependencies: `openpyxl` (filling the workbooks) and `xlrd` (reading `.xls` statements).
- The assistant now speaks as **Юкияша** by default: a bundled character pack (persona, honesty
  rules and 400 example replies in 20 categories). A few replies that fit the message are shown to
  the model as a tone sample (never sent as-is, never repeated within the last 30 answers, none for
  messages about real danger). A persona file still equal to the 0.3.0 default is upgraded on
  start; an edited persona is left alone.

## [0.8.0] - 2026-10-07

Documents found by Юкияша are now first-class visual objects in the conversation instead of raw
file paths.

### Added
- Read-only document metadata tool for the five Примавтодор document sections.
- Structured document refs persisted on assistant messages and emitted during streaming.
- Rich mini-document cards with section, human-readable title, format, size and local preview.
- One-click opening into the existing Yukiyasha file editor; the disk path stays hidden.
- Pure `documents.js` presentation helpers with Node tests.

### Privacy
- Document contents are not sent to the AI provider merely to build the card or preview.
- The provider receives document metadata from the list tool; text preview is fetched locally by
  the browser through the existing protected Disk API.
- Default persona instructs the assistant not to print raw document paths or turn them into links.

## [0.7.0] - 2026-10-07

Proposal review is now available directly inside the assistant conversation.

### Added
- In-chat proposal cards with operation, target, reason, status and field-level diff.
- Approve/reject controls only inside pending proposal cards; no new global navigation actions.
- Immutable `before` snapshot for update/delete proposals so the browser can show exact old/new values.
- Pure `proposals.js` UI helpers with Node tests for create/update/delete diffs.
- JavaScript syntax checks for assistant/proposal UI in Fast CI.

### Changed
- Assistant privacy text now accurately explains read-only Примавтодор tool disclosure and proposal approval.
- Recent applied/rejected/stale proposals stay visible in the assistant as history without action controls.

## [0.6.0] - 2026-10-07

AI-assisted Примавтодор mutations now go through a concrete proposal and separate human approval.

### Added
- New **Предложения** module with scoped `proposals/**` storage and lifecycle health.
- Validated create/update/delete proposals for structured Примавтодор records.
- Partial update proposals are expanded to a full normalized target state before persistence.
- Source fingerprints for update/delete proposals; changed targets become `stale` on approval.
- Human proposal API: list/get, approve and reject.
- Assistant capability `proposal.create` and the `primavtodor_propose_change` tool.
- Dry-run `Records.validate()` for schema/reference/uniqueness checks without mutation.
- Migration of an untouched v0.5 default persona to proposal-aware rules.

### Security
- The assistant has no direct Примавтодор write/delete capability and no proposal apply/reject tool.
- Proposal execution re-checks the current user message for mutation intent.
- Approval/rejection uses the existing same-origin mutation boundary.
- Completed proposals are one-shot; stale proposals never overwrite newer record state.
- Proposal audit events omit the proposed business payload.

### Changed
- Runtime module order is now Disk → Memory → Примавтодор → Proposals → Assistant.
- Project architecture now treats business writes as a two-phase propose/approve workflow.

## [0.5.0] - 2026-10-07

Long-term assistant memory behind the same permission and audit boundaries as business tools.

### Added
- New **Memory** module with scoped `memory/**` storage, lifecycle health and one JSON file per
  durable memory item.
- Exact-text deduplication, local token-overlap retrieval, 2,000-character item limit and
  500-item store limit.
- AI capabilities `memory.read`, `memory.write` and `memory.delete` through `MemoryAccess`.
- Guarded AI tools `memory_search`, `memory_remember` and `memory_forget`.
- Transparent memory API: list, search, add and remove entries.
- Migration of an untouched v0.4 default persona to the new memory-aware rules.

### Security
- Memory write/delete tools are advertised and executed only for explicit remember/forget intent
  in the current user message.
- Credential-like material is rejected before long-term persistence.
- Memory audit records omit both stored text and search queries.
- The assistant still has no create/update/delete capability over Примавтодор.

### Changed
- Runtime module order is now Disk → Memory → Примавтодор → Assistant.
- Assistant tool status is `guarded` rather than globally read-only because memory mutations are
  allowed only under the explicit-intent boundary.

## [0.4.0] - 2026-10-07

Permissions, audited read-only Примавтодор tools for the assistant, and the Yukiyasha character.

### Added
- Runtime-owned `PermissionBroker` with default-deny module capability checks.
- Path-scoped `DiskAccess` views: Примавтодор is confined to its project tree; AI to `ai/**`.
- Explicit `primavtodor.read` capability and a read-only facade for records, timesheet and settings.
- Four assistant tools: list/get records, timesheet and settings; no write/delete tools.
- Sensitive-field masking before tool results leave Yukiyasha.
- Persistent audit events under `system/audit/YYYY-MM-DD/*.json`; business payloads and API keys
  are not copied into the audit record.
- Standard OpenAI-compatible tool planning with fallback to ordinary chat for providers that reject
  the standard `tools` request.
- The assistant now speaks as **Юкияша** by default using the bundled character pack and tone
  examples; an untouched older default persona is upgraded automatically.

### Security
- Module-to-module data access is permission-checked and path-scoped.
- AI business access is read-only and fail-closed: disclosure requires a successful audit write.
- Phone numbers, personnel numbers and fuel-card/card values are masked before provider transfer.
- Tool calls are capped per turn and arguments are validated against a small allow-list.

### Changed
- The default persona now accurately states that read-only Примавтодор tools are available.
- Project documentation now describes the capability boundary, masking and audit model.

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
