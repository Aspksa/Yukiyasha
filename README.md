# Yukiyasha

Yukiyasha is a modular AI-oriented platform foundation with a local web interface.

## Current version

**v0.2.1 — Disk and runtime hardening**

The current release provides:
- modular Python core and module registry;
- explicit module lifecycle and health;
- sandboxed local **Диск Yukiyasha**;
- project navigation for **Рабочие проекты** and **Домашние проекты**;
- FastAPI web/API layer;
- automated tests and two-tier CI.

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

The current browser UI can browse the work/home project directories. It does not yet expose
general file editing or module permission controls.

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
  web/         FastAPI application, middleware and browser UI
tests/         isolated automated tests
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_STATE.md](PROJECT_STATE.md).
