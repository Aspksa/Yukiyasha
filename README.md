# Yukiyasha

Yukiyasha is a modular AI-oriented platform foundation with a local web interface.

## Current version

**v0.8.0 — Rich document cards in chat**

The current release provides:
- modular Python core and module registry with explicit lifecycle and health;
- sandboxed local **Диск Yukiyasha** and a browser workspace (file manager, editor, system page);
- the **Примавтодор** module: waybills, fuel (ГСМ), employees with fuel cards and vehicles, garage,
  timesheet, seasonal fuel norms with one summer/winter switch, document folders;
- an **AI assistant** with audited read access, long-term memory, rich document cards and human-approved write proposals;
- FastAPI web/API layer, automated tests and two-tier CI.

## Requirements

- Python 3.11+

## Quick start

### Windows — one click

Double-click `Yukiyasha.bat`.

The launcher:
- verifies Python 3.11+;
- prepares and validates `.venv`;
- synchronizes dependencies when `pyproject.toml` changes;
- checks ports and detects an already running Yukiyasha;
- starts the server on `127.0.0.1`;
- opens the browser after the health endpoint becomes available.

### Manual launch

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn yukiyasha.web.app:app --reload
```

Open: http://127.0.0.1:8000

## Диск Yukiyasha

Default storage directory is stable and does not depend on the process working directory:

```text
~/.yukiyasha/disk
```

Optional custom location:

```bat
set YUKIYASHA_DISK_DIR=D:\YukiyashaData
Yukiyasha.bat
```

The disk API supports:
- `GET /api/modules`
- `GET /api/disk?path=`
- `GET /api/disk/file?path=`
- `PUT /api/disk/file`
- `DELETE /api/disk/file?path=`

Safety properties:
- writes are published atomically;
- `overwrite=false` uses atomic no-replace semantics;
- UTF-8 text is capped at 1 MiB;
- HTTP request bodies are capped at 2 MiB before JSON parsing;
- line endings are preserved byte-for-byte;
- absolute paths, traversal and symlink escapes are rejected;
- untrusted Host and browser Origin values are rejected for the local API.

The browser UI is a small workspace on top of the disk API: sidebar sections (work, home, whole
disk, system), breadcrumbs, a text editor (Ctrl+S), file creation and deletion, and a system page
with module manifests. It supports light/dark themes and phones. Binary files and module
permission controls are not exposed yet.

## AI assistant (your own key)

The **Помощник** page is a chat with any OpenAI-compatible API (DeepSeek, Cloud.ru, OpenAI, a
local Ollama, ...). Nothing is configured by default. Create `ai.env` in the Yukiyasha home folder
(`%USERPROFILE%\.yukiyasha\ai.env` on Windows, `~/.yukiyasha/ai.env` elsewhere) and restart:

```text
YUKIYASHA_AI_BASE_URL=https://api.example.com/v1   # address of the OpenAI-compatible API
YUKIYASHA_AI_MODEL=model-name
YUKIYASHA_AI_API_KEY=your-key
# optional: YUKIYASHA_AI_NAME=Саюри   YUKIYASHA_AI_MAX_TOKENS=2048   YUKIYASHA_AI_TIMEOUT=120
```

Take the exact address and model name from your provider's documentation. The same variables work
as ordinary environment variables (they win over the file). `http://` is accepted only for
`localhost` (a local model; give it any non-empty key); everything else must be `https://`.

- The key lives only in that file or the environment: it is never stored on the disk module,
  written to a log, returned by the API or shown in the UI, and it is scrubbed from error texts.
- **Every message is sent to the provider** together with the persona and the earlier messages of
  the conversation. For questions about Примавтодор, a compatible provider can request read-only
  local tools for waybills, fuel, employees, vehicles, timesheets, settings and document
  metadata. Tool results are also sent to the provider. **Document contents are not sent merely
  to render a card**: card previews are loaded locally by the browser from Yukiyasha. Phone
  numbers, personnel numbers and fuel-card numbers are masked
  before they leave Yukiyasha. Providers that do not support standard OpenAI tools fall back to
  ordinary chat.
- By default the assistant speaks as Юкияша (a bundled character pack); examples of her tone are
  added to the prompt, so the request is a little longer. Replace the persona any time.
- The persona (`ai/persona.md`) and the conversations (`ai/chats/chat-*.json`) are plain files on
  the disk; edit the persona on the page ("Личность") at any time.
- Direct Примавтодор access stays read-only. For mutation requests the assistant can only create
  a validated **proposal**. A proposal changes nothing until a person separately approves its id
  through the local API. Update/delete proposals capture the source record fingerprint and become
  `stale` instead of overwriting data that changed after the proposal was created.
- Proposal lifecycle is transparent through the local API and appears directly in the assistant
  conversation as review cards with old/new diff, status, and local approve/reject controls.
- Documents found by the assistant are shown as **mini-document cards**, not raw paths or links:
  human title, section, format, size, local text preview and an «Открыть» action into the existing
  Yukiyasha editor. The document path stays internal to the UI.
- Tool disclosures and proposal lifecycle events are written to
  `system/audit/YYYY-MM-DD/*.json` without copying the business payload itself.
- **Long-term memory** is separate from chat history and stored as JSON under
  `memory/items/*.json`. The assistant can add or remove a memory only after an explicit
  remember/forget request. Sensitive credential material is rejected. Memory actions are audited
  without copying memory text or search queries into the audit event.
- Memory can also be inspected through `GET /api/memory`, searched with
  `GET /api/memory/search?q=...`, added with `POST /api/memory`, and removed with
  `DELETE /api/memory/{id}`.
- Cost control: answers are limited by `MAX_TOKENS`, a conversation sends only the most recent
  history that fits the context budget, and at most two answers are produced at a time.

## Printing and fuel reports (Примавтодор)

- **Waybill:** open a waybill → *Печать (.xlsx)* gives the filled form № 3. Fill the organisation,
  signers and the wording of the control once in *Данные для печати* (waybills page).
- **Fuel statement:** ГСМ → *Загрузить выписку* (`.xls`/`.xlsx` from the card provider). A preview
  shows what will be loaded and what cannot be matched; loading the same file again adds nothing.
  A fill-up is matched through the card number to the driver and to that driver's waybill on the
  date of the fill-up.
- **Monthly fuel card:** open a vehicle → choose the month → *Скачать*: a sheet per driver.
- **Closing of the month:** on the Примавтодор page, *Закрытие месяца* shows what is done and what
  does not add up (overruns, odometer and fuel gaps, wrong fuel, fill-ups over the tank volume —
  set it on the vehicle, unclosed waybills, ...). Accept a finding you have checked; download the
  whole month (timesheet, analysis, fuel cards, findings) as one zip.
- **Calculations:** *Закрытие месяца* also shows, per vehicle, the fuel at the start (first
  waybill) and at the end (last closed waybill), the mileage by waybills and by the odometer, the
  actual consumption (start + fill-ups − end), the consumption by the norm and the deviation.
- **Timesheet:** the *Календарь* button shows the production calendar of Russia for 2026 and 2027
  (choose the year); holidays and transfers are painted in the timesheet and the month norm is
  shown. *Табель Т-12 (.xlsx)* fills your form. Calendar data: open data of xmlcalendar.ru
  (government decrees); verify 2027 against the final decree.
- **Monthly analysis:** ГСМ → *Анализ за месяц*: one row per vehicle with diesel/petrol columns.

## Quality checks

```bash
ruff check .
pytest
node --test tests/js/util.test.js   # UI helpers, needs Node 20+
```

## Project structure

```text
src/yukiyasha/
  core/        application runtime
  modules/     module runtime, permissions and modules
    disk/      Диск Yukiyasha + scoped module access
    ai/        assistant + guarded tool registry
    memory/    explicit long-term memory
    proposals/ human-approved mutation proposals
  web/         FastAPI application, middleware and browser UI
tests/         isolated automated tests
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_STATE.md](PROJECT_STATE.md).
