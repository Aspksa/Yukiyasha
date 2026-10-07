# Yukiyasha Architecture

## Module foundation (v0.3.0)

Yukiyasha is a modular monolith with explicit runtime, module and transport boundaries.

### Layers

1. **Core**
   - owns runtime lifecycle and the module registry;
   - coordinates degraded/ready/stopped state;
   - does not depend on FastAPI or browser code.

2. **Application configuration**
   - immutable environment-driven settings;
   - service identity and stable storage paths;
   - package version comes from installed package metadata.

3. **Modules**
   - explicit manifest;
   - registered/ready/failed/stopped lifecycle;
   - health snapshots;
   - declared permissions;
   - no dependency on the web layer.

4. **Web/API**
   - transport and HTTP safety boundary;
   - request body, Host and same-origin validation;
   - security headers (CSP without inline code, no framing, no MIME sniffing) and cache rules;
   - synchronous filesystem endpoints run through FastAPI's threadpool.

### Dependency rule

```text
Browser -> Web/API -> Core -> Module Registry -> Modules
                    -> Configuration
```

Core and modules never import from Web/API.

## Модуль «Помощник» (ИИ по ключу)

`modules/ai` depends only on the disk module. A `ChatProvider` (`open(messages) -> chunks`) hides
the vendor: `OpenAICompatibleProvider` speaks the common `/chat/completions` streaming protocol
over the standard library, so there is no extra dependency and any compatible service (cloud or
local) works. Settings (`config.AiSettings`) come from the environment or `ai.env`; the key is
excluded from `repr`, never persisted and scrubbed from errors.

- one turn = validate → build the context (persona + the history that fits the budget + the new
  message) → connect (errors surface as HTTP statuses before any streaming starts) → stream
  server-sent events → save the conversation only when the whole answer has arrived;
- a bounded semaphore limits concurrent answers; the slot is released when the stream ends or
  the response is torn down;
- the module reads no business data. Giving it read-only tools (waybills, fuel, timesheet) is a
  separate step that needs the permission boundary first.

## Модуль Примавтодор

Work-project module. It depends only on the disk module (never on the web layer), is registered
right after it (modules start in registration order and stop in reverse) and owns the folder
`projects/work/Примавтодор`. Each section is one sub-folder; all data lives on the disk and the
module reaches it only through the disk's public API.

| Group | Sections (in data-flow order) |
| --- | --- |
| Учёт | Путевые листы → Горюче-смазочные материалы → Сотрудники → Гараж → Табель |
| Документы | Договора, Счёт-оферта, Служебные записки, Приказы, Распоряжения |

Section ids are ASCII (`waybills`, `fuel`, `employees`, `garage`, `timesheet`, `contracts`,
`invoice_offer`, `memos`, `orders`, `directives`); titles and folder names are Russian. The module id is
`primavtodor`. Documents are plain text files addressed by a single file name inside a section;
the disk still validates every path. Declared permissions (`disk.read`, `disk.write`,
`disk.delete`) are metadata until the central permission boundary exists.

### Linked records

`schema.py` is the single source of truth for fields, relations and list columns; the backend
validates against it and the browser renders forms and tables from `/api/primavtodor/schema`.

```text
employee (driver) ── vehicle_id ──▶ vehicle              fuel_card_number (unique)
waybill ── driver_id ──▶ employee, ── vehicle_id ──▶ vehicle
fuel    ── waybill_id ──▶ waybill   (driver, vehicle, card number derived and stored)
timesheet = waybills (auto "Я") + manual marks per month
```

- one JSON file per record in the section folder; all I/O goes through the disk's public API;
- cross-record rules live in `records.py` (driver flag, closing a waybill, card required for
  fuel, uniqueness); deleting a referenced record is refused (`409`);
- computed values (distance, consumption, norm, deviation, amount) are derived on read and never
  stored, so they cannot go stale; the fuel record keeps the card number it was issued on;
- the timesheet stores only manual marks (`Табель/<ГГГГ-ММ>.json`);
- fuel norms are seasonal: a vehicle has `norm_summer` and `norm_winter`; a waybill stores its own
  `season` and is computed with that season's norm. The module-wide switch
  (`Примавтодор/settings.json`) only changes the *active* norm shown for vehicles, the default for
  new waybills and the season of open waybills, never of closed ones (history stays exact);
- records written by earlier versions are upgraded in memory when read (`RecordStore._upgrade`)
  and persisted in the new shape the next time they are saved.

### Printing, import and reports

`printing.py`, `fuelcard.py` and `fuelreport.py` fill the organisation's own blank workbooks
(`forms/*.xlsx`, bundled with the package, no personal data in them) with `openpyxl`; they are
pure (plain values in, `.xlsx` bytes out). The waybill sheet holds the form twice side by side, so
every value is written in both halves. The monthly card and the report keep live `SUM` formulas.
`statement.py` reads the fuel-card provider's `.xls`/`.xlsx` (Windows-1251 for `.xls`);
`fuel_import.py` matches each fill-up card -> employee -> the driver's waybill on that date,
reports what it cannot match and skips what is already on file. Print settings (organisation,
signers, control wording) live next to the season in `settings.json`.

Note: a failing module start rolls back every module started before it (registry semantics), so a
file (not a folder) named like a section degrades the whole runtime.

## Диск Yukiyasha

Default root:

```text
~/.yukiyasha/disk
```

Override with `YUKIYASHA_DISK_DIR`.

Security and consistency invariants:
- absolute paths and traversal outside the disk root are rejected;
- symlink escapes are rejected;
- replacement writes use a temporary file in the destination directory and `os.replace`;
- no-overwrite publication uses an atomic hard-link operation;
- UTF-8 bytes are read/written directly so line endings are never translated by the OS;
- text API reads/writes are capped at 1 MiB;
- HTTP request bodies are capped at 2 MiB before application parsing;
- internal temporary files are recognised by exact name shape, never by prefix alone;
- built-in project directories are protected by file identity, not by path spelling;
- the fully resolved path (not only symlink flags) must stay inside the root;
- deleting the disk root is forbidden;
- permission, conflict, invalid-path and size failures are represented explicitly.

Declared permissions remain metadata in v0.3.0:
- `disk.read`
- `disk.write`
- `disk.delete`

The next architecture step is enforcing those declarations through a central permission boundary.
