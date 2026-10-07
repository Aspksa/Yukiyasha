# Yukiyasha

Yukiyasha is a modular AI-oriented platform foundation with a web interface.

## Current version

**v0.2.0 — Module Runtime + Диск Yukiyasha**

The current release provides:
- modular Python core and module registry;
- explicit module lifecycle and health;
- first module: sandboxed local **Диск Yukiyasha**;
- FastAPI web/API layer;
- responsive browser UI;
- automated tests and two-tier CI.

## Requirements

- Python 3.11+

## Quick start

### Windows — one click

Double-click `Yukiyasha.bat`.

The launcher verifies Python, prepares `.venv`, checks ports, starts the server and
opens the browser.

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

Default storage directory:

```text
data/disk
```

Optional custom location:

```bat
set YUKIYASHA_DISK_DIR=D:\YukiyashaData
Yukiyasha.bat
```

API:
- `GET /api/modules`
- `GET /api/disk?path=`
- `GET /api/disk/file?path=`
- `PUT /api/disk/file`
- `DELETE /api/disk/file?path=`

The disk is sandboxed: absolute paths and attempts to escape its root are rejected.

## Quality checks

```bash
ruff check .
pytest
```

## Project structure

```text
src/yukiyasha/
  core/        application runtime
  modules/     module runtime and modules
    disk/      Диск Yukiyasha
  web/         FastAPI application and browser UI
tests/         automated tests
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_STATE.md](PROJECT_STATE.md).
