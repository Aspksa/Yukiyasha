# Yukiyasha

Yukiyasha is a modular AI-oriented platform foundation with a local web interface.

## Current version

**v0.3.0 — Workspace, Примавтодор and AI assistant**

The current release provides:
- modular Python core and module registry with explicit lifecycle and health;
- sandboxed local **Диск Yukiyasha** and a browser workspace (file manager, editor, system page);
- the **Примавтодор** module: waybills, fuel (ГСМ), employees with fuel cards and vehicles, garage,
  timesheet, seasonal fuel norms with one summer/winter switch, document folders;
- an **AI assistant** you connect with your own API key (see below);
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
  the conversation. The assistant currently sees none of the Yukiyasha data (waybills, employees,
  documents). Do not paste personal data you would not send to that provider.
- By default the assistant speaks as Юкияша (a bundled character pack); examples of her tone are
  added to the prompt, so the request is a little longer. Replace the persona any time.
- The persona (`ai/persona.md`) and the conversations (`ai/chats/chat-*.json`) are plain files on
  the disk; edit the persona on the page ("Личность") at any time.
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
  modules/     module runtime and modules
    disk/      Диск Yukiyasha
  web/         FastAPI application, middleware and browser UI
tests/         isolated automated tests
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_STATE.md](PROJECT_STATE.md).
