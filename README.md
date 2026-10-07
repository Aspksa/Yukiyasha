# Yukiyasha

Yukiyasha is a modular AI-oriented platform foundation with a web interface.

## Current version

**v0.1.0 Foundation**

The first release establishes:
- modular Python core;
- application runtime and configuration;
- FastAPI web/API layer;
- responsive browser UI;
- health and runtime endpoints;
- automated tests and CI;
- architecture, changelog and project-state documentation.

## Requirements

- Python 3.11+

## Quick start

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

## Quality checks

```bash
ruff check .
pytest
```

## Project structure

```text
src/yukiyasha/
  core/        core runtime and domain state
  web/         FastAPI application and browser UI
tests/         automated tests
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_STATE.md](PROJECT_STATE.md).
